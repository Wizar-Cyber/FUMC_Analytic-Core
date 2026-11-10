from __future__ import annotations

import asyncio
import inspect
import json
import os
import random
import re
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlsplit, urlunsplit

from .policy import (
    CRITICAL_PROBABILITY_THRESHOLD,
    FOLLOWUP_ACTION_LABELS,
    classify_risk,
    is_critical,
)


DEFAULT_SYNTHETIC_STUDENT_COUNT = 5000
SYNTHETIC_STUDENT_COUNT = max(
    1,
    min(int(os.getenv("SYNTHETIC_STUDENT_COUNT", str(DEFAULT_SYNTHETIC_STUDENT_COUNT))), 5000),
)
MAX_BATCH_SIZE = 5
SEED_VERSION = 4
PERIOD_ID = "2025-2"
SNAPSHOT_CUT = "SEMANA_4"
OPERATIONAL_SEED_VERSION = 5

TABLE_STUDENTS = "SyntheticStudents"
TABLE_SNAPSHOTS = "SyntheticSnapshots"
TABLE_ACADEMICS = "SyntheticAcademic"
TABLE_FINANCE = "SyntheticFinance"
TABLE_WELLBEING = "SyntheticWellbeing"
TABLE_TARGETS = "SyntheticTargets"
TABLE_CONTROL = "SyntheticControl"
TABLE_ALERTS = "SyntheticAlerts"
TABLE_FOLLOWUPS = "SyntheticFollowups"
TABLE_TRENDS = "SyntheticDashboardTrends"
TABLE_NAMES = (
    TABLE_STUDENTS,
    TABLE_SNAPSHOTS,
    TABLE_ACADEMICS,
    TABLE_FINANCE,
    TABLE_WELLBEING,
    TABLE_TARGETS,
    TABLE_CONTROL,
    TABLE_ALERTS,
    TABLE_FOLLOWUPS,
    TABLE_TRENDS,
)

_PROGRAMS = (
    ("FIS", "Fisioterapia", 0.234),
    ("FON", "Fonoaudiología", 0.130),
    ("ADE", "Administración de Empresas", 0.182),
    ("CON", "Contaduría Pública", 0.126),
    ("SWE", "Ingeniería de Software", 0.156),
    ("TEM", "Tecnología en Electromedicina", 0.062),
    ("PSI", "Psicología", 0.106),
)
_CAMPUSES = (
    ("MED", "Medellín", "Presencial", 0.548),
    ("CAL", "Cali", "Presencial", 0.159),
    ("NEI", "Neiva", "Presencial", 0.139),
    ("POP", "Popayán", "Presencial", 0.154),
)
_CITIES = ("Medellín", "Cali", "Neiva", "Popayán")
_FACULTY_BY_PROGRAM = {
    "FIS": "Ciencias de la Salud",
    "FON": "Ciencias de la Salud",
    "ADE": "Ciencias Empresariales",
    "CON": "Ciencias Empresariales",
    "SWE": "Ingeniería y Tecnología",
    "TEM": "Ingeniería y Tecnología",
    "PSI": "Ciencias Sociales y Humanas",
}
_SUPPORT_TYPES = (
    "Tutoría académica",
    "Orientación profesional",
    "Apoyo socioeconómico",
    "Taller de nivelación",
)
_FIRST_NAMES = (
    "Ana", "Sofía", "Mateo", "Daniela", "Sebastián", "Valentina", "Camilo", "Laura", "Alejandro",
    "Isabella", "Juan", "María", "Nicolás", "Paula", "Dylan", "Lucía", "Miguel", "Juliana", "Andrés",
    "Gabriela", "Tomás", "Karina", "Esteban", "Daniel", "Sara", "Felipe", "Manuela", "Javier", "Ximena",
    "Cristian", "Tatiana", "Leonardo", "Mariana", "Rafael", "Carmen", "Pablo", "Andrea", "David", "Alejandra",
    "Simón", "Valeria", "Emilio", "Renata", "Edgar", "Lina", "José", "Melissa", "Diego", "Lorena",
    "Hugo", "Catalina", "Mateo", "Yuliana", "Isaac", "Natalia", "Oscar", "Clara", "Mauro", "Diana",
    "Brayan", "Fernanda", "Julián", "Verónica", "Raúl", "Angie", "Néstor", "Patricia", "Gustavo", "Adriana",
    "Ricardo", "Dayana", "Kevin", "Samantha", "Mauricio", "Carolina", "Óscar", "María José", "Samuel", "Elena",
    "Iván", "Vanessa", "Andrés Felipe", "Mónica", "Arturo", "Beatriz", "Juan Pablo", "Isabel", "Luis", "Danna",
    "Ruben", "Marta", "Jorge", "Cecilia", "Roberto", "Viviana", "Erick", "Katherine", "Jhosé", "Alicia",
)
_LAST_NAMES = (
    "Arango", "Barrera", "Castro", "Díaz", "Estrada", "Fernández", "García", "Hernández", "Ibarra",
    "Jiménez", "López", "Molina", "Núñez", "Ospina", "Pérez", "Quintero", "Ramírez", "Sánchez",
    "Torres", "Uribe", "Vargas", "Zapata", "Alvarez", "Blanco", "Cárdenas", "Duarte", "Escobar",
    "Figueroa", "González", "Hoyos", "Jaramillo", "Klein", "Luna", "Mora", "Navarro", "Ortega",
    "Pineda", "Quinones", "Restrepo", "Suárez", "Tobón", "Velásquez", "Wong", "Yañez", "Zuluaga",
    "Aguirre", "Beltrán", "Correa", "Duque", "Echeverri", "Franco", "Giraldo", "Hurtado", "Jurado",
    "Londoño", "Mejía", "Ocampo", "Pabón", "Ríos", "Salazar", "Trujillo", "Valencia", "Villa", "Zulueta",
    "Acosta", "Buitrago", "Castaño", "Echeverry", "Flórez", "Gómez", "López", "Méndez", "Perea", "Rojas",
)
_SEED_LOCK = asyncio.Lock()
_TABLES_READY = False


async def _ensure_synthetic_database_ready() -> None:
    result = ensure_synthetic_database()
    if inspect.isawaitable(result):
        await result


async def _query_entities(table: Any, *, query_filter: str):
    result = table.query_entities(query_filter=query_filter)
    if inspect.isawaitable(result):
        result = await result
    async for row in result:
        yield row


def _synthetic_name(number: int) -> tuple[str, str]:
    first_name = _FIRST_NAMES[(number * 7) % len(_FIRST_NAMES)]
    last_name = _LAST_NAMES[(number * 13 + 3) % len(_LAST_NAMES)]
    return first_name, last_name


def _table_endpoint() -> str:
    blob_url = os.environ.get("BLOB_STORAGE_URL", "").strip()
    parsed = urlsplit(blob_url)
    if not parsed.scheme or not parsed.hostname or ".blob." not in parsed.hostname:
        raise RuntimeError("Configure BLOB_STORAGE_URL para acceder a las tablas sintéticas.")
    host = parsed.hostname.replace(".blob.", ".table.", 1)
    return urlunsplit((parsed.scheme, host, "", "", ""))


@asynccontextmanager
async def _table_clients() -> AsyncIterator[dict[str, Any]]:
    from azure.data.tables.aio import TableServiceClient
    from azure.identity.aio import DefaultAzureCredential

    global _TABLES_READY
    async with DefaultAzureCredential() as credential:
        async with TableServiceClient(
            endpoint=_table_endpoint(), credential=credential
        ) as service:
            if not _TABLES_READY:
                for name in TABLE_NAMES:
                    await service.create_table_if_not_exists(name)
                _TABLES_READY = True
            yield {name: service.get_table_client(name) for name in TABLE_NAMES}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _generate_entities() -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(42)
    entities: dict[str, list[dict[str, Any]]] = {
        name: [] for name in TABLE_NAMES if name != TABLE_CONTROL
    }
    program_codes, program_names, program_weights = zip(*_PROGRAMS)
    campus_codes, campus_names, modalities, campus_weights = zip(*_CAMPUSES)

    for number in range(1, SYNTHETIC_STUDENT_COUNT + 1):
        student_id = f"ST-SYN-{number:06d}"
        first_name, last_name = _synthetic_name(number)
        display_name = f"{first_name} {last_name}"
        case_id = f"syn-{student_id.lower()}"
        program_index = rng.choices(range(len(_PROGRAMS)), weights=program_weights)[0]
        campus_index = rng.choices(range(len(_CAMPUSES)), weights=campus_weights)[0]
        program_code = program_codes[program_index]
        program_name = program_names[program_index]
        campus_code = campus_codes[campus_index]
        campus_name = campus_names[campus_index]
        modality = modalities[campus_index]
        stratum = rng.choices([1, 2, 3, 4, 5, 6], weights=[20, 30, 30, 12, 5, 3])[0]
        semester = rng.randint(1, 9 if program_code == "SWE" else 8)
        city = campus_name
        is_head_of_household = rng.random() < 0.18
        family_context = "has_dependents" if is_head_of_household else "no_dependents"

        has_arrears = rng.random() < (0.35 if stratum <= 2 else 0.15)
        arrears_months = rng.randint(1, 4) if has_arrears else 0
        arrears_balance = rng.randint(50_000, 2_500_000) if has_arrears else 0
        financing = rng.choice(
            ["Recursos propios", "ICETEX crédito", "Beca mérito", "Crédito bancario"]
        )

        academic_base = 3.55 - (0.18 if has_arrears else 0.0) - (0.12 if stratum <= 2 else 0.0)
        signals = []
        for course_number in range(1, 4):
            grade = round(_clamp(rng.gauss(academic_base, 0.58), 0.0, 5.0), 2)
            attendance = round(
                _clamp(rng.gauss(88 if grade >= 3.0 else 69, 10), 35, 100), 1
            )
            signals.append(
                {
                    "course_code": f"{program_code}-A{course_number:03d}",
                    "grade": grade,
                    "attendance_pct": attendance,
                }
            )

        average_grade = sum(item["grade"] for item in signals) / len(signals)
        average_attendance = sum(item["attendance_pct"] for item in signals) / len(signals)
        probability = _clamp(
            0.08
            + (0.20 if average_grade < 3.0 else 0.0)
            + (0.16 if has_arrears else 0.0)
            + (0.12 if average_attendance < 70 else 0.0)
            + (0.10 if stratum <= 2 else 0.0)
            + (0.08 if modality == "Virtual" else 0.0)
            + rng.uniform(-0.035, 0.035),
            0.02,
            0.95,
        )
        risk_level = classify_risk(probability)

        student = {
            "PartitionKey": "students",
            "RowKey": student_id,
            "StudentId": student_id,
            "FirstName": first_name,
            "LastName": last_name,
            "DisplayName": display_name,
            "DocumentId": f"{number:09d}",  # fictitious identity for demo only
            "ProgramCode": program_code,
            "ProgramName": program_name,
            "CampusCode": campus_code,
            "CampusName": campus_name,
            "Modality": modality,
            "Semester": semester,
            "Stratum": stratum,
            "City": city,
            "FamilyContext": family_context,
        }
        snapshot = {
            "PartitionKey": PERIOD_ID,
            "RowKey": student_id,
            "StudentId": student_id,
            "CaseId": case_id,
            "PeriodId": PERIOD_ID,
            "Cut": SNAPSHOT_CUT,
            "ModelProbability": round(probability, 4),
            "RiskLevel": risk_level,
            "Status": "pending",
            "BatchId": "",
            "ReviewId": "",
            "SeedVersion": SEED_VERSION,
        }
        finance = {
            "PartitionKey": student_id,
            "RowKey": PERIOD_ID,
            "StudentId": student_id,
            "PeriodId": PERIOD_ID,
            "EventType": "mora" if has_arrears else "liquidacion",
            "ArrearsMonths": arrears_months,
            "ArrearsBalanceCop": arrears_balance,
            "FinancingType": financing,
            "HasScholarship": financing == "Beca mérito",
        }
        support_attended = rng.random() < (0.42 if average_grade < 3.5 or has_arrears else 0.20)
        wellbeing = {
            "PartitionKey": student_id,
            "RowKey": PERIOD_ID,
            "StudentId": student_id,
            "PeriodId": PERIOD_ID,
            "SupportType": rng.choice(_SUPPORT_TYPES) if support_attended else "",
            "Sessions": rng.randint(1, 4) if support_attended else 0,
            "Attended": support_attended,
            "Channel": rng.choice(["Presencial", "Virtual", "Híbrido"]),
        }
        target = {
            "PartitionKey": PERIOD_ID,
            "RowKey": student_id,
            "StudentId": student_id,
            "PeriodId": PERIOD_ID,
            "TargetDesercion": int(rng.random() < probability),
        }

        entities[TABLE_STUDENTS].append(student)
        entities[TABLE_SNAPSHOTS].append(snapshot)
        entities[TABLE_FINANCE].append(finance)
        entities[TABLE_WELLBEING].append(wellbeing)
        entities[TABLE_TARGETS].append(target)
        for course_number, signal in enumerate(signals, start=1):
            entities[TABLE_ACADEMICS].append(
                {
                    "PartitionKey": student_id,
                    "RowKey": f"{PERIOD_ID}-COURSE-{course_number:02d}",
                    "StudentId": student_id,
                    "PeriodId": PERIOD_ID,
                    "CourseCode": signal["course_code"],
                    "GradeAtFirstCut": signal["grade"],
                    "AttendancePctAtCut": signal["attendance_pct"],
                }
            )
    return entities


async def _ensure_database(tables: dict[str, Any]) -> None:
    control = tables[TABLE_CONTROL]
    try:
        state = await control.get_entity(partition_key="control", row_key="poc")
    except Exception as error:
        from azure.core.exceptions import ResourceNotFoundError

        if not isinstance(error, ResourceNotFoundError):
            raise
        state = {
            "PartitionKey": "control",
            "RowKey": "poc",
            "Enabled": True,
            "SeedVersion": 0,
        }
        await control.create_entity(state)

    if int(state.get("SeedVersion", 0)) >= SEED_VERSION:
        return

    from azure.data.tables import UpdateMode

    entities = _generate_entities()
    for table_name, rows in entities.items():
        table = tables[table_name]
        for offset in range(0, len(rows), 25):
            chunk = rows[offset : offset + 25]
            await asyncio.gather(
                *(
                    table.upsert_entity(entity=row, mode=UpdateMode.REPLACE)
                    for row in chunk
                )
            )

    await control.upsert_entity(
        entity={
            "PartitionKey": "control",
            "RowKey": "poc",
            "Enabled": state.get("Enabled", True),
            "SeedVersion": SEED_VERSION,
            "StudentCount": SYNTHETIC_STUDENT_COUNT,
        },
        mode=UpdateMode.MERGE,
    )


async def _create_if_missing(table: Any, entity: dict[str, Any]) -> None:
    from azure.core.exceptions import ResourceExistsError

    try:
        await table.create_entity(entity=entity)
    except ResourceExistsError:
        pass


async def _ensure_operational_data(tables: dict[str, Any]) -> None:
    from azure.data.tables import UpdateMode

    control = tables[TABLE_CONTROL]
    state = await control.get_entity(partition_key="control", row_key="poc")
    previous_version = int(state.get("OperationalSeedVersion", 0))
    if previous_version >= OPERATIONAL_SEED_VERSION:
        return

    if previous_version > 0:
        for table_name, partition, predicate in (
            (TABLE_ALERTS, "alerts", lambda row: row.get("Source") == "synthetic-risk-rule"),
            (TABLE_FOLLOWUPS, "followups", lambda row: str(row.get("RowKey", "")).startswith("seed-")),
            (TABLE_TRENDS, "dashboard", lambda row: row.get("DataSource") == "simulated-history"),
        ):
            table = tables[table_name]
            old_rows = [
                dict(row)
                async for row in _query_entities(
                    table, query_filter=f"PartitionKey eq '{partition}'"
                )
            ]
            for row in old_rows:
                if predicate(row):
                    await table.delete_entity(
                        partition_key=partition,
                        row_key=str(row["RowKey"]),
                    )

    students = {}
    async for student in _query_entities(
        tables[TABLE_STUDENTS], query_filter="PartitionKey eq 'students'"
    ):
        students[str(student["RowKey"])] = student

    snapshots = []
    async for snapshot in _query_entities(
        tables[TABLE_SNAPSHOTS], query_filter=f"PartitionKey eq '{PERIOD_ID}'"
    ):
        snapshots.append(dict(snapshot))

    alerts = []
    followups = []
    now = datetime.now(timezone.utc).isoformat()
    for snapshot in snapshots:
        probability = float(snapshot["ModelProbability"])
        if snapshot.get("RiskLevel") not in {"Alto", "Medio"}:
            continue
        student_id = str(snapshot["StudentId"])
        student = students.get(student_id)
        if student is None:
            continue
        if snapshot.get("RiskLevel") == "Alto":
            critical = is_critical(probability)
            alerts.append(
                {
                    "PartitionKey": "alerts",
                    "RowKey": f"risk-{student_id}",
                    "AlertId": f"risk-{student_id}",
                    "StudentId": student_id,
                    "Program": str(student["ProgramName"]),
                    "ProgramCode": str(student["ProgramCode"]),
                    "CampusCode": str(student["CampusCode"]),
                    "Campus": str(student["CampusName"]),
                    "City": str(student["City"]),
                    "Semester": int(student["Semester"]),
                    "Severity": "critical" if critical else "high",
                    "Title": "Probabilidad de riesgo crítico" if critical else "Riesgo alto pendiente de revisión",
                    "Status": "open",
                    "ModelProbability": probability,
                    "Source": "synthetic-risk-rule",
                    "CreatedAt": now,
                    "UpdatedAt": now,
                    "History": json.dumps(
                        [{"status": "open", "at": now, "by": "system-seed"}]
                    ),
                }
            )
        followups.append(
            {
                "PartitionKey": "followups",
                "RowKey": f"seed-{student_id}",
                "FollowupId": f"seed-{student_id}",
                "StudentId": student_id,
                "Action": "academic_advisor_review",
                "ActionLabel": "Revisión con asesoría académica",
                "Owner": "Equipo de permanencia",
                "DueDate": (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat(),
                "Status": "in_progress" if int(student_id[-2:]) % 3 == 0 else "open",
                "ReviewId": "",
                "CreatedAt": now,
                "UpdatedAt": now,
                "CreatedBy": "system-seed",
                "History": json.dumps(
                    [{"status": "open", "at": now, "by": "system-seed"}]
                ),
            }
        )

    trend_rows = []
    risk_totals = {
        "high": sum(item.get("RiskLevel") == "Alto" for item in snapshots),
        "medium": sum(item.get("RiskLevel") == "Medio" for item in snapshots),
        "low": sum(item.get("RiskLevel") == "Bajo" for item in snapshots),
    }
    month_ids = ["2025-12", *[f"2026-{month:02d}" for month in range(1, 12)]]
    high_offsets = [-7, -6, -4, -1, 1, 4, 3, 2, 0, -2, -1, 0]
    followup_offsets = [-12, -9, -6, -4, 0, 3, 6, 8, 5, 2, 1, 0]
    total = len(snapshots)
    active_followup_base = len(followups)
    open_alert_base = len(alerts)
    for index, period_id in enumerate(month_ids):
        high_offset = high_offsets[index]
        high = max(0, min(total, risk_totals["high"] + high_offset))
        medium = max(0, min(total - high, risk_totals["medium"] - high_offset // 2))
        trend_rows.append(
            {
                "PartitionKey": "dashboard",
                "RowKey": period_id,
                "PeriodId": period_id,
                "TotalStudents": total,
                "HighRisk": high,
                "MediumRisk": medium,
                "LowRisk": total - high - medium,
                "ActiveFollowups": max(
                    0,
                    min(
                        total,
                        active_followup_base + followup_offsets[index],
                    ),
                ),
                "OpenAlerts": max(0, min(total, open_alert_base + high_offset)),
                "DataSource": "simulated-history",
            }
        )

    for table, rows in (
        (tables[TABLE_ALERTS], alerts),
        (tables[TABLE_FOLLOWUPS], followups),
        (tables[TABLE_TRENDS], trend_rows),
    ):
        for offset in range(0, len(rows), 25):
            await asyncio.gather(
                *(_create_if_missing(table, row) for row in rows[offset : offset + 25])
            )

    await control.upsert_entity(
        entity={
            "PartitionKey": "control",
            "RowKey": "poc",
            "OperationalSeedVersion": OPERATIONAL_SEED_VERSION,
        },
        mode=UpdateMode.MERGE,
    )


async def ensure_synthetic_database() -> None:
    async with _SEED_LOCK:
        async with _table_clients() as tables:
            try:
                await _ensure_database(tables)
                await _ensure_operational_data(tables)
            except Exception as error:
                raise RuntimeError("No se pudo inicializar la base sintética.") from error


def _student_id_from_case_id(case_id: str) -> str:
    if not case_id.startswith("syn-st-syn-"):
        raise ValueError("El id del caso sintético no pertenece a esta base.")
    return case_id[len("syn-") :].upper()


async def _load_case(tables: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    student_id = str(snapshot["StudentId"])
    student = await tables[TABLE_STUDENTS].get_entity(
        partition_key="students", row_key=student_id
    )
    finance = await tables[TABLE_FINANCE].get_entity(
        partition_key=student_id, row_key=PERIOD_ID
    )
    wellbeing = await tables[TABLE_WELLBEING].get_entity(
        partition_key=student_id, row_key=PERIOD_ID
    )
    academic_rows = []
    async for row in _query_entities(
        tables[TABLE_ACADEMICS], query_filter=f"PartitionKey eq '{student_id}'"
    ):
        if row.get("PeriodId") == PERIOD_ID:
            academic_rows.append(row)
    academic_rows.sort(key=lambda row: row["RowKey"])

    return {
        "case_id": snapshot["CaseId"],
        "model_probability": float(snapshot["ModelProbability"]),
        "economic": {
            "arrears_months": int(finance["ArrearsMonths"]),
            "arrears_balance_cop": int(finance["ArrearsBalanceCop"]),
            "socioeconomic_stratum": int(student["Stratum"]),
            "origin_city": str(student["City"]),
            "family_context": str(student["FamilyContext"]),
        },
        "wellbeing": {
            "support_type": wellbeing.get("SupportType") or None,
            "sessions": int(wellbeing.get("Sessions", 0)),
            "attended": bool(wellbeing.get("Attended", False)),
            "channel": wellbeing.get("Channel"),
        },
        "academic_signals": [
            {
                "course_code": str(row["CourseCode"]),
                "grade": float(row["GradeAtFirstCut"]),
                "attendance_pct": float(row["AttendancePctAtCut"]),
            }
            for row in academic_rows[:3]
        ],
    }


async def list_synthetic_cases(limit: int = 20) -> list[dict[str, Any]]:
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        students = {}
        async for student in _query_entities(
            tables[TABLE_STUDENTS], query_filter="PartitionKey eq 'students'"
        ):
            students[str(student["RowKey"])] = student

        cases = []
        async for row in _query_entities(
            tables[TABLE_SNAPSHOTS], query_filter=f"PartitionKey eq '{PERIOD_ID}'"
        ):
            student = students.get(str(row["StudentId"]))
            if student is None:
                continue
            display_name = student.get("DisplayName") or f"{student.get('FirstName', 'Estudiante')} {student.get('LastName', '')}".strip()
            cases.append(
                {
                    "case_id": row["CaseId"],
                    "student_id": row["StudentId"],
                    "display_name": display_name,
                    "first_name": student.get("FirstName", "Estudiante"),
                    "last_name": student.get("LastName", "Sintético"),
                    "scenario": f"{student['ProgramName']} · {student['CampusName']} · semestre {student['Semester']}",
                    "program_code": student["ProgramCode"],
                    "program": student["ProgramName"],
                    "faculty": _FACULTY_BY_PROGRAM.get(
                        str(student["ProgramCode"]), "Facultad sin clasificar"
                    ),
                    "campus_code": student["CampusCode"],
                    "campus": student["CampusName"],
                    "city": student["City"],
                    "modality": student["Modality"],
                    "semester": int(student["Semester"]),
                    "stratum": int(student["Stratum"]),
                    "model_probability": float(row["ModelProbability"]),
                    "risk_level": row["RiskLevel"],
                    "status": row["Status"],
                    "review_id": row.get("ReviewId") or None,
                }
            )
    cases.sort(key=lambda item: item["case_id"])
    return cases[: max(0, min(limit, SYNTHETIC_STUDENT_COUNT))]


async def list_synthetic_students(
    *,
    search: str = "",
    program: str = "",
    campus: str = "",
    city: str = "",
    faculty: str = "",
    semester: str = "",
    risk: str = "",
    min_probability: float = 0.0,
    status: str = "",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    if not 1 <= limit <= 100 or not 0 <= offset <= SYNTHETIC_STUDENT_COUNT:
        raise ValueError(f"La paginación debe ser limit 1–100 y offset 0–{SYNTHETIC_STUDENT_COUNT}.")
    normalized_risk = risk.strip().casefold()
    if normalized_risk and normalized_risk not in {"bajo", "medio", "alto", "critical"}:
        raise ValueError("risk debe ser Bajo, Medio, Alto o critical.")
    normalized_status = status.strip().casefold()
    normalized_semester = semester.strip()
    if normalized_semester and (
        not normalized_semester.isdigit()
        or not 1 <= int(normalized_semester) <= 9
    ):
        raise ValueError("semester debe ser un entero entre 1 y 9.")
    if (
        isinstance(min_probability, bool)
        or not isinstance(min_probability, (int, float))
        or not 0 <= min_probability <= 1
    ):
        raise ValueError("min_probability debe estar entre 0 y 1.")
    if normalized_status and normalized_status not in {"pending", "processing", "processed"}:
        raise ValueError("status debe ser pending, processing o processed.")

    cases = await list_synthetic_cases(SYNTHETIC_STUDENT_COUNT)
    needle = search.strip().casefold()

    def matches_risk(item: dict[str, Any]) -> bool:
        if not normalized_risk:
            return True
        if normalized_risk == "critical":
            return item["model_probability"] >= CRITICAL_PROBABILITY_THRESHOLD
        if normalized_risk == "alto":
            return (
                item["risk_level"].casefold() == "alto"
                and item["model_probability"] < CRITICAL_PROBABILITY_THRESHOLD
            )
        return item["risk_level"].casefold() == normalized_risk

    cohort = [
        item
        for item in cases
        if (not needle or needle in item["student_id"].casefold() or needle in item["display_name"].casefold() or needle in item["program"].casefold() or needle in item["campus"].casefold())
        and (
            not program
            or item["program_code"].casefold() == program.strip().casefold()
            or item["program"].casefold() == program.strip().casefold()
        )
        and (not campus or item["campus_code"].casefold() == campus.strip().casefold())
        and (not city or item["city"].casefold() == city.strip().casefold())
        and (not faculty or item["faculty"].casefold() == faculty.strip().casefold())
        and (not normalized_semester or item["semester"] == int(normalized_semester))
        and item["model_probability"] >= min_probability
        and (not normalized_status or item["status"].casefold() == normalized_status)
    ]
    risk_counts = {"all": len(cohort), "critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in cohort:
        if item["model_probability"] >= CRITICAL_PROBABILITY_THRESHOLD:
            risk_counts["critical"] += 1
        elif item["risk_level"] == "Alto":
            risk_counts["high"] += 1
        elif item["risk_level"] == "Medio":
            risk_counts["medium"] += 1
        else:
            risk_counts["low"] += 1
    filtered = [item for item in cohort if matches_risk(item)]
    filtered.sort(key=lambda item: item["model_probability"], reverse=True)
    return {
        "total": len(filtered),
        "risk_counts": risk_counts,
        "offset": offset,
        "limit": limit,
        "programs": [
            {
                "code": code,
                "name": name,
                "faculty": _FACULTY_BY_PROGRAM[code],
            }
            for code, name, _ in _PROGRAMS
        ],
        "campuses": [
            {"code": code, "name": name} for code, name, _, _ in _CAMPUSES
        ],
        "cities": [{"name": name} for name in sorted(_CITIES)],
        "semesters": list(range(1, 10)),
        "faculties": [
            {"name": name} for name in sorted(set(_FACULTY_BY_PROGRAM.values()))
        ],
        "items": filtered[offset : offset + limit],
    }


async def get_synthetic_student(student_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"ST-SYN-\d{6}", student_id):
        raise ValueError("student_id no pertenece a la base sintética.")
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        student = await tables[TABLE_STUDENTS].get_entity(
            partition_key="students", row_key=student_id
        )
        snapshot = await tables[TABLE_SNAPSHOTS].get_entity(
            partition_key=PERIOD_ID, row_key=student_id
        )
        try:
            finance = await tables[TABLE_FINANCE].get_entity(
                partition_key=student_id, row_key=PERIOD_ID
            )
        except Exception:
            finance = {
                "ArrearsMonths": 0,
                "ArrearsBalanceCop": 0,
                "FinancingType": "Sin registro",
                "HasScholarship": False,
            }
        try:
            wellbeing = await tables[TABLE_WELLBEING].get_entity(
                partition_key=student_id, row_key=PERIOD_ID
            )
        except Exception:
            wellbeing = {
                "SupportType": None,
                "Sessions": 0,
                "Attended": False,
                "Channel": "Sin registro",
            }
        academic = []
        async for row in _query_entities(
            tables[TABLE_ACADEMICS], query_filter=f"PartitionKey eq '{student_id}'"
        ):
            if row.get("PeriodId") == PERIOD_ID:
                academic.append(
                    {
                        "course_code": row.get("CourseCode", "SIN-CURSO"),
                        "grade": float(row.get("GradeAtFirstCut", 0.0)),
                        "attendance_pct": float(row.get("AttendancePctAtCut", 0.0)),
                    }
                )
        academic.sort(key=lambda item: item["course_code"])
        display_name = student.get("DisplayName") or f"{student.get('FirstName', 'Estudiante')} {student.get('LastName', '')}".strip()
        return {
            "student": {
                "student_id": student_id,
                "case_id": snapshot["CaseId"],
                "display_name": display_name,
                "first_name": student.get("FirstName", "Estudiante"),
                "last_name": student.get("LastName", "Sintético"),
                "document_id": student.get("DocumentId"),
                "program_code": student["ProgramCode"],
                "program": student["ProgramName"],
                "faculty": _FACULTY_BY_PROGRAM.get(
                    str(student["ProgramCode"]), "Sin facultad"
                ),
                "campus_code": student["CampusCode"],
                "campus": student["CampusName"],
                "modality": student["Modality"],
                "semester": int(student["Semester"]),
                "stratum": int(student["Stratum"]),
                "city": student["City"],
                "family_context": student["FamilyContext"],
                "model_probability": float(snapshot["ModelProbability"]),
                "risk_level": snapshot["RiskLevel"],
                "status": snapshot["Status"],
                "review_id": snapshot.get("ReviewId") or None,
                "period_id": PERIOD_ID,
                "cut": SNAPSHOT_CUT,
            },
            "academic_signals": academic,
            "finance": {
                "arrears_months": int(finance.get("ArrearsMonths", 0)),
                "arrears_balance_cop": int(finance.get("ArrearsBalanceCop", 0)),
                "financing_type": finance.get("FinancingType", "Sin registro"),
                "has_scholarship": bool(finance.get("HasScholarship", False)),
            },
            "wellbeing": {
                "support_type": wellbeing.get("SupportType") or None,
                "sessions": int(wellbeing.get("Sessions", 0)),
                "attended": bool(wellbeing.get("Attended", False)),
                "channel": wellbeing.get("Channel", "Sin registro"),
            },
        }


async def get_pending_synthetic_cases(limit: int) -> list[dict[str, Any]]:
    if not 1 <= limit <= MAX_BATCH_SIZE:
        raise ValueError(f"El lote debe contener de 1 a {MAX_BATCH_SIZE} casos.")
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        snapshots = []
        async for row in tables[TABLE_SNAPSHOTS].query_entities(
            query_filter=f"PartitionKey eq '{PERIOD_ID}' and Status eq 'pending'"
        ):
            snapshots.append(dict(row))
        snapshots.sort(key=lambda row: row["RowKey"])
        return [await _load_case(tables, row) for row in snapshots[:limit]]


async def claim_synthetic_cases(case_ids: list[str], batch_id: str) -> None:
    await _ensure_synthetic_database_ready()
    claimed: list[str] = []
    try:
        async with _table_clients() as tables:
            table = tables[TABLE_SNAPSHOTS]
            from azure.data.tables import UpdateMode

            for case_id in case_ids:
                student_id = _student_id_from_case_id(case_id)
                snapshot = await table.get_entity(
                    partition_key=PERIOD_ID, row_key=student_id
                )
                if snapshot.get("Status") != "pending":
                    raise RuntimeError("Uno de los casos ya no está pendiente.")
                await table.upsert_entity(
                    entity={
                        "PartitionKey": PERIOD_ID,
                        "RowKey": student_id,
                        "Status": "processing",
                        "BatchId": batch_id,
                        "ReviewId": "",
                    },
                    mode=UpdateMode.MERGE,
                )
                claimed.append(case_id)
    except Exception:
        for case_id in claimed:
            try:
                await update_synthetic_case_status(case_id, "pending")
            except Exception:
                pass
        raise


async def update_synthetic_case_status(
    case_id: str,
    status: str,
    *,
    batch_id: str = "",
    review_id: str = "",
) -> None:
    student_id = _student_id_from_case_id(case_id)
    if status not in {"pending", "processing", "processed"}:
        raise ValueError("Estado sintético no permitido.")
    await _ensure_synthetic_database_ready()
    from azure.data.tables import UpdateMode

    async with _table_clients() as tables:
        table = tables[TABLE_SNAPSHOTS]
        await table.get_entity(
            partition_key=PERIOD_ID, row_key=student_id
        )
        await table.upsert_entity(
            entity={
                "PartitionKey": PERIOD_ID,
                "RowKey": student_id,
                "Status": status,
                "BatchId": batch_id,
                "ReviewId": review_id,
            },
            mode=UpdateMode.MERGE,
        )


async def get_database_summary() -> dict[str, Any]:
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        counts = {"pending": 0, "processing": 0, "processed": 0}
        async for row in _query_entities(
            tables[TABLE_SNAPSHOTS], query_filter=f"PartitionKey eq '{PERIOD_ID}'"
        ):
            status = row.get("Status")
            if status in counts:
                counts[status] += 1
        return {
            "student_count": SYNTHETIC_STUDENT_COUNT,
            "snapshot_count": SYNTHETIC_STUDENT_COUNT,
            "period_id": PERIOD_ID,
            "cut": SNAPSHOT_CUT,
            "pending": counts["pending"],
            "processing": counts["processing"],
            "processed": counts["processed"],
            "table_names": [name for name in TABLE_NAMES if name != TABLE_CONTROL],
            "target_table_separate": TABLE_TARGETS,
            "max_batch_size": MAX_BATCH_SIZE,
        }


async def get_synthetic_dashboard(
    *, campus: str = "", program: str = ""
) -> dict[str, Any]:
    cases = await list_synthetic_cases(SYNTHETIC_STUDENT_COUNT)
    normalized_campus = campus.strip().casefold()
    normalized_program = program.strip().casefold()
    if normalized_campus:
        cases = [
            item
            for item in cases
            if normalized_campus in {item["campus"].casefold(), item["campus_code"].casefold()}
        ]
    if normalized_program:
        cases = [
            item
            for item in cases
            if normalized_program in {item["program"].casefold(), item["program_code"].casefold()}
        ]
    cohort_student_ids = {item["student_id"] for item in cases}
    by_risk = {"Alto": 0, "Medio": 0, "Bajo": 0}
    groups: dict[str, dict[str, dict[str, int]]] = {
        "by_campus": {},
        "by_program": {},
        "by_city": {},
        "by_faculty": {},
    }
    program_semester: dict[str, dict[str, dict[str, int]]] = {}
    for item in cases:
        risk = item["risk_level"]
        if risk in by_risk:
            by_risk[risk] += 1
        for dimension, name in (
            ("by_campus", item["campus"]),
            ("by_program", item["program"]),
            ("by_city", item["city"]),
            ("by_faculty", item["faculty"]),
        ):
            group = groups[dimension].setdefault(
                name, {"total": 0, "high": 0, "medium": 0, "low": 0}
            )
            group["total"] += 1
            risk_key = {"Alto": "high", "Medio": "medium", "Bajo": "low"}.get(risk)
            if risk_key:
                group[risk_key] += 1
        semester_group = program_semester.setdefault(item["program"], {}).setdefault(
            str(item["semester"]),
            {"total": 0, "high": 0, "medium": 0, "low": 0},
        )
        semester_group["total"] += 1
        semester_key = {"Alto": "high", "Medio": "medium", "Bajo": "low"}.get(risk)
        if semester_key:
            semester_group[semester_key] += 1

    summary = await get_database_summary()
    async with _table_clients() as tables:
        alerts = [
            dict(row)
            async for row in _query_entities(
                tables[TABLE_ALERTS], query_filter="PartitionKey eq 'alerts'"
            )
        ]
        followups = [
            dict(row)
            async for row in _query_entities(
                tables[TABLE_FOLLOWUPS], query_filter="PartitionKey eq 'followups'"
            )
        ]
        trends = [
            dict(row)
            async for row in _query_entities(
                tables[TABLE_TRENDS], query_filter="PartitionKey eq 'dashboard'"
            )
        ]
    probability_sum = sum(item["model_probability"] for item in cases)
    active_followup_student_ids = {
        str(row.get("StudentId"))
        for row in followups
        if row.get("Status") in {"open", "in_progress"}
    }
    program_summary = []
    for program, values in sorted(groups["by_program"].items()):
        program_cases = [item for item in cases if item["program"] == program]
        program_summary.append(
            {
                "program": program,
                "faculty": program_cases[0]["faculty"] if program_cases else "",
                "total": values["total"],
                "high": values["high"],
                "medium": values["medium"],
                "low": values["low"],
                "risk_rate": round(values["high"] * 100 / max(values["total"], 1), 1),
                "active_followups": sum(
                    item["student_id"] in active_followup_student_ids
                    for item in program_cases
                ),
                "period_delta_pp": None,
            }
        )
    cohort_ratio = len(cases) / max(SYNTHETIC_STUDENT_COUNT, 1)
    trend_points = []
    for row in trends:
        trend_total = round(int(row["TotalStudents"]) * cohort_ratio)
        trend_high = min(trend_total, round(int(row["HighRisk"]) * cohort_ratio))
        trend_medium = min(
            trend_total - trend_high,
            round(int(row["MediumRisk"]) * cohort_ratio),
        )
        trend_points.append(
            {
                "period_id": row["PeriodId"],
                "total": trend_total,
                "high": trend_high,
                "medium": trend_medium,
                "low": max(0, trend_total - trend_high - trend_medium),
                "active_followups": min(
                    trend_total,
                    round(int(row.get("ActiveFollowups", 0)) * cohort_ratio),
                ),
                "open_alerts": min(
                    trend_total,
                    round(int(row.get("OpenAlerts", 0)) * cohort_ratio),
                ),
                "data_source": row["DataSource"],
            }
        )
    return {
        "total_students": len(cases),
        "high_risk": by_risk["Alto"],
        "medium_risk": by_risk["Medio"],
        "low_risk": by_risk["Bajo"],
        "critical_cases": sum(
            item["model_probability"] >= CRITICAL_PROBABILITY_THRESHOLD
            for item in cases
        ),
        "active_followups": sum(
            row.get("Status") in {"open", "in_progress"}
            and row.get("StudentId") in cohort_student_ids
            for row in followups
        ),
        "open_alerts": sum(
            row.get("Status") in {"open", "acknowledged"}
            and row.get("StudentId") in cohort_student_ids
            for row in alerts
        ),
        "critical_probability_threshold": CRITICAL_PROBABILITY_THRESHOLD,
        "average_model_probability": round(probability_sum / max(len(cases), 1), 4),
        "pending_reviews": summary["processed"],
        "processed_snapshots": summary["processed"],
        "pending_snapshots": summary["pending"],
        **groups,
        "trend": sorted(trend_points, key=lambda row: row["period_id"]),
        "trend_is_simulated": True,
        "trend_filter_estimated": bool(normalized_campus or normalized_program),
        "program_faculty": [
            {
                "program": item["program"],
                "program_code": item["program_code"],
                "faculty": item["faculty"],
            }
            for item in sorted(
                {item["program"]: item for item in cases}.values(),
                key=lambda row: row["program"],
            )
        ],
        "risk_by_program_semester": [
            {"program": program, "semesters": semesters}
            for program, semesters in sorted(program_semester.items())
        ],
        "program_summary": program_summary,
        "period_id": PERIOD_ID,
        "cut": SNAPSHOT_CUT,
        "filter_options": {
            "campuses": [
                {"code": code, "name": name}
                for code, name, _, _ in _CAMPUSES
            ],
            "programs": [
                {"code": code, "name": name}
                for code, name, _ in _PROGRAMS
            ],
        },
        "applied_filters": {"campus": campus, "program": program},
    }


def _public_alert(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": str(entity["AlertId"]),
        "student_id": str(entity["StudentId"]),
        "program": str(entity.get("Program", "")),
        "campus": str(entity.get("Campus", "")),
        "city": str(entity.get("City", "")),
        "semester": int(entity.get("Semester", 0)),
        "severity": str(entity["Severity"]),
        "title": str(entity["Title"]),
        "status": str(entity["Status"]),
        "model_probability": float(entity["ModelProbability"]),
        "source": str(entity["Source"]),
        "created_at": str(entity["CreatedAt"]),
        "updated_at": str(entity["UpdatedAt"]),
    }


def _public_followup(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "followup_id": str(entity["FollowupId"]),
        "student_id": str(entity["StudentId"]),
        "action": str(entity["Action"]),
        "action_label": str(entity["ActionLabel"]),
        "owner": str(entity.get("Owner", "")),
        "due_date": str(entity.get("DueDate", "")),
        "status": str(entity["Status"]),
        "review_id": str(entity.get("ReviewId", "")) or None,
        "created_at": str(entity["CreatedAt"]),
        "updated_at": str(entity["UpdatedAt"]),
    }


async def list_synthetic_alerts(
    *, status: str = "open", limit: int = 100, campus: str = "", program: str = ""
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit debe estar entre 1 y 500.")
    normalized = status.strip().casefold()
    if normalized not in {"all", "open", "acknowledged", "resolved"}:
        raise ValueError("status debe ser all, open, acknowledged o resolved.")
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        entities = [
            dict(row)
            async for row in tables[TABLE_ALERTS].query_entities(
                query_filter="PartitionKey eq 'alerts'"
            )
        ]
    if normalized == "open":
        entities = [row for row in entities if row.get("Status") in {"open", "acknowledged"}]
    elif normalized != "all":
        entities = [row for row in entities if row.get("Status") == normalized]
    normalized_campus = campus.strip().casefold()
    normalized_program = program.strip().casefold()
    if normalized_campus:
        entities = [row for row in entities if normalized_campus in {str(row.get("Campus", "")).casefold(), str(row.get("CampusCode", "")).casefold()}]
    if normalized_program:
        entities = [row for row in entities if normalized_program in {str(row.get("Program", "")).casefold(), str(row.get("ProgramCode", "")).casefold()}]
    entities.sort(key=lambda row: row.get("CreatedAt", ""), reverse=True)
    return [_public_alert(row) for row in entities[:limit]]


async def update_synthetic_alert(
    alert_id: str, status: str, updated_by: str
) -> dict[str, Any]:
    if not re.fullmatch(r"risk-ST-SYN-\d{6}", alert_id):
        raise ValueError("alert_id no pertenece a la base sintética.")
    if status not in {"acknowledged", "resolved"}:
        raise ValueError("status debe ser acknowledged o resolved.")
    if not updated_by:
        raise ValueError("updated_by es obligatorio.")
    await _ensure_synthetic_database_ready()
    from azure.data.tables import UpdateMode

    async with _table_clients() as tables:
        table = tables[TABLE_ALERTS]
        entity = await table.get_entity(partition_key="alerts", row_key=alert_id)
        now = datetime.now(timezone.utc).isoformat()
        history = json.loads(entity.get("History", "[]"))
        if not isinstance(history, list):
            raise RuntimeError("El historial de la alerta no es válido.")
        history.append({"status": status, "at": now, "by": updated_by})
        entity.update(
            {
                "Status": status,
                "UpdatedAt": now,
                "UpdatedBy": updated_by,
                "History": json.dumps(history),
            }
        )
        await table.upsert_entity(entity=entity, mode=UpdateMode.REPLACE)
        return _public_alert(entity)


async def list_synthetic_followups(
    *, status: str = "active", limit: int = 100
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValueError("limit debe estar entre 1 y 500.")
    normalized = status.strip().casefold()
    if normalized not in {"active", "all", "open", "in_progress", "completed"}:
        raise ValueError("status de seguimiento no válido.")
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        entities = [
            dict(row)
            async for row in tables[TABLE_FOLLOWUPS].query_entities(
                query_filter="PartitionKey eq 'followups'"
            )
        ]
    if normalized == "active":
        entities = [row for row in entities if row.get("Status") in {"open", "in_progress"}]
    elif normalized != "all":
        entities = [row for row in entities if row.get("Status") == normalized]
    entities.sort(key=lambda row: (row.get("DueDate", ""), row.get("CreatedAt", "")))
    return [_public_followup(row) for row in entities[:limit]]


async def create_synthetic_followup(
    *,
    student_id: str,
    action: str,
    created_by: str,
    owner: str | None = None,
    review_id: str | None = None,
    due_date: str | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"ST-SYN-\d{6}", student_id):
        raise ValueError("student_id no pertenece a la base sintética.")
    if action not in FOLLOWUP_ACTION_LABELS:
        raise ValueError("La acción de seguimiento no está permitida.")
    if not created_by or len(created_by) > 200:
        raise ValueError("created_by no es válido.")
    if owner is not None and (not owner.strip() or len(owner) > 100):
        raise ValueError("owner debe tener entre 1 y 100 caracteres.")
    if review_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", review_id):
        raise ValueError("review_id no es válido.")
    if due_date is not None:
        try:
            due_date = datetime.fromisoformat(due_date).date().isoformat()
        except ValueError as error:
            raise ValueError("due_date debe tener formato ISO YYYY-MM-DD.") from error

    await _ensure_synthetic_database_ready()
    from azure.core.exceptions import ResourceExistsError

    async with _table_clients() as tables:
        await tables[TABLE_STUDENTS].get_entity(
            partition_key="students", row_key=student_id
        )
        followup_id = f"approval-{review_id}" if review_id else f"manual-{uuid.uuid4().hex}"
        table = tables[TABLE_FOLLOWUPS]
        try:
            entity = await table.get_entity(
                partition_key="followups", row_key=followup_id
            )
            return _public_followup(dict(entity))
        except Exception as error:
            from azure.core.exceptions import ResourceNotFoundError

            if not isinstance(error, ResourceNotFoundError):
                raise
        now = datetime.now(timezone.utc).isoformat()
        due = due_date or (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        entity = {
            "PartitionKey": "followups",
            "RowKey": followup_id,
            "FollowupId": followup_id,
            "StudentId": student_id,
            "Action": action,
            "ActionLabel": FOLLOWUP_ACTION_LABELS[action],
            "Owner": owner.strip() if owner else "Equipo de permanencia",
            "DueDate": due,
            "Status": "open",
            "ReviewId": review_id or "",
            "CreatedAt": now,
            "UpdatedAt": now,
            "CreatedBy": created_by,
            "History": json.dumps([{"status": "open", "at": now, "by": created_by}]),
        }
        try:
            await table.create_entity(entity=entity)
        except ResourceExistsError:
            entity = await table.get_entity(
                partition_key="followups", row_key=followup_id
            )
        return _public_followup(dict(entity))


async def update_synthetic_followup(
    *,
    followup_id: str,
    status: str,
    updated_by: str,
    owner: str | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", followup_id):
        raise ValueError("followup_id no es válido.")
    if status not in {"open", "in_progress", "completed"}:
        raise ValueError("status de seguimiento no válido.")
    if not updated_by or len(updated_by) > 200:
        raise ValueError("updated_by no es válido.")
    if owner is not None and (not owner.strip() or len(owner) > 100):
        raise ValueError("owner debe tener entre 1 y 100 caracteres.")
    await _ensure_synthetic_database_ready()
    from azure.data.tables import UpdateMode

    async with _table_clients() as tables:
        table = tables[TABLE_FOLLOWUPS]
        entity = await table.get_entity(partition_key="followups", row_key=followup_id)
        now = datetime.now(timezone.utc).isoformat()
        history = json.loads(entity.get("History", "[]"))
        if not isinstance(history, list):
            raise RuntimeError("El historial del seguimiento no es válido.")
        history.append({"status": status, "at": now, "by": updated_by})
        entity.update(
            {
                "Status": status,
                "UpdatedAt": now,
                "UpdatedBy": updated_by,
                "History": json.dumps(history),
            }
        )
        if owner is not None:
            entity["Owner"] = owner.strip()
        await table.upsert_entity(entity=entity, mode=UpdateMode.REPLACE)
        return _public_followup(entity)


async def set_batch_case_status(case_id: str, status: str, batch_id: str) -> None:
    await update_synthetic_case_status(
        case_id,
        status,
        batch_id=batch_id if status == "processing" else "",
        review_id=batch_id if status == "processed" else "",
    )


async def get_poc_enabled() -> bool:
    if os.environ.get("POC_ENABLED", "true").strip().lower() != "true":
        return False
    await _ensure_synthetic_database_ready()
    async with _table_clients() as tables:
        try:
            state = await tables[TABLE_CONTROL].get_entity(
                partition_key="control", row_key="poc"
            )
        except Exception as error:
            from azure.core.exceptions import ResourceNotFoundError

            if isinstance(error, ResourceNotFoundError):
                return True
            raise RuntimeError("No se pudo leer el estado de la POC.") from error
        return bool(state.get("Enabled", True))


async def set_poc_enabled(enabled: bool) -> None:
    if not isinstance(enabled, bool):
        raise ValueError("enabled debe ser booleano.")
    if enabled and os.environ.get("POC_ENABLED", "true").strip().lower() != "true":
        raise RuntimeError("La POC está deshabilitada por configuración de servicio.")
    await _ensure_synthetic_database_ready()
    from azure.data.tables import UpdateMode

    async with _table_clients() as tables:
        control = tables[TABLE_CONTROL]
        await control.get_entity(partition_key="control", row_key="poc")
        await control.upsert_entity(
            entity={
                "PartitionKey": "control",
                "RowKey": "poc",
                "Enabled": enabled,
            },
            mode=UpdateMode.MERGE,
        )
