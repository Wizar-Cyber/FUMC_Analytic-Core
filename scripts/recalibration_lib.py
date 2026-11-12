"""Biblioteca de experimentos de recalibración del modelo SAT-FUMC.

Restricciones del experimento (definidas por el proyecto):
  * Se usan exactamente las variables del contrato de entrenamiento
    (``src.ml.feature_engineering``); no se incorporan fuentes nuevas.
  * Se añaden, como mucho, transformaciones determinísticas de esas mismas columnas
    (indicadores de umbral, suma ``promedio_anterior + tendencia``).
  * El umbral se elige solo con validación; el test no se usa para decidir.
  * ``oracle_hazard`` es DIAGNÓSTICO (cota teórica del generador). Nunca es feature.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ml.feature_engineering import (  # noqa: E402
    CATEGORICAL_FEATURES,
    engineer_features,
    feature_columns,
    join_mature_targets,
    temporal_group_train_validation_test_split,
)

TARGET = "target_desercion"
SIZES = [5000, 10000, 15000, 25000, 50000, 75000, 100000]

_PROGRAM_BASE_RISK = {
    "FIS": 0.035, "FON": 0.032, "TOP": 0.033, "NUT": 0.032, "AFD": 0.038,
    "ADE": 0.045, "CON": 0.048, "ASV": 0.060, "SWE": 0.050, "PSI": 0.042,
}


# --------------------------------------------------------------------------- datos
def oracle_hazard(main: pd.DataFrame) -> pd.Series:
    """Riesgo latente instantáneo del generador (diagnóstico, no es feature)."""
    ordered = main.sort_values(["id_estudiante_anon", "periodo_id"])
    support = ((ordered.asistio_tquieroenlaU == 1) & (ordered.num_sesiones_bienestar > 0)).astype(int)
    prev_support = support.groupby(ordered.id_estudiante_anon).shift(1).fillna(0)
    m = ordered
    r = m.programa.map(_PROGRAM_BASE_RISK).astype(float)
    r = r * np.where(m.semestres_cursados == 1, 1.45, 1) * np.where(m.jornada == "Nocturna", 1.3, 1)
    r = r * np.where(m.estrato_socioeconomico <= 2, 1.35, 1) * np.where(m.saldo_mora > 0, 1.5, 1)
    r = r * np.where(m.asistio_tquieroenlaU == 0, 1.2, 1) * np.where(m.promedio_semestre < 3.0, 1.6, 1)
    r = r * np.where(m.modalidad == "Virtual", 1.25, 1) * np.where(m.trabaja == 1, 1.18, 1)
    r = r * np.where(m.jefe_hogar == 1, 1.22, 1) * np.where(m.rezago_academico > 15, 1.4, 1)
    r = r * np.where(m.historial_prueba_academica == 1, 1.55, 1) * np.where(m.tiene_beca == 1, 0.7, 1)
    r = r * np.where(m.bloqueo_financiero == 1, 1.3, 1) * np.where(prev_support == 1, 0.88, 1)
    return pd.Series(np.clip(r, 0.01, 0.95), index=ordered.index).reindex(main.index)


def add_reconstructed_features(df: pd.DataFrame) -> pd.DataFrame:
    """Transformaciones determinísticas de las MISMAS columnas del contrato."""
    out = df.copy()
    prev_avg = out["promedio_semestre_anterior"]
    # promedio del semestre en curso = anterior + tendencia (primer semestre: acumulado)
    out["promedio_semestre_actual_rec"] = np.where(
        prev_avg.isna(), out["promedio_acumulado"], prev_avg + out["tendencia_promedio"]
    )
    out["promedio_bajo_3"] = (out["promedio_semestre_actual_rec"] < 3.0).astype(int)
    out["con_mora"] = (out["saldo_mora"] > 0).astype(int)
    out["rezago_alto_15"] = (out["rezago_academico"] > 15).astype(int)
    out["estrato_bajo"] = (out["estrato_socioeconomico"] <= 2).astype(int)
    out["sin_apoyo_permanencia"] = (out["asistio_tquieroenlaU"] == 0).astype(int)
    out["factor_riesgo_multiplicativo"] = (
        np.where(out["primer_semestre"] == 1, 1.45, 1.0)
        * np.where(out["estrato_bajo"] == 1, 1.35, 1.0)
        * np.where(out["con_mora"] == 1, 1.5, 1.0)
        * np.where(out["sin_apoyo_permanencia"] == 1, 1.2, 1.0)
        * np.where(out["promedio_bajo_3"] == 1, 1.6, 1.0)
        * np.where(out["trabaja"] == 1, 1.18, 1.0)
        * np.where(out["jefe_hogar"] == 1, 1.22, 1.0)
        * np.where(out["rezago_alto_15"] == 1, 1.4, 1.0)
        * np.where(out["historial_prueba_academica"] == 1, 1.55, 1.0)
        * np.where(out["tiene_beca"] == 1, 0.7, 1.0)
        * np.where(out["bloqueo_financiero"] == 1, 1.3, 1.0)
    )
    out["log_factor_riesgo"] = np.log(out["factor_riesgo_multiplicativo"])
    return out


RECONSTRUCTED = [
    "promedio_semestre_actual_rec", "promedio_bajo_3", "con_mora", "rezago_alto_15",
    "estrato_bajo", "sin_apoyo_permanencia", "factor_riesgo_multiplicativo", "log_factor_riesgo",
]


TRAJECTORY = [
    "prom_lag1", "prom_delta", "prom_media_hist", "prom_min_hist", "periodos_prom_bajo",
    "mora_lag1", "periodos_con_mora", "frac_periodos_mora", "mora_racha",
    "apoyo_lag1", "apoyo_frac_hist", "engagement_lag1", "engagement_delta", "engagement_media_hist",
    "tareas_venc_lag1", "reprobados_lag1", "prueba_lag1", "n_snapshots_previos",
]


def add_trajectory_features(main: pd.DataFrame) -> pd.DataFrame:
    """Rezagos y acumulados por estudiante de las MISMAS columnas, solo con periodos <= actual."""
    m = main.sort_values(["id_estudiante_anon", "periodo_id"]).copy()
    g = m.groupby("id_estudiante_anon", sort=False)
    prev_avg = m["promedio_semestre_anterior"]
    prom = pd.Series(np.where(prev_avg.isna(), m["promedio_acumulado"], prev_avg + m["tendencia_promedio"]), index=m.index)
    mora = (m["saldo_mora"] > 0).astype(int)
    apoyo = ((m["asistio_tquieroenlaU"] == 1) & (m["num_sesiones_bienestar"] > 0)).astype(int)
    low = (prom < 3.0).astype(int)
    key = m["id_estudiante_anon"]
    m["prom_lag1"] = prom.groupby(key).shift(1)
    m["prom_delta"] = prom - m["prom_lag1"]
    m["prom_media_hist"] = prom.groupby(key).transform(lambda x: x.expanding().mean())
    m["prom_min_hist"] = prom.groupby(key).transform(lambda x: x.expanding().min())
    m["periodos_prom_bajo"] = low.groupby(key).cumsum()
    m["mora_lag1"] = mora.groupby(key).shift(1)
    m["periodos_con_mora"] = mora.groupby(key).cumsum()
    m["frac_periodos_mora"] = m["periodos_con_mora"] / g.cumcount().add(1)
    streak = mora.groupby([key, (mora == 0).groupby(key).cumsum()]).cumsum()
    m["mora_racha"] = streak
    m["apoyo_lag1"] = apoyo.groupby(key).shift(1)
    m["apoyo_frac_hist"] = apoyo.groupby(key).transform(lambda x: x.expanding().mean())
    m["engagement_lag1"] = m.groupby("id_estudiante_anon")["engagement_lms"].shift(1)
    m["engagement_delta"] = m["engagement_lms"] - m["engagement_lag1"]
    m["engagement_media_hist"] = m.groupby("id_estudiante_anon")["engagement_lms"].transform(lambda x: x.expanding().mean())
    m["tareas_venc_lag1"] = m.groupby("id_estudiante_anon")["tareas_vencidas"].shift(1)
    m["reprobados_lag1"] = m.groupby("id_estudiante_anon")["creditos_reprobados"].shift(1)
    m["prueba_lag1"] = m.groupby("id_estudiante_anon")["en_prueba_academica_actual"].shift(1)
    m["n_snapshots_previos"] = g.cumcount()
    return m.reindex(main.index)


def load_dataset(data_dir: Path) -> tuple[pd.DataFrame, list[str], list[str]]:
    main = pd.read_parquet(data_dir / "estudiante_periodo_corte.parquet")
    target = pd.read_parquet(data_dir / "target_trazabilidad.parquet")
    main = main.copy()
    main["oracle_hazard"] = oracle_hazard(main)
    main = add_trajectory_features(main)
    df = join_mature_targets(main, target)
    df = engineer_features(df)
    df = add_reconstructed_features(df)
    numeric, categorical = feature_columns(df)
    for col in categorical:
        df[col] = df[col].astype("category")
    return df.reset_index(drop=True), numeric, categorical


def make_split(df: pd.DataFrame, seed: int = 42, test_periods: list[str] | None = None):
    """Mismo protocolo del proyecto: test = 2 últimos periodos, estudiantes disjuntos."""
    fit, val, train, test, val_periods, test_p = temporal_group_train_validation_test_split(
        df, number_of_test_periods=2, number_of_validation_periods=1,
        test_periods=test_periods, random_state=seed,
    )
    return {"fit": fit.values, "val": val.values, "train": train.values, "test": test.values,
            "val_periods": val_periods, "test_periods": test_p}


# --------------------------------------------------------------------------- métricas
def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -1e-9, 1 + 1e-9
    idx = np.clip(np.searchsorted(edges, p, side="right") - 1, 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(p[m].mean() - y[m].mean())
    return float(ece)


def decision_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    pred = np.asarray(pred).astype(bool)
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    rec = tp / max(tp + fn, 1)
    prec = tp / max(tp + fp, 1)
    spec = tn / max(tn + fp, 1)
    return {
        "recall": rec, "precision": prec,
        "f1": 2 * prec * rec / max(prec + rec, 1e-12),
        "specificity": spec, "fpr": 1 - spec,
        "alert_rate": float(pred.mean()), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def score_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    y = np.asarray(y).astype(int)
    return {
        "auc_roc": float(roc_auc_score(y, p)),
        "auc_pr": float(average_precision_score(y, p)),
        "brier": float(np.mean((p - y) ** 2)),
        "ece": expected_calibration_error(y, np.asarray(p, dtype=float)),
        "prevalence": float(y.mean()),
    }


def recall_at_alert_rate(y: np.ndarray, p: np.ndarray, rate: float) -> dict[str, float]:
    """Top-k exacto por puntaje: política de capacidad fija."""
    k = max(1, int(round(rate * len(p))))
    order = np.argsort(-p, kind="mergesort")
    pred = np.zeros(len(p), dtype=bool)
    pred[order[:k]] = True
    return decision_metrics(y, pred)


def threshold_for_alert_rate(p_val: np.ndarray, rate: float) -> float:
    return float(np.quantile(p_val, 1 - rate))


def threshold_min_recall(y: np.ndarray, p: np.ndarray, minimum_recall: float = 0.80) -> float:
    """Regla original del proyecto: mayor precisión con recall >= mínimo en validación."""
    from src.ml.model_selection import select_recall_threshold

    return float(select_recall_threshold(y, np.clip(p, 0, 1), minimum_recall=minimum_recall)["threshold"])


def threshold_max_fbeta(y: np.ndarray, p: np.ndarray, beta: float = 2.0) -> float:
    order = np.argsort(-p, kind="mergesort")
    ys = np.asarray(y)[order]
    tp = np.cumsum(ys)
    fp = np.cumsum(1 - ys)
    fn = ys.sum() - tp
    fbeta = (1 + beta**2) * tp / np.maximum((1 + beta**2) * tp + beta**2 * fn + fp, 1)
    return float(np.asarray(p)[order][int(np.argmax(fbeta))])
