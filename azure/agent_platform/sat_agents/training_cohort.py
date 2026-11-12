"""Convierte el dataset del generador de entrenamiento en entidades de las tablas operativas.

Se usa fuera de la Function (scripts/seed_operational_data.py): la probabilidad de
riesgo viene del endpoint de Azure ML (modelo vigente) sobre las mismas variables de entrenamiento y
la etiqueta real va a la tabla de targets, nunca al snapshot.
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable, Mapping, Sequence

from .policy import classify_risk
from .synthetic_database import (
    PERIOD_ID,
    SEED_VERSION,
    SNAPSHOT_CUT,
    TABLE_ACADEMICS,
    TABLE_FINANCE,
    TABLE_SNAPSHOTS,
    TABLE_STUDENTS,
    TABLE_TARGETS,
    TABLE_WELLBEING,
    _FACULTY_BY_PROGRAM,
    _synthetic_name,
)

MAX_ACADEMIC_SIGNALS = 3
MAX_SEMESTER = 9  # el heatmap y los filtros de la UI cubren semestres 1-9
CITY_BY_CAMPUS = {
    "MED": "Medellín",
    "CAL": "Cali",
    "NEI": "Neiva",
    "POP": "Popayán",
    "VIR": "Nacional",
}


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _number(value: Any, default: float = 0.0) -> float:
    value = _clean(value)
    return default if value is None else float(value)


def arrears_months(arrears_balance: float, tuition: float) -> int:
    """Meses de mora estimados: saldo vencido sobre una cuota mensual de seis."""
    if arrears_balance <= 0:
        return 0
    monthly = max(tuition / 6.0, 1.0)
    return int(min(6, max(1, round(arrears_balance / monthly))))


def build_cohort_entities(
    *,
    snapshot_rows: Iterable[Mapping[str, Any]],
    probabilities: Mapping[str, float],
    course_rows: Iterable[Mapping[str, Any]],
    wellbeing_rows: Iterable[Mapping[str, Any]],
    target_rows: Iterable[Mapping[str, Any]],
    program_names: Mapping[str, str],
    campus_names: Mapping[str, str],
    first_number: int = 1,
    numbers: Sequence[int] | None = None,
    model_name: str,
    model_version: str,
    scored_at: str,
    feature_columns: Iterable[str] = (),
) -> dict[str, list[dict[str, Any]]]:
    """Genera las entidades operativas numerando a partir de `first_number` o con `numbers`.

    `snapshot_rows` son filas de estudiante_periodo_corte del periodo operativo y
    `probabilities` la salida del modelo indexada por id de entrenamiento.
    """
    courses_by_student: dict[str, list[Mapping[str, Any]]] = {}
    for row in course_rows:
        if _clean(row.get("cancelada")) in (1, True):
            continue
        courses_by_student.setdefault(str(row["id_estudiante_anon"]), []).append(row)
    wellbeing_by_student = {str(row["id_estudiante_anon"]): row for row in wellbeing_rows}
    target_by_student = {str(row["id_estudiante_anon"]): row for row in target_rows}
    feature_names = list(feature_columns)

    entities: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            TABLE_STUDENTS,
            TABLE_SNAPSHOTS,
            TABLE_ACADEMICS,
            TABLE_FINANCE,
            TABLE_WELLBEING,
            TABLE_TARGETS,
        )
    }
    for offset, row in enumerate(snapshot_rows):
        training_id = str(row["id_estudiante_anon"])
        number = numbers[offset] if numbers is not None else first_number + offset
        student_id = f"ST-SYN-{number:06d}"
        first_name, last_name = _synthetic_name(number)
        program_code = str(row["programa"])
        campus_code = str(row["sede"])
        probability = float(probabilities[training_id])
        tuition = _number(row.get("monto_matricula"))
        arrears_balance = _number(row.get("saldo_mora"))
        financing = _clean(row.get("tipo_financiacion")) or "Sin registro"
        has_arrears = arrears_balance > 0

        entities[TABLE_STUDENTS].append(
            {
                "PartitionKey": "students",
                "RowKey": student_id,
                "StudentId": student_id,
                "FirstName": first_name,
                "LastName": last_name,
                "DisplayName": f"{first_name} {last_name}",
                "DocumentId": f"{number:09d}",
                "ProgramCode": program_code,
                "ProgramName": program_names[program_code],
                "CampusCode": campus_code,
                "CampusName": campus_names[campus_code],
                "Modality": str(row["modalidad"]),
                "Semester": int(min(MAX_SEMESTER, max(1, _number(row.get("semestres_cursados"), 1)))),
                "Stratum": int(_number(row.get("estrato_socioeconomico"), 3)),
                "City": CITY_BY_CAMPUS.get(campus_code, campus_names[campus_code]),
                "FamilyContext": (
                    "has_dependents" if _number(row.get("jefe_hogar")) else "no_dependents"
                ),
                "TrainingStudentId": training_id,
                "Faculty": _FACULTY_BY_PROGRAM.get(program_code, ""),
            }
        )
        features = {
            name: _clean(row.get(name)) for name in feature_names if name in row
        }
        entities[TABLE_SNAPSHOTS].append(
            {
                "PartitionKey": PERIOD_ID,
                "RowKey": student_id,
                "StudentId": student_id,
                "CaseId": f"syn-{student_id.lower()}",
                "PeriodId": PERIOD_ID,
                "Cut": SNAPSHOT_CUT,
                "ModelProbability": round(probability, 4),
                "RiskLevel": classify_risk(probability),
                "Status": "pending",
                "BatchId": "",
                "ReviewId": "",
                "SeedVersion": SEED_VERSION,
                "ModelName": model_name,
                "ModelVersion": str(model_version),
                "ScoredAt": scored_at,
                "TrainingStudentId": training_id,
                "TrainingPeriodId": str(row["periodo_id"]),
                "FeaturesJson": json.dumps(features, ensure_ascii=False, default=str),
            }
        )
        entities[TABLE_FINANCE].append(
            {
                "PartitionKey": student_id,
                "RowKey": PERIOD_ID,
                "StudentId": student_id,
                "PeriodId": PERIOD_ID,
                "EventType": "mora" if has_arrears else "liquidacion",
                "ArrearsMonths": arrears_months(arrears_balance, tuition),
                "ArrearsBalanceCop": int(round(arrears_balance)),
                "FinancingType": str(financing),
                "HasScholarship": bool(_number(row.get("tiene_beca"))),
            }
        )

        wellbeing = wellbeing_by_student.get(training_id)
        attended = bool(wellbeing is not None and _clean(wellbeing.get("asistio")) in (1, True))
        entities[TABLE_WELLBEING].append(
            {
                "PartitionKey": student_id,
                "RowKey": PERIOD_ID,
                "StudentId": student_id,
                "PeriodId": PERIOD_ID,
                "SupportType": (_clean(wellbeing.get("tipo_apoyo")) or "") if wellbeing else "",
                "Sessions": int(_number(wellbeing.get("num_sesiones"))) if wellbeing else 0,
                "Attended": attended,
                "Channel": (_clean(wellbeing.get("canal")) or "Sin registro") if wellbeing else "Sin registro",
            }
        )

        target = target_by_student.get(training_id)
        if target is not None and _clean(target.get("target_desercion")) is not None:
            entities[TABLE_TARGETS].append(
                {
                    "PartitionKey": PERIOD_ID,
                    "RowKey": student_id,
                    "StudentId": student_id,
                    "PeriodId": PERIOD_ID,
                    "TargetDesercion": int(target["target_desercion"]),
                }
            )

        signals = sorted(
            courses_by_student.get(training_id, []),
            key=lambda item: _number(item.get("nota_primer_corte"), 5.0),
        )[:MAX_ACADEMIC_SIGNALS]
        for position, course in enumerate(signals, start=1):
            entities[TABLE_ACADEMICS].append(
                {
                    "PartitionKey": student_id,
                    "RowKey": f"{PERIOD_ID}-COURSE-{position:02d}",
                    "StudentId": student_id,
                    "PeriodId": PERIOD_ID,
                    "CourseCode": str(course["asignatura_id"]),
                    "GradeAtFirstCut": round(_number(course.get("nota_primer_corte")), 2),
                    "AttendancePctAtCut": round(_number(course.get("asistencia_pct")), 1),
                }
            )
    return entities
