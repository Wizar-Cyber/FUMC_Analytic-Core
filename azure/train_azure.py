"""
=============================================================================
SAT-FUMC — Script de Entrenamiento para Azure Machine Learning / Foundry
Modelo Unico: LightGBM Classifier (Optimo para datos tabulares y baja latencia)
=============================================================================
Este script se ejecuta en un Compute Target de Azure ML (o localmente) y:
  - Recibe argumentos CLI (--data_dir, --learning_rate, --n_estimators, etc.)
  - Lee los datos en formato Parquet
  - Aplica ingenieria de caracteristicas segun el diccionario de la FUMC
  - Registra metricas, parametros y artefactos en Azure ML / MLflow Tracking
  - Guarda el modelo en formato MLmodel / Joblib listo para Model Registry y Endpoint
=============================================================================
"""
import os
import argparse
import warnings
import json
import joblib
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

# --- Azure ML / MLflow ---
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
import mlflow
import mlflow.lightgbm
import mlflow.sklearn

from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    f1_score, recall_score, precision_score, roc_auc_score,
    confusion_matrix, classification_report, brier_score_loss
)

import lightgbm as lgb
import shap

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.ml.feature_engineering import (
    engineer_features,
    feature_columns,
    require_feature_schema,
    temporal_holdout,
)
from src.agents.agent_ingestion import AgentIngestion
from src.agents.agent_quality import AgentQuality
from dashboards.render_summary import render_dashboard


def parse_args():
    parser = argparse.ArgumentParser(description="Entrenamiento SAT-FUMC con Azure ML / Foundry")
    parser.add_argument("--data_dir", type=str, default="./data/raw", help="Ruta al directorio de datos raw")
    parser.add_argument("--output_dir", type=str, default="./outputs", help="Directorio de salidas y artefactos")
    parser.add_argument("--n_estimators", type=int, default=350, help="Numero de arboles de LightGBM")
    parser.add_argument("--learning_rate", type=float, default=0.04, help="Tasa de aprendizaje")
    parser.add_argument("--max_depth", type=int, default=7, help="Profundidad maxima de arboles")
    parser.add_argument("--num_leaves", type=int, default=31, help="Numero de hojas")
    parser.add_argument("--threshold", type=float, default=0.35, help="Umbral de decision para alerta temprana")
    parser.add_argument(
        "--test_periods", nargs="+", default=None,
        help="Periodos académicos para prueba temporal; por defecto, los dos más recientes."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not 0 <= args.threshold <= 1:
        raise ValueError("--threshold debe estar entre 0 y 1.")
    if args.n_estimators < 1 or args.num_leaves < 2 or args.max_depth < 1:
        raise ValueError("n_estimators debe ser >=1, num_leaves >=2 y max_depth >=1.")
    if args.learning_rate <= 0:
        raise ValueError("--learning_rate debe ser mayor que cero.")
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("Azure Machine Learning / Foundry — SAT-FUMC Pipeline de Entrenamiento")
    print(f"Modelo Unico: LightGBM | Threshold: {args.threshold}")
    print("=" * 70)

    # Azure ML injects the workspace MLflow tracking URI into the job environment.
    mlflow.set_experiment("SAT-FUMC-Foundry")

    with mlflow.start_run(run_name="LightGBM_Foundry_v1") as run:
        # Registrar hiperparametros
        mlflow.log_params({
            "model_type": "LightGBM",
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
            "num_leaves": args.num_leaves,
            "decision_threshold": args.threshold,
            "source": "Azure_ML_Foundry_FUMC"
        })

        # 1. Reuse the same ingestion and quality gates as the batch agent workflow.
        print(f"[1] Leyendo y validando datos desde: {data_dir}")
        ingested = AgentIngestion().run({"data_dir": str(data_dir), "require_target": True})
        quality = AgentQuality().run(ingested)
        main_df = quality["clean_df"]
        target_df = quality["target_df"]
        mlflow.log_param("dataset_version", quality["metrics_quality"]["dataset_version"])
        mlflow.log_metric(
            "quality_compliance_pct",
            quality["metrics_quality"]["tasa_cumplimiento_calidad"],
        )
        quality_report_path = output_dir / "data_quality_report.json"
        with quality_report_path.open("w", encoding="utf-8") as report_file:
            json.dump(
                {
                    "metrics": quality["metrics_quality"],
                    "rules": quality["quality_report"],
                },
                report_file,
                indent=2,
                ensure_ascii=False,
            )
        mlflow.log_artifact(str(quality_report_path))
        dataset_manifest_path = output_dir / "dataset_manifest.json"
        dataset_manifest = {
            "dataset_version": quality["metrics_quality"]["dataset_version"],
            "processed_at_utc": datetime.now(timezone.utc).isoformat(),
            "data_rows": len(main_df),
            "target_rows": len(target_df),
            "data_path": str(data_dir),
        }
        with dataset_manifest_path.open("w", encoding="utf-8") as manifest_file:
            json.dump(dataset_manifest, manifest_file, indent=2, ensure_ascii=False)
        mlflow.log_artifact(str(dataset_manifest_path))

        df = main_df.merge(
            target_df[["id_estudiante_anon", "periodo_id", "target_desercion"]],
            on=["id_estudiante_anon", "periodo_id"],
            how="left",
            validate="one_to_one"
        )
        if df["target_desercion"].isna().any():
            raise ValueError("Hay registros de datos sin etiqueta target; se cancela el entrenamiento.")
        print(f"    Total registros: {len(df):,}")

        require_feature_schema(df)
        df = engineer_features(df)
        numeric_features, categorical_features = feature_columns(df)
        all_features = numeric_features + categorical_features

        if not all_features:
            raise ValueError("No se encontraron variables predictoras compatibles con el contrato del modelo.")
        print(f"[2] Variables predictoras preparadas: {len(all_features)}")

        # 4. Split temporal (Evita Data Leakage entre semestres)
        mask_train, mask_test, periodos_test = temporal_holdout(df, args.test_periods)

        X_train, y_train = df.loc[mask_train, all_features], df.loc[mask_train, "target_desercion"]
        X_test, y_test = df.loc[mask_test, all_features], df.loc[mask_test, "target_desercion"]

        print(f"[3] Registros entrenamiento: {len(X_train):,} | Registros prueba: {len(X_test):,}")
        if X_train.empty or X_test.empty:
            raise ValueError(
                f"El split temporal quedó vacío (train={len(X_train)}, test={len(X_test)}); "
                f"periodos de test configurados: {periodos_test}."
            )
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            raise ValueError("Entrenamiento y prueba deben incluir las dos clases del target.")

        # 5. Pipeline Preprocesador + LightGBM
        preprocessor = ColumnTransformer([
            ("num", Pipeline([
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler())
            ]), numeric_features),
            ("cat", Pipeline([
                ("imputer", SimpleImputer(strategy="most_frequent")),
                ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1))
            ]), categorical_features)
        ])

        lgbm_model = lgb.LGBMClassifier(
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
            num_leaves=args.num_leaves,
            learning_rate=args.learning_rate,
            subsample=0.85,
            colsample_bytree=0.85,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )

        pipeline = Pipeline([
            ("preprocessor", preprocessor),
            ("classifier", lgbm_model)
        ])

        # 6. Entrenamiento
        print("[4] Entrenando modelo LightGBM...")
        pipeline.fit(X_train, y_train)

        # 7. Evaluacion en Test
        y_proba = pipeline.predict_proba(X_test)[:, 1]
        y_pred = (y_proba >= args.threshold).astype(int)

        recall = recall_score(y_test, y_pred)
        f1 = f1_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred)
        auc_roc = roc_auc_score(y_test, y_proba)
        brier = brier_score_loss(y_test, y_proba)

        metrics = {
            "test_recall": round(recall, 4),
            "test_f1": round(f1, 4),
            "test_precision": round(precision, 4),
            "test_auc_roc": round(auc_roc, 4),
            "test_brier_score": round(brier, 4)
        }
        mlflow.log_metrics(metrics)

        fairness_rows = []
        test_attributes = df.loc[mask_test].reset_index(drop=True)
        for dimension in ("genero", "estrato_socioeconomico", "programa", "modalidad", "sede"):
            if dimension not in test_attributes:
                continue
            groups = test_attributes[dimension].dropna().astype(str).unique()
            recalls = []
            for group in sorted(groups):
                group_mask = test_attributes[dimension].astype(str) == group
                group_y = y_test.reset_index(drop=True)[group_mask]
                if int(group_y.sum()) < 3:
                    continue
                group_recall = recall_score(
                    group_y,
                    y_pred[group_mask.to_numpy()],
                    zero_division=0,
                )
                recalls.append(group_recall)
                fairness_rows.append({
                    "dimension": dimension,
                    "grupo": group,
                    "registros_test": int(group_mask.sum()),
                    "desertores_reales": int(group_y.sum()),
                    "recall": round(float(group_recall), 4),
                })
            if len(recalls) > 1:
                mlflow.log_metric(
                    f"fairness_recall_gap_{dimension}",
                    round(float(max(recalls) - min(recalls)), 4),
                )
        fairness_path = output_dir / "fairness_report.csv"
        pd.DataFrame(fairness_rows).to_csv(fairness_path, index=False)
        mlflow.log_artifact(str(fairness_path))

        print("\n[5] Metricas en Azure ML / Foundry:")
        print(f"    Recall (Sensibilidad): {recall:.1%}")
        print(f"    AUC-ROC:               {auc_roc:.3f}")
        print(f"    F1-Score:              {f1:.3f}")
        print(f"    Precision:             {precision:.1%}")

        # 8. Explicabilidad con TreeSHAP
        print("\n[6] Calculando explicabilidad SHAP...")
        pipe_trans = pipeline[:-1].transform(X_test)
        clf = pipeline[-1]
        explainer = shap.TreeExplainer(clf)
        shap_values = explainer.shap_values(pipe_trans)
        if isinstance(shap_values, list):
            shap_values = shap_values[1]

        shap_df = pd.DataFrame({
            "variable": all_features[:pipe_trans.shape[1]],
            "importancia_media_shap": np.abs(shap_values).mean(axis=0)
        }).sort_values("importancia_media_shap", ascending=False)

        shap_path = output_dir / "shap_feature_importance.csv"
        shap_df.to_csv(shap_path, index=False)
        mlflow.log_artifact(str(shap_path))

        # 9. Guardar y registrar el modelo
        model_save_path = output_dir / "sat_fumc_lightgbm.joblib"
        joblib.dump(pipeline, model_save_path)
        print(f"\n[7] Modelo serializado en: {model_save_path}")

        # Fail the job if registration fails; a successful-looking run without a deployable
        # model is not a valid training result.
        mlflow.sklearn.log_model(
            sk_model=pipeline,
            artifact_path="sat_fumc_lightgbm_model",
            registered_model_name="SAT_FUMC_LightGBM_Model",
            serialization_format="pickle"
        )

        # 10. Generar predicciones finales para Power BI / Azure Data Lake
        print("[8] Generando dataset de scoring final...")
        X_all = df[all_features].copy()
        y_proba_all = pipeline.predict_proba(X_all)[:, 1]
        y_pred_all = (y_proba_all >= args.threshold).astype(int)

        def asignar_intervencion(row, prob):
            if prob >= 0.75:
                nivel = "Crítico"
            elif prob >= 0.50:
                nivel = "Alto"
            elif prob >= 0.25:
                nivel = "Medio"
            else:
                return "Bajo", "Seguimiento preventivo regular"

            if row.get("saldo_mora", 0) > 400_000:
                return nivel, "Apoyo socioeconómico — Acuerdo de financiación o beca"
            elif row.get("en_prueba_academica_actual", 0) == 1:
                return nivel, "Tutoría de permanencia — Acompañamiento tutorial urgente"
            elif row.get("engagement_lms", 1.0) < 0.35:
                return nivel, "Fase de acogida — Contacto de reconexión con plataforma"
            else:
                return nivel, "Apoyo psicoeducativo — Programa 'Te quiero en la U'"

        scoring_rows = []
        for i in range(len(df)):
            p = float(y_proba_all[i])
            r = df.iloc[i]
            nivel, accion = asignar_intervencion(r, p)
            scoring_rows.append({
                "id_estudiante_anon": r["id_estudiante_anon"],
                "periodo_id": r["periodo_id"],
                "programa": r["programa"],
                "sede": r["sede"],
                "jornada": r["jornada"],
                "modalidad": r["modalidad"],
                "estrato": int(r["estrato_socioeconomico"]),
                "probabilidad_desercion": round(p, 4),
                "nivel_riesgo": nivel,
                "alerta_activa": int(y_pred_all[i]),
                "intervencion_sugerida": accion,
                "fecha_scoring": datetime.now().strftime("%Y-%m-%d")
            })

        scoring_df = pd.DataFrame(scoring_rows)
        pbi_parquet = output_dir / "predicciones_powerbi.parquet"
        pbi_csv = output_dir / "predicciones_powerbi.csv"
        scoring_df.to_parquet(pbi_parquet, index=False)
        scoring_df.to_csv(pbi_csv, index=False)
        render_dashboard(scoring_df, output_dir / "dashboard_resumen.html")

        mlflow.log_artifact(str(pbi_parquet))
        mlflow.log_artifact(str(pbi_csv))
        mlflow.log_artifact(str(output_dir / "dashboard_resumen.html"))

        print(f"    Predicciones exportadas a: {pbi_parquet}")
        print("\n" + "=" * 70)
        print("Entrenamiento en Azure Machine Learning completado exitosamente.")
        print("=" * 70)


if __name__ == "__main__":
    main()
