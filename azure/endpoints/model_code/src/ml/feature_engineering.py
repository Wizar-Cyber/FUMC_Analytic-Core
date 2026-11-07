"""Shared feature schema and transformations for training and inference."""

import numpy as np
import pandas as pd


NUMERIC_FEATURES = [
    "semestres_cursados", "antiguedad_institucional_periodos",
    "puntaje_global_prueba_ingreso", "puntaje_matematicas",
    "puntaje_lectura_critica", "puntaje_ingles", "puntaje_ciencias",
    "promedio_semestre_anterior", "promedio_acumulado", "mejor_promedio_hist",
    "peor_promedio_hist", "tendencia_promedio", "creditos_inscritos",
    "creditos_aprobados", "creditos_reprobados", "creditos_acumulados",
    "num_materias_inscritas", "num_materias_perdidas", "num_materias_canceladas",
    "avance_plan_pct", "rezago_academico", "historial_prueba_academica",
    "en_prueba_academica_actual", "estrato_socioeconomico", "edad_en_periodo",
    "trabaja", "jefe_hogar", "discapacidad", "monto_matricula", "saldo_mora",
    "bloqueo_financiero", "tiene_beca", "accesos_lms_semestre", "dias_activos_lms",
    "tareas_vencidas", "participacion_foros", "evaluaciones_completadas",
    "engagement_lms", "asistio_tquieroenlaU", "num_sesiones_bienestar",
    "num_solicitudes_periodo", "tasa_aprobacion", "intensidad_perdida",
    "indice_riesgo_academico", "tendencia_financiera",
]

CATEGORICAL_FEATURES = [
    "programa", "sede", "jornada", "modalidad", "genero",
    "tipo_financiacion", "tipo_ingreso",
]

DERIVED_NUMERIC_FEATURES = [
    "mora_x_prueba", "estrato_x_mora", "engagement_x_promedio",
    "riesgo_financiero_academico", "desconexion_lms", "primer_semestre",
    "estudiante_vulnerable",
]

ALL_NUMERIC_FEATURES = NUMERIC_FEATURES + DERIVED_NUMERIC_FEATURES
REQUIRED_RAW_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def _column(data: pd.DataFrame, name: str, default: float = 0) -> pd.Series:
    if name not in data:
        return pd.Series(default, index=data.index, dtype="float64")
    return data[name]


def engineer_features(data: pd.DataFrame) -> pd.DataFrame:
    """Return a copy enriched with the derived features used by the model."""
    result = data.copy()
    balance = _column(result, "saldo_mora", 0)
    academic_warning = _column(result, "historial_prueba_academica", 0)
    stratum = _column(result, "estrato_socioeconomico", 3)
    engagement = _column(result, "engagement_lms", 0)
    prior_average = _column(result, "promedio_semestre_anterior", 0)
    current_average = _column(result, "promedio_acumulado", 0)
    credits = _column(result, "bloqueo_financiero", 0)
    semesters = _column(result, "semestres_cursados", 1)

    result["mora_x_prueba"] = balance * academic_warning
    result["estrato_x_mora"] = stratum * np.log1p(balance.clip(lower=0))
    result["engagement_x_promedio"] = engagement * prior_average.fillna(0)
    result["riesgo_financiero_academico"] = (
        (balance > 500_000).astype(int)
        + (academic_warning == 1).astype(int)
        + (credits == 1).astype(int)
    )
    result["desconexion_lms"] = (_column(result, "accesos_lms_semestre", 50) < 10).astype(int)
    result["primer_semestre"] = (semesters == 1).astype(int)
    result["estudiante_vulnerable"] = (
        (stratum <= 2).astype(int)
        + _column(result, "trabaja", 0).fillna(0)
        + _column(result, "jefe_hogar", 0).fillna(0)
    ).clip(0, 3)
    return result


def feature_columns(data: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Return the available numeric and categorical model columns in stable order."""
    numeric = [name for name in ALL_NUMERIC_FEATURES if name in data.columns]
    categorical = [name for name in CATEGORICAL_FEATURES if name in data.columns]
    return numeric, categorical


def require_feature_schema(data: pd.DataFrame) -> None:
    """Prevent training on an accidental subset when an upstream source changes."""
    missing = [name for name in REQUIRED_RAW_FEATURES if name not in data.columns]
    if missing:
        raise ValueError(f"Faltan variables requeridas por el contrato de entrenamiento: {missing}")


def temporal_holdout(
    data: pd.DataFrame,
    test_periods: list[str] | None = None,
    number_of_test_periods: int = 2,
) -> tuple[pd.Series, pd.Series, list[str]]:
    """Split by the latest available academic periods unless explicitly configured."""
    if "periodo_id" not in data:
        raise ValueError("Falta periodo_id; no es posible hacer una partición temporal.")
    periods = data["periodo_id"].dropna().astype(str).unique().tolist()
    if not periods:
        raise ValueError("No hay periodos válidos para crear el conjunto de prueba.")

    def period_order(period: str) -> tuple[int, int]:
        try:
            year, semester = period.split("-", maxsplit=1)
            return int(year), int(semester)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Formato de periodo no válido: {period!r}; use YYYY-S.") from exc

    ordered_periods = sorted(periods, key=period_order)
    selected = test_periods or ordered_periods[-number_of_test_periods:]
    missing = sorted(set(selected) - set(periods))
    if missing:
        raise ValueError(f"Los periodos de prueba no existen en los datos: {missing}")
    test_mask = data["periodo_id"].astype(str).isin(selected)
    return ~test_mask, test_mask, list(selected)
