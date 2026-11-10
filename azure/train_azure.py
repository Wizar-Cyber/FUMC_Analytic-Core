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
import hashlib
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
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    f1_score, recall_score, precision_score, roc_auc_score,
    average_precision_score, confusion_matrix, classification_report,
    brier_score_loss, precision_recall_curve, roc_curve,
)
from sklearn.calibration import calibration_curve

import lightgbm as lgb
import shap
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from src.ml.feature_engineering import (
    engineer_features,
    feature_columns,
    join_mature_targets,
    require_feature_schema,
    temporal_group_train_validation_test_split,
)
from src.ml.model_selection import classification_metrics, select_recall_threshold
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
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Sobrescribe el umbral calibrado; úselo solo con aprobación documentada.",
    )
    parser.add_argument(
        "--minimum_recall",
        type=float,
        default=0.80,
        help="Recall mínimo requerido para que el modelo pueda promoverse.",
    )
    parser.add_argument(
        "--max_alert_rate",
        type=float,
        default=None,
        help="Capacidad máxima de alertas como fracción de estudiantes; requerido para promoción.",
    )
    parser.add_argument(
        "--tracking_uri",
        type=str,
        default=None,
        help="MLflow tracking URI; use un directorio temporal para experimentos locales.",
    )
    parser.add_argument(
        "--register_model",
        action="store_true",
        help="Permite registrar el modelo si supera los gates; úselo solo en un AML run aprobado.",
    )
    parser.add_argument(
        "--test_periods", nargs="+", default=None,
        help="Periodos académicos para prueba temporal; por defecto, los dos más recientes."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.threshold is not None and not 0 <= args.threshold <= 1:
        raise ValueError("--threshold debe estar entre 0 y 1.")
    if not 0 < args.minimum_recall <= 1:
        raise ValueError("--minimum_recall debe estar en el intervalo (0, 1].")
    if args.max_alert_rate is not None and not 0 < args.max_alert_rate < 1:
        raise ValueError("--max_alert_rate debe estar en el intervalo (0, 1).")
    if args.n_estimators < 1 or args.num_leaves < 2 or args.max_depth < 1:
        raise ValueError("n_estimators debe ser >=1, num_leaves >=2 y max_depth >=1.")
    if args.learning_rate <= 0:
        raise ValueError("--learning_rate debe ser mayor que cero.")
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print("Azure Machine Learning / Foundry — SAT-FUMC Pipeline de Entrenamiento")
    print(f"Modelo: LightGBM | Recall mínimo de promoción: {args.minimum_recall:.1%}")
    print("=" * 70)

    if args.tracking_uri:
        mlflow.set_tracking_uri(args.tracking_uri)
    # Azure ML injects the workspace MLflow tracking URI into the job environment.
    mlflow.set_experiment("SAT-FUMC-Foundry")

    with mlflow.start_run(run_name="LightGBM_Foundry_v1") as run:
        run_parameters = {
            "model_type": "LightGBM",
            "n_estimators": args.n_estimators,
            "learning_rate": args.learning_rate,
            "max_depth": args.max_depth,
            "num_leaves": args.num_leaves,
            "minimum_recall": args.minimum_recall,
            "source": "Azure_ML_Foundry_FUMC"
        }
        if args.threshold is not None:
            run_parameters["decision_threshold_override"] = args.threshold
        if args.max_alert_rate is not None:
            run_parameters["max_alert_rate"] = args.max_alert_rate
        mlflow.log_params(run_parameters)
        code_hasher = hashlib.sha256()
        for source_path in (Path(__file__), PROJECT_ROOT / "src" / "ml" / "feature_engineering.py"):
            code_hasher.update(source_path.read_bytes())
        code_version = code_hasher.hexdigest()
        mlflow.log_param("code_version_sha256", code_version)

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
            "mature_target_rows": int(
                target_df["target_observado"].fillna(False).astype(bool).sum()
            ) if "target_observado" in target_df else len(target_df),
            "immature_target_rows": int(
                (~target_df["target_observado"].fillna(False).astype(bool)).sum()
            ) if "target_observado" in target_df else 0,
            "data_path": str(data_dir),
        }
        with dataset_manifest_path.open("w", encoding="utf-8") as manifest_file:
            json.dump(dataset_manifest, manifest_file, indent=2, ensure_ascii=False)
        mlflow.log_artifact(str(dataset_manifest_path))

        df = join_mature_targets(main_df, target_df)
        print(
            f"    Filas etiquetadas maduras: {len(df):,} / {len(main_df):,} "
            f"snapshots ({len(df) / max(len(main_df), 1):.1%})"
        )

        require_feature_schema(df)
        df = engineer_features(df)
        numeric_features, categorical_features = feature_columns(df)
        all_features = numeric_features + categorical_features

        if not all_features:
            raise ValueError("No se encontraron variables predictoras compatibles con el contrato del modelo.")
        print(f"[2] Variables predictoras preparadas: {len(all_features)}")

        # 4. Future period and student-disjoint fit/validation/test sets.
        (
            fit_mask,
            validation_mask,
            mask_train,
            mask_test,
            validation_periods,
            periodos_test,
        ) = temporal_group_train_validation_test_split(
            df,
            test_periods=args.test_periods,
            number_of_test_periods=2,
            number_of_validation_periods=1,
        )

        X_train, y_train = df.loc[mask_train, all_features], df.loc[mask_train, "target_desercion"]
        X_test, y_test = df.loc[mask_test, all_features], df.loc[mask_test, "target_desercion"]
        X_fit, y_fit = df.loc[fit_mask, all_features], df.loc[fit_mask, "target_desercion"]
        X_validation = df.loc[validation_mask, all_features]
        y_validation = df.loc[validation_mask, "target_desercion"]

        print(f"[3] Registros entrenamiento: {len(X_train):,} | Registros prueba: {len(X_test):,}")
        if X_train.empty or X_test.empty:
            raise ValueError(
                f"El split temporal quedó vacío (train={len(X_train)}, test={len(X_test)}); "
                f"periodos de test configurados: {periodos_test}."
            )
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            raise ValueError("Entrenamiento y prueba deben incluir las dos clases del target.")

        mlflow.log_metric("fit_students", int(df.loc[fit_mask, "id_estudiante_anon"].nunique()))
        mlflow.log_metric("validation_students", int(df.loc[validation_mask, "id_estudiante_anon"].nunique()))
        mlflow.log_metric("test_students", int(df.loc[mask_test, "id_estudiante_anon"].nunique()))
        if X_fit.empty or X_validation.empty or y_fit.nunique() < 2 or y_validation.nunique() < 2:
            raise ValueError(
                "La ventana temporal interna debe contener ambas clases en ajuste y validación; "
                f"periodo de validación: {validation_periods}. Se requieren más periodos históricos."
            )

        # 6. Pipeline Preprocesador + LightGBM. Search is deliberately small and
        # confined to pre-test data; class_weight handles the observed imbalance.
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

        candidate_params = [
            {
                "n_estimators": args.n_estimators,
                "max_depth": args.max_depth,
                "num_leaves": args.num_leaves,
                "learning_rate": args.learning_rate,
            },
            {
                "n_estimators": max(100, int(args.n_estimators * 0.75)),
                "max_depth": max(3, args.max_depth - 2),
                "num_leaves": max(7, args.num_leaves // 2),
                "learning_rate": args.learning_rate,
            },
            {
                "n_estimators": min(1000, int(args.n_estimators * 1.25)),
                "max_depth": args.max_depth + 2,
                "num_leaves": min(63, args.num_leaves * 2),
                "learning_rate": max(0.01, args.learning_rate * 0.75),
            },
        ]

        candidate_configs = [
            (params, method)
            for params in candidate_params
            for method in ("sigmoid", "isotonic")
        ]
        print(
            "[4] Buscando hiperparámetros, calibrando probabilidades en fit-CV "
            "y seleccionando el umbral en validación temporal..."
        )
        candidates = []
        for candidate_index, (params, calibration_method) in enumerate(candidate_configs, start=1):
            candidate_model = lgb.LGBMClassifier(
                **params,
                subsample=0.85,
                colsample_bytree=0.85,
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
                verbose=-1,
            )
            base_pipeline = Pipeline([
                ("preprocessor", preprocessor),
                ("classifier", candidate_model),
            ])
            candidate_pipeline = CalibratedClassifierCV(
                estimator=base_pipeline,
                method=calibration_method,
                cv=3,
                ensemble=True,
            )
            candidate_pipeline.fit(X_fit, y_fit)
            validation_probabilities = candidate_pipeline.predict_proba(X_validation)[:, 1]
            if args.threshold is None:
                threshold_selection = select_recall_threshold(
                    y_validation,
                    validation_probabilities,
                    minimum_recall=args.minimum_recall,
                    max_alert_rate=args.max_alert_rate,
                )
            else:
                fixed_metrics = classification_metrics(
                    y_validation, validation_probabilities, args.threshold
                )
                threshold_selection = {
                    **fixed_metrics,
                    "threshold": args.threshold,
                    "alert_rate": float(np.mean(validation_probabilities >= args.threshold)),
                    "eligible": (
                        fixed_metrics["recall"] >= args.minimum_recall
                        and np.any(validation_probabilities < args.threshold)
                        and (
                            args.max_alert_rate is None
                            or np.mean(validation_probabilities >= args.threshold)
                            <= args.max_alert_rate
                        )
                    ),
                }
            candidates.append({
                "pipeline": candidate_pipeline,
                "params": params,
                "calibration_method": calibration_method,
                "selection": threshold_selection,
                "validation_probabilities": validation_probabilities,
            })
            print(
                f"    Candidato {candidate_index} ({calibration_method}): "
                f"recall={threshold_selection['recall']:.1%}, "
                f"precision={threshold_selection['precision']:.1%}, "
                f"umbral={threshold_selection['threshold']:.4f}, "
                f"elegible={threshold_selection['eligible']}"
            )

        selected = max(
            candidates,
            key=lambda item: (
                bool(item["selection"]["eligible"]),
                float(item["selection"]["precision"]),
                float(item["selection"]["f1"]),
                float(item["selection"]["recall"]),
            ),
        )
        threshold = float(selected["selection"]["threshold"])
        validation_metrics = selected["selection"]
        mlflow.log_params({f"selected_{key}": value for key, value in selected["params"].items()})
        mlflow.log_param("probability_calibration", selected["calibration_method"])
        mlflow.log_param("threshold_selection_periods", ",".join(validation_periods))
        mlflow.log_param("decision_threshold", threshold)

        # Keep the calibrated fit-only estimator. Validation selects the
        # operating threshold; final test identities are untouched.
        pipeline = selected["pipeline"]

        # 7. Final holdout: never used for threshold or parameter selection.
        y_proba = pipeline.predict_proba(X_test)[:, 1]
        y_pred = (y_proba >= threshold).astype(int)

        test_classification = classification_metrics(y_test, y_proba, threshold)
        recall = test_classification["recall"]
        f1 = test_classification["f1"]
        precision = test_classification["precision"]
        auc_roc = roc_auc_score(y_test, y_proba)
        auc_pr = average_precision_score(y_test, y_proba)
        brier = brier_score_loss(y_test, y_proba)
        test_alert_rate = float(np.mean(y_pred))
        tn, fp, fn, tp = confusion_matrix(y_test, y_pred, labels=[0, 1]).ravel()
        promotion_eligible = bool(
            args.max_alert_rate is not None
            and validation_metrics["eligible"]
            and recall >= args.minimum_recall
            and test_alert_rate < 1.0
            and test_alert_rate <= args.max_alert_rate
        )

        metrics = {
            "test_recall": round(recall, 4),
            "test_f1": round(f1, 4),
            "test_precision": round(precision, 4),
            "test_auc_roc": round(auc_roc, 4),
            "test_auc_pr": round(auc_pr, 4),
            "test_brier_score": round(brier, 4),
            "test_alert_rate": round(test_alert_rate, 4),
            "test_true_negative": int(tn),
            "test_false_positive": int(fp),
            "test_false_negative": int(fn),
            "test_true_positive": int(tp),
            "validation_recall": round(float(validation_metrics["recall"]), 4),
            "validation_precision": round(float(validation_metrics["precision"]), 4),
            "promotion_eligible": int(promotion_eligible),
        }
        mlflow.log_metrics(metrics)
        pipeline.decision_threshold_ = threshold
        pipeline.promotion_eligible_ = promotion_eligible

        evaluation_dir = output_dir / "evaluation"
        evaluation_dir.mkdir(parents=True, exist_ok=True)
        confusion_path = evaluation_dir / "confusion_matrix.csv"
        pd.DataFrame(
            [[tn, fp], [fn, tp]],
            index=["actual_0", "actual_1"],
            columns=["predicted_0", "predicted_1"],
        ).to_csv(confusion_path)
        report_path = evaluation_dir / "classification_report.json"
        report_path.write_text(
            json.dumps(
                classification_report(
                    y_test, y_pred, output_dict=True, zero_division=0
                ),
                indent=2,
            ),
            encoding="utf-8",
        )

        pr_precision, pr_recall, pr_thresholds = precision_recall_curve(y_test, y_proba)
        pr_path = evaluation_dir / "precision_recall_curve.csv"
        pd.DataFrame({
            "threshold": pr_thresholds,
            "precision": pr_precision[:-1],
            "recall": pr_recall[:-1],
        }).to_csv(pr_path, index=False)
        roc_fpr, roc_tpr, roc_thresholds = roc_curve(y_test, y_proba)
        roc_path = evaluation_dir / "roc_curve.csv"
        pd.DataFrame({
            "threshold": roc_thresholds,
            "false_positive_rate": roc_fpr,
            "true_positive_rate": roc_tpr,
        }).to_csv(roc_path, index=False)
        fraction_positive, mean_predicted = calibration_curve(
            y_test, y_proba, n_bins=10, strategy="quantile"
        )
        calibration_path = evaluation_dir / "calibration_curve.csv"
        pd.DataFrame({
            "mean_predicted_probability": mean_predicted,
            "fraction_positive": fraction_positive,
        }).to_csv(calibration_path, index=False)

        figure, axes = plt.subplots(2, 2, figsize=(12, 10))
        axes[0, 0].plot(pr_recall, pr_precision, label=f"AP={auc_pr:.3f}")
        axes[0, 0].set(xlabel="Recall", ylabel="Precision", title="Precision–Recall")
        axes[0, 0].legend()
        axes[0, 1].plot(roc_fpr, roc_tpr, label=f"AUC={auc_roc:.3f}")
        axes[0, 1].plot([0, 1], [0, 1], linestyle="--", color="gray")
        axes[0, 1].set(xlabel="False positive rate", ylabel="True positive rate", title="ROC")
        axes[0, 1].legend()
        axes[1, 0].plot(mean_predicted, fraction_positive, marker="o", label="Model")
        axes[1, 0].plot([0, 1], [0, 1], linestyle="--", color="gray", label="Perfect calibration")
        axes[1, 0].set(xlabel="Mean predicted probability", ylabel="Observed fraction", title="Calibration")
        axes[1, 0].legend()
        axes[1, 1].imshow([[tn, fp], [fn, tp]], cmap="Blues")
        axes[1, 1].set(
            xticks=[0, 1], yticks=[0, 1],
            xticklabels=["Pred 0", "Pred 1"],
            yticklabels=["Actual 0", "Actual 1"],
            title="Confusion matrix",
        )
        for row_index, row_values in enumerate([[tn, fp], [fn, tp]]):
            for col_index, value in enumerate(row_values):
                axes[1, 1].text(col_index, row_index, str(value), ha="center", va="center")
        figure.tight_layout()
        evaluation_plot_path = evaluation_dir / "evaluation_curves.png"
        figure.savefig(evaluation_plot_path, dpi=140)
        plt.close(figure)
        for artifact_path in (
            confusion_path,
            report_path,
            pr_path,
            roc_path,
            calibration_path,
            evaluation_plot_path,
        ):
            mlflow.log_artifact(str(artifact_path))

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
        print(f"    Recall (Sensibilidad): {recall:.1%} (objetivo {args.minimum_recall:.1%})")
        print(f"    AUC-ROC:               {auc_roc:.3f}")
        print(f"    AUC-PR:                {auc_pr:.3f}")
        print(f"    F1-Score:              {f1:.3f}")
        print(f"    Precision:             {precision:.1%}")
        print(f"    Umbral calibrado:      {threshold:.4f}")
        print(f"    Tasa de alertas:       {test_alert_rate:.1%}")
        print(f"    Falsos positivos:      {fp:,}")
        print(f"    Falsos negativos:      {fn:,}")
        print(f"    Promoción autorizada:  {'sí' if promotion_eligible else 'no'}")

        # 8. Explicabilidad con TreeSHAP
        print("\n[6] Calculando explicabilidad SHAP...")
        explanation_pipeline = pipeline.calibrated_classifiers_[0].estimator
        pipe_trans = explanation_pipeline[:-1].transform(X_test)
        clf = explanation_pipeline[-1]
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

        threshold_path = output_dir / "decision_threshold.json"
        threshold_manifest = {
            "dataset_version": quality["metrics_quality"]["dataset_version"],
            "code_version_sha256": code_version,
            "threshold": threshold,
            "probability_calibration": selected["calibration_method"],
            "minimum_recall": args.minimum_recall,
            "max_alert_rate": args.max_alert_rate,
            "validation_periods": validation_periods,
            "validation_metrics": {
                key: value for key, value in validation_metrics.items()
            },
            "test_metrics": metrics,
            "promotion_eligible": promotion_eligible,
        }
        threshold_path.write_text(
            json.dumps(threshold_manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        mlflow.log_artifact(str(threshold_path))

        # Failed candidates remain auditable as run artifacts, but are not
        # registered for endpoint deployment.
        register_model = promotion_eligible and args.register_model
        mlflow.log_metric("model_registered", int(register_model))
        mlflow.set_tag(
            "promotion_status",
            "registered" if register_model else (
                "eligible_pending_explicit_registration"
                if promotion_eligible else "blocked_recall_or_alert_capacity"
            ),
        )
        mlflow.sklearn.log_model(
            sk_model=pipeline,
            artifact_path="sat_fumc_lightgbm_model",
            registered_model_name=(
                "SAT_FUMC_LightGBM_Model" if register_model else None
            ),
            serialization_format="pickle"
        )
        if not promotion_eligible:
            print(
                "[BLOQUEADO] El candidato no alcanzó el Recall mínimo en validación y test "
                "y requiere un máximo de alertas aprobado. No se registró como modelo promovible."
            )
        elif not args.register_model:
            print("[PENDIENTE] Modelo elegible; registro no solicitado en esta ejecución local.")

        # 10. Generar predicciones finales para consumo de la plataforma.
        print("[8] Generando dataset de scoring final...")
        X_all = df[all_features].copy()
        y_proba_all = pipeline.predict_proba(X_all)[:, 1]
        y_pred_all = (y_proba_all >= threshold).astype(int)

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
        predictions_parquet = output_dir / "predicciones_estudiante_periodo.parquet"
        predictions_csv = output_dir / "predicciones_estudiante_periodo.csv"
        scoring_df.to_parquet(predictions_parquet, index=False)
        scoring_df.to_csv(predictions_csv, index=False)
        render_dashboard(scoring_df, output_dir / "dashboard_resumen.html")

        mlflow.log_artifact(str(predictions_parquet))
        mlflow.log_artifact(str(predictions_csv))
        mlflow.log_artifact(str(output_dir / "dashboard_resumen.html"))

        print(f"    Predicciones exportadas a: {predictions_parquet}")
        print("\n" + "=" * 70)
        print("Entrenamiento en Azure Machine Learning completado exitosamente.")
        print("=" * 70)


if __name__ == "__main__":
    main()
