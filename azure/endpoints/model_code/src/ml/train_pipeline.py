"""
=============================================================================
SAT-FUMC: Pipeline de Machine Learning — Modelo Predictivo de Deserción
=============================================================================
Modelos seleccionados:
  1. XGBoost Classifier (Optimo para datos tabulares heterogeneos y SHAP)
  2. LightGBM Classifier (Optimo en velocidad, eficiencia y patrones no lineales)

Basado en:
  - diccionario_datos_SAT_desercion_FUMC.xlsx
  - PredictiveModel.md
  - AIArchitecture.md
=============================================================================
"""
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import warnings
import json
import joblib
import os
import sys
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore")

# --- Configurar entorno para MLflow y Matplotlib en Windows ---
os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
os.environ["MPLCONFIGDIR"] = str(Path(__file__).parent.parent.parent / "data" / ".mpl")

# --- MLflow ---
import mlflow
import mlflow.sklearn

# --- Scikit-learn ---
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OrdinalEncoder
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    f1_score, recall_score, precision_score, roc_auc_score,
    confusion_matrix, classification_report, brier_score_loss,
    average_precision_score
)

# --- Los dos modelos mas potentes para datos tabulares ---
import xgboost as xgb
import lightgbm as lgb

# --- SHAP ---
import shap

# =============================================================================
# CONFIGURACIÓN
# =============================================================================
BASE_DIR   = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
from src.ml.feature_engineering import (
    engineer_features,
    feature_columns,
    require_feature_schema,
    temporal_holdout,
)
from src.agents.agent_ingestion import AgentIngestion
from src.agents.agent_quality import AgentQuality

DATA_DIR   = BASE_DIR / "data" / "raw"
PROC_DIR   = BASE_DIR / "data" / "processed"
PRED_DIR   = BASE_DIR / "data" / "predictions"
MLRUNS_DIR = BASE_DIR / "mlruns"
MODELS_DIR = BASE_DIR / "models"

for d in [PROC_DIR, PRED_DIR, MLRUNS_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

mlflow.set_tracking_uri(str(MLRUNS_DIR))
mlflow.set_experiment("SAT_FUMC_Desercion_v1")

RANDOM_STATE = 42
TARGET_COL   = "target_desercion"
THRESHOLD    = 0.35   # Optimizado para aumentar Recall (prioridad institucional)

print("=" * 70)
print("SAT-FUMC — Pipeline de Machine Learning (Top 2 Modelos: XGBoost y LightGBM)")
print("=" * 70)

# =============================================================================
# 1. CARGA DE DATOS
# =============================================================================
print("\n[1] Cargando datos del Digital Twin...")

ingested = AgentIngestion().run({"data_dir": str(DATA_DIR), "require_target": True})
quality = AgentQuality().run(ingested)
main_df = quality["clean_df"]
target_df = quality["target_df"]

with (PROC_DIR / "data_quality_report.json").open("w", encoding="utf-8") as report_file:
    json.dump(
        {"metrics": quality["metrics_quality"], "rules": quality["quality_report"]},
        report_file,
        indent=2,
        ensure_ascii=False,
    )

print(f"   Tabla principal:  {len(main_df):,} filas x {main_df.shape[1]} cols")
print(f"   Target:           {len(target_df):,} filas")

df = main_df.merge(
    target_df[["id_estudiante_anon", "periodo_id", TARGET_COL]],
    on=["id_estudiante_anon", "periodo_id"],
    how="inner"
)
print(f"   Dataset unido:    {len(df):,} filas")
vc = df[TARGET_COL].value_counts()
print(f"      Activo (0):    {vc.get(0, 0):,} ({vc.get(0, 0)/len(df):.1%})")
print(f"      Desertor (1):  {vc.get(1, 0):,} ({vc.get(1, 0)/len(df):.1%})")

require_feature_schema(df)

# =============================================================================
# 3. FEATURE ENGINEERING AVANZADO
# =============================================================================
print("\n[3] Generando interacciones y variables compuestas...")
df = engineer_features(df)
NUMERIC_FEATURES, CATEGORICAL_FEATURES = feature_columns(df)
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

print(f"   Total de variables de entrada para el modelo: {len(ALL_FEATURES)}")

# =============================================================================
# 4. PARTICION TEMPORAL (Por Periodos / Cohortes)
# =============================================================================
print("\n[4] Dividiendo train / test por ventana temporal...")

X = df[ALL_FEATURES].copy()
y = df[TARGET_COL].copy()

mask_train, mask_test, PERIODOS_TEST = temporal_holdout(df)

X_train, y_train = X[mask_train], y[mask_train]
X_test,  y_test  = X[mask_test],  y[mask_test]

print(f"   Entrenamiento (2021-2024): {len(X_train):,} registros")
print(f"   Evaluación test (2025):     {len(X_test):,} registros")

# =============================================================================
# 5. PREPROCESADOR
# =============================================================================
numeric_pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler",  StandardScaler()),
])

categorical_pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="most_frequent")),
    ("encoder", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)),
])

preprocessor = ColumnTransformer([
    ("num", numeric_pipeline,  NUMERIC_FEATURES),
    ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
], remainder="drop")

# =============================================================================
# 6. LOS DOS MODELOS SELECCIONADOS
# =============================================================================
print("\n[5] Configurando XGBoost y LightGBM...")

n_neg = int((y_train == 0).sum())
n_pos = int((y_train == 1).sum())
scale_pos = n_neg / max(n_pos, 1)

MODELS = {
    "XGBoost": Pipeline([
        ("preprocessor", preprocessor),
        ("clf", xgb.XGBClassifier(
            n_estimators=350,
            max_depth=6,
            learning_rate=0.04,
            subsample=0.85,
            colsample_bytree=0.85,
            scale_pos_weight=scale_pos,
            eval_metric="logloss",
            random_state=RANDOM_STATE,
            n_jobs=-1,
            verbosity=0
        ))
    ]),
    "LightGBM": Pipeline([
        ("preprocessor", preprocessor),
        ("clf", lgb.LGBMClassifier(
            n_estimators=350,
            max_depth=7,
            num_leaves=31,
            learning_rate=0.04,
            subsample=0.85,
            colsample_bytree=0.85,
            class_weight="balanced",
            random_state=RANDOM_STATE,
            n_jobs=-1,
            verbose=-1
        ))
    ])
}

# =============================================================================
# 7. ENTRENAMIENTO Y COMPARACIÓN
# =============================================================================
print("\n[6] Entrenando y evaluando modelos...")

results = {}

for model_name, pipeline in MODELS.items():
    print(f"\n   -> Entrenando {model_name}...")
    with mlflow.start_run(run_name=model_name):
        mlflow.log_metric(
            "quality_compliance_pct",
            quality["metrics_quality"]["tasa_cumplimiento_calidad"],
        )
        mlflow.log_param("dataset_version", quality["metrics_quality"]["dataset_version"])
        pipeline.fit(X_train, y_train)
        
        y_proba = pipeline.predict_proba(X_test)[:, 1]
        y_pred  = (y_proba >= THRESHOLD).astype(int)

        f1   = f1_score(y_test, y_pred)
        rec  = recall_score(y_test, y_pred)
        prec = precision_score(y_test, y_pred)
        auc  = roc_auc_score(y_test, y_proba)
        brier = brier_score_loss(y_test, y_proba)

        metrics = {
            "f1": round(f1, 4),
            "recall": round(rec, 4),
            "precision": round(prec, 4),
            "auc_roc": round(auc, 4),
            "brier_score": round(brier, 4),
        }
        mlflow.log_metrics(metrics)

        print(f"      [Metricas] Recall: {rec:.1%} | F1: {f1:.3f} | Precision: {prec:.1%} | AUC-ROC: {auc:.3f}")
        
        model_path = MODELS_DIR / f"model_{model_name}.joblib"
        joblib.dump(pipeline, model_path)

        results[model_name] = {**metrics, "pipeline": pipeline, "y_proba": y_proba, "y_pred": y_pred}

# Selección del campeón
champion_name = "XGBoost" if results["XGBoost"]["recall"] >= results["LightGBM"]["recall"] and results["XGBoost"]["f1"] >= results["LightGBM"]["f1"] else "LightGBM"
if results["LightGBM"]["auc_roc"] > results["XGBoost"]["auc_roc"] + 0.02:
    champion_name = "LightGBM"

champion = results[champion_name]
print(f"\n   [CAMPEON SELECCIONADO]: {champion_name}")
joblib.dump(champion["pipeline"], MODELS_DIR / "model_champion.joblib")

# =============================================================================
# 8. ANÁLISIS DE EQUIDAD Y FAIRNESS
# =============================================================================
print("\n[7] Evaluando equidad / fairness por sede, facultad y genero...")

test_df = df[mask_test].copy()
test_df["y_pred"]  = champion["y_pred"]
test_df["y_proba"] = champion["y_proba"]
test_df["y_true"]  = y_test.values

fairness_records = []
for col in ["sede", "programa", "genero", "jornada"]:
    for val in sorted(test_df[col].dropna().unique()):
        sub = test_df[test_df[col] == val]
        if sub[TARGET_COL].sum() < 3:
            continue
        r = recall_score(sub["y_true"], sub["y_pred"], zero_division=0)
        f = f1_score(sub["y_true"], sub["y_pred"], zero_division=0)
        fairness_records.append({
            "dimension": col, "subgrupo": val, "n": len(sub),
            "desertores_reales": int(sub["y_true"].sum()),
            "recall": round(r, 3), "f1": round(f, 3)
        })

fairness_df = pd.DataFrame(fairness_records)
fairness_df.to_parquet(PROC_DIR / "fairness_report.parquet", index=False)
fairness_df.to_csv(PROC_DIR / "fairness_report.csv", index=False)
print("   Reporte de fairness generado y guardado.")

# =============================================================================
# 9. EXPLICABILIDAD SHAP
# =============================================================================
print("\n[8] Generando explicaciones con TreeSHAP...")

pipe = champion["pipeline"]
X_test_trans = pipe[:-1].transform(X_test)
clf = pipe[-1]

try:
    explainer = shap.TreeExplainer(clf)
    shap_vals = explainer.shap_values(X_test_trans)
    if isinstance(shap_vals, list):
        shap_vals = shap_vals[1]

    feature_names = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    feat_subset = feature_names[:X_test_trans.shape[1]]

    shap_importance = pd.DataFrame({
        "feature": feat_subset,
        "importancia_media": np.abs(shap_vals).mean(axis=0)
    }).sort_values("importancia_media", ascending=False)

    shap_importance.to_csv(PROC_DIR / "shap_global_importance.csv", index=False)
    print("   Top 10 factores determinantes de desercion (SHAP global):")
    for _, r_ in shap_importance.head(10).iterrows():
        print(f"      - {r_['feature']:<35}: {r_['importancia_media']:.4f}")

    # Top factores por estudiante
    test_idx = X_test.index
    shap_students = []
    for i in range(len(test_idx)):
        top5_idx = np.argsort(np.abs(shap_vals[i]))[-5:][::-1]
        s_row = {
            "id_estudiante_anon": df.loc[test_idx[i], "id_estudiante_anon"],
            "periodo_id": df.loc[test_idx[i], "periodo_id"],
            "probabilidad": round(float(champion["y_proba"][i]), 4),
            "factor_ppal": feat_subset[top5_idx[0]] if top5_idx[0] < len(feat_subset) else "",
            "factor_2":    feat_subset[top5_idx[1]] if top5_idx[1] < len(feat_subset) else "",
            "factor_3":    feat_subset[top5_idx[2]] if top5_idx[2] < len(feat_subset) else ""
        }
        shap_students.append(s_row)
    pd.DataFrame(shap_students).to_parquet(PROC_DIR / "shap_por_estudiante.parquet", index=False)

except Exception as err:
    print(f"   Nota en SHAP: {err}")

# =============================================================================
# 10. GENERACIÓN DE PREDICCIONES CONSOLIDADAS
# =============================================================================
print("\n[9] Exportando predicciones consolidadas...")

X_all = df[ALL_FEATURES].copy()
y_proba_all = pipe.predict_proba(X_all)[:, 1]
y_pred_all  = (y_proba_all >= THRESHOLD).astype(int)

intervencion_map = {
    "saldo_mora": "Apoyo socioeconómico — Gestión de créditos/descuentos institucionales",
    "bloqueo_financiero": "Apoyo socioeconómico — Acuerdo de pago inmediato",
    "promedio_acumulado": "Tutoría de permanencia — Refuerzo en asignaturas críticas",
    "en_prueba_academica_actual": "Apoyo psicoeducativo — Acompañamiento tutorial urgente",
    "desconexion_lms": "Fase de acogida — Contacto de reconexión digital",
    "tareas_vencidas": "Apoyo psicoeducativo — Métodos de estudio y gestión del tiempo",
    "asistio_tquieroenlaU": "Vinculación al programa 'Te quiero en la U'",
    "estudiante_vulnerable": "Atención integral — Bienestar universitario y apoyo alimentario/transporte"
}

export_rows = []
for i in range(len(df)):
    prob = float(y_proba_all[i])
    nivel = "Crítico" if prob >= 0.75 else "Alto" if prob >= 0.50 else "Medio" if prob >= 0.25 else "Bajo"
    
    # Determinar intervención
    accion = "Monitoreo preventivo"
    if nivel in ["Alto", "Crítico"]:
        if df.iloc[i].get("saldo_mora", 0) > 400_000:
            accion = intervencion_map["saldo_mora"]
        elif df.iloc[i].get("en_prueba_academica_actual", 0) == 1:
            accion = intervencion_map["en_prueba_academica_actual"]
        elif df.iloc[i].get("engagement_lms", 1.0) < 0.35:
            accion = intervencion_map["desconexion_lms"]
        else:
            accion = intervencion_map["promedio_acumulado"]

    export_rows.append({
        "id_estudiante_anon": df.iloc[i]["id_estudiante_anon"],
        "periodo_id": df.iloc[i]["periodo_id"],
        "programa": df.iloc[i]["programa"],
        "sede": df.iloc[i]["sede"],
        "jornada": df.iloc[i]["jornada"],
        "modalidad": df.iloc[i]["modalidad"],
        "estrato": int(df.iloc[i]["estrato_socioeconomico"]),
        "semestres_cursados": int(df.iloc[i]["semestres_cursados"]),
        "probabilidad_desercion": round(prob, 4),
        "nivel_riesgo": nivel,
        "alerta_activa": int(y_pred_all[i]),
        "intervencion_sugerida": accion,
        "modelo_utilizado": champion_name,
        "fecha_corte": datetime.now().strftime("%Y-%m-%d")
    })

predictions_df = pd.DataFrame(export_rows)
predictions_df.to_parquet(PRED_DIR / "predicciones_estudiante_periodo.parquet", index=False)
predictions_df.to_csv(PRED_DIR / "predicciones_estudiante_periodo.csv", index=False)

print(f"   Predicciones listas:")
print(f"   -> {PRED_DIR / 'predicciones_estudiante_periodo.parquet'} ({len(predictions_df):,} registros)")
print(f"   -> {PRED_DIR / 'predicciones_estudiante_periodo.csv'}")

print("\n" + "=" * 70)
print(f"PIPELINE COMPLETADO CON EXITO CON LOS MODELOS MAS POTENTES")
print(f"Campeon: {champion_name} | Recall: {champion['recall']:.1%} | AUC-ROC: {champion['auc_roc']:.3f}")
print("=" * 70)
