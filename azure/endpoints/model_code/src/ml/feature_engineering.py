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


def join_mature_targets(
    predictors: pd.DataFrame,
    target: pd.DataFrame,
) -> pd.DataFrame:
    """Join only observed forward outcomes; never coerce censored labels to zero."""
    key_columns = ["id_estudiante_anon", "periodo_id"]
    required = {*key_columns, "target_desercion"}
    missing = sorted(required - set(target.columns))
    if missing:
        raise ValueError(f"Faltan columnas requeridas en target: {missing}")
    mature_mask = (
        target["target_observado"].fillna(False).astype(bool)
        if "target_observado" in target
        else pd.Series(True, index=target.index)
    )
    mature_target = target.loc[mature_mask, [*key_columns, "target_desercion"]]
    if mature_target.empty:
        raise ValueError("No hay etiquetas maduras disponibles para entrenar.")
    labels = mature_target["target_desercion"]
    if labels.isna().any() or not labels.isin([0, 1]).all():
        raise ValueError("Las etiquetas maduras deben ser binarias y no nulas.")
    if mature_target.duplicated(key_columns).any():
        raise ValueError("El target maduro tiene llaves estudiante-periodo duplicadas.")
    joined = predictors.merge(
        mature_target,
        on=key_columns,
        how="inner",
        validate="one_to_one",
    )
    if joined.empty:
        raise ValueError("No hay predictores que coincidan con targets maduros.")
    return joined


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


def temporal_group_holdout(
    data: pd.DataFrame,
    *,
    student_column: str = "id_estudiante_anon",
    test_periods: list[str] | None = None,
    number_of_test_periods: int = 2,
    test_fraction: float = 0.20,
    random_state: int = 42,
) -> tuple[pd.Series, pd.Series, list[str]]:
    """Hold out future periods for unseen students; exclude held-out identities from fit.

    The test set contains selected students only in the latest periods. Their
    earlier records are excluded from training, and other students' records in
    the test periods are not reused for training. This is intentionally stricter
    than a period-only split and simulates prospective generalization.
    """
    if student_column not in data:
        raise ValueError(f"Falta la llave de grupo requerida: {student_column}.")
    if data[student_column].isna().any():
        raise ValueError(f"La llave de grupo {student_column} contiene valores nulos.")
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction debe estar entre 0 y 1.")

    test_period_mask, _, selected = temporal_holdout(
        data,
        test_periods=test_periods,
        number_of_test_periods=number_of_test_periods,
    )
    test_period_mask = ~test_period_mask
    candidate_students = np.asarray(
        data.loc[test_period_mask, student_column].astype(str).unique()
    )
    if candidate_students.size < 2:
        raise ValueError("Se requieren al menos dos estudiantes en los periodos de holdout.")

    rng = np.random.default_rng(random_state)
    shuffled_students = rng.permutation(candidate_students)
    test_count = min(
        candidate_students.size - 1,
        max(1, int(np.ceil(candidate_students.size * test_fraction))),
    )
    heldout_students = set(shuffled_students[:test_count].tolist())
    student_mask = data[student_column].astype(str).isin(heldout_students)

    test_mask = test_period_mask & student_mask
    train_mask = ~test_period_mask & ~student_mask
    if not train_mask.any() or not test_mask.any():
        raise ValueError("El split temporal/grupal produjo train o test vacío.")
    return train_mask, test_mask, selected


def temporal_group_train_validation_test_split(
    data: pd.DataFrame,
    *,
    student_column: str = "id_estudiante_anon",
    test_periods: list[str] | None = None,
    number_of_test_periods: int = 2,
    number_of_validation_periods: int = 1,
    test_student_fraction: float = 0.20,
    validation_student_fraction: float = 0.20,
    random_state: int = 42,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series, list[str], list[str]]:
    """Create student-disjoint fit, validation, and future test partitions.

    Test identities are sampled from the latest test periods and excluded from
    all earlier data. Validation identities are sampled from a preceding period
    and excluded from fit. The final training mask includes fit and validation
    data, but never test identities or test periods.
    """
    required = {"periodo_id", student_column}
    missing_columns = required - set(data.columns)
    if missing_columns:
        raise ValueError(f"Faltan columnas para el split: {sorted(missing_columns)}")
    if data[list(required)].isna().any().any():
        raise ValueError("El split temporal/grupal no admite llaves nulas.")
    if number_of_test_periods < 1 or number_of_validation_periods < 1:
        raise ValueError("Debe reservarse al menos un periodo de test y validación.")
    if not 0 < test_student_fraction < 1 or not 0 < validation_student_fraction < 1:
        raise ValueError("Las fracciones de estudiantes deben estar entre 0 y 1.")

    def period_order(period: str) -> tuple[int, int]:
        try:
            year, semester = str(period).split("-", maxsplit=1)
            semester_number = int(semester)
            if semester_number not in (1, 2):
                raise ValueError
            return int(year), semester_number
        except (ValueError, TypeError) as error:
            raise ValueError(f"Formato de periodo no válido: {period!r}; use YYYY-S.") from error

    periods = sorted(data["periodo_id"].astype(str).unique(), key=period_order)
    minimum_periods = number_of_test_periods + number_of_validation_periods + 1
    if len(periods) < minimum_periods:
        raise ValueError(
            f"Se requieren al menos {minimum_periods} periodos para fit, validation y test."
        )
    selected_test_periods = test_periods or periods[-number_of_test_periods:]
    if not selected_test_periods or not set(selected_test_periods).issubset(periods):
        raise ValueError("Los periodos de test deben existir en el dataset.")
    earliest_test_order = min(period_order(period) for period in selected_test_periods)
    periods_before_test = [
        period for period in periods if period_order(period) < earliest_test_order
    ]
    if len(periods_before_test) < number_of_validation_periods + 1:
        raise ValueError("No hay suficientes periodos previos para fit y validation.")
    validation_periods = periods_before_test[-number_of_validation_periods:]
    validation_start = min(validation_periods, key=period_order)

    test_period_rows = data["periodo_id"].astype(str).isin(selected_test_periods)
    test_candidates = data.loc[test_period_rows, student_column].astype(str).unique()
    if test_candidates.size < 2:
        raise ValueError("Se requieren al menos dos estudiantes en el periodo de test.")
    rng = np.random.default_rng(random_state)
    shuffled_test = rng.permutation(test_candidates)
    test_count = min(test_candidates.size - 1, max(1, int(np.ceil(test_candidates.size * test_student_fraction))))
    test_students = set(shuffled_test[:test_count].tolist())

    validation_period_rows = data["periodo_id"].astype(str).isin(validation_periods)
    validation_candidates = data.loc[
        validation_period_rows
        & ~data[student_column].astype(str).isin(test_students),
        student_column,
    ].astype(str).unique()
    if validation_candidates.size < 2:
        raise ValueError("Se requieren al menos dos estudiantes candidatos a validación.")
    shuffled_validation = rng.permutation(validation_candidates)
    validation_count = min(
        validation_candidates.size - 1,
        max(1, int(np.ceil(validation_candidates.size * validation_student_fraction))),
    )
    validation_students = set(shuffled_validation[:validation_count].tolist())

    identities = data[student_column].astype(str)
    period_ids = data["periodo_id"].astype(str)
    period_ordinals = period_ids.map(
        lambda value: period_order(value)[0] * 2 + period_order(value)[1]
    )
    validation_start_ordinal = (
        period_order(validation_start)[0] * 2
        + period_order(validation_start)[1]
    )
    test_mask = test_period_rows & identities.isin(test_students)
    validation_mask = validation_period_rows & identities.isin(validation_students)
    fit_mask = (
        period_ordinals < validation_start_ordinal
    ) & ~identities.isin(test_students | validation_students)
    train_mask = ~test_period_rows & ~identities.isin(test_students)

    if not fit_mask.any() or not validation_mask.any() or not test_mask.any():
        raise ValueError("El split temporal/grupal produjo una partición vacía.")
    if not set(identities[fit_mask]).isdisjoint(identities[validation_mask]):
        raise AssertionError("Hay estudiantes compartidos entre ajuste y validación.")
    if not set(identities[fit_mask | validation_mask]).isdisjoint(identities[test_mask]):
        raise AssertionError("Hay estudiantes compartidos entre desarrollo y test.")
    return (
        fit_mask,
        validation_mask,
        train_mask,
        test_mask,
        validation_periods,
        list(selected_test_periods),
    )
