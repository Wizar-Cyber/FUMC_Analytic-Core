"""Carga por lotes la cohorte operativa derivada del dataset de entrenamiento.

Lee el dataset del generador (data/raw u otra carpeta), selecciona los estudiantes
matriculados en el periodo operativo, puntúa por lotes contra el endpoint de Azure ML
(AZURE_ML_ENDPOINT_URL / AZURE_ML_ENDPOINT_KEY) y escribe en las tablas Synthetic* solo
los IDs nuevos (ST-SYN-<n>, n > StudentCount). Cada snapshot guarda ModelName,
ModelVersion y ScoredAt. Si el endpoint no responde el sembrado falla: no hay fallback.
Los estudiantes ya sembrados, sus estados y revisiones no se tocan.

Uso:
  python scripts/seed_operational_data.py --dry-run
  python scripts/seed_operational_data.py --count 20000 --generate
  python scripts/seed_operational_data.py --count 20000 --data-dir <carpeta> --model-name X --model-version 3

Requiere AZURE_ML_ENDPOINT_URL y AZURE_ML_ENDPOINT_KEY (las claves no se imprimen) y BLOB_STORAGE_URL (cuenta de las tablas) y una sesión `az login` con rol
Storage Table Data Contributor. El script es reanudable: puede interrumpirse y volver a correr.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))

import pandas as pd  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from sat_agents import synthetic_database as db  # noqa: E402
from sat_agents.training_cohort import build_cohort_entities  # noqa: E402
from src.ml import endpoint_scoring as scoring  # noqa: E402
from src.ml.feature_engineering import REQUIRED_RAW_FEATURES  # noqa: E402

ACTIVE_FRACTION_SAFETY = 0.5
CHECKPOINT_STUDENTS = 1000
WRITE_CONCURRENCY = 50
TRANSACTION_SIZE = 100
SEED_ORDER = (
    db.TABLE_STUDENTS,
    db.TABLE_SNAPSHOTS,
    db.TABLE_TARGETS,
    db.TABLE_FINANCE,
    db.TABLE_WELLBEING,
    db.TABLE_ACADEMICS,
)


def generate_dataset(students: int, output_dir: Path) -> Path:
    if output_dir.exists() and any(output_dir.iterdir()):
        print(f"Reutilizando dataset existente: {output_dir}")
        return output_dir
    env = {**os.environ, "SAT_SYNTHETIC_STUDENTS": str(students), "SAT_OUTPUT_DIR": str(output_dir)}
    print(f"Generando {students} estudiantes de entrenamiento en {output_dir} ...")
    subprocess.run(
        [sys.executable, "-m", "src.data_generation.generate_digital_twin"],
        cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL,
    )
    return output_dir


def load_frames(data_dir: Path) -> dict[str, pd.DataFrame]:
    names = {
        "snapshot": "estudiante_periodo_corte",
        "courses": "estudiante_asignatura_periodo",
        "wellbeing": "bienestar_acompanamiento",
        "targets": "target_trazabilidad",
    }
    return {key: pd.read_parquet(data_dir / f"{value}.parquet") for key, value in names.items()}


def select_cohort(frames: dict[str, pd.DataFrame], needed: int, exclude=frozenset()) -> pd.DataFrame:
    active = frames["snapshot"]
    active = active[active["periodo_id"] == db.PERIOD_ID].sort_values("id_estudiante_anon")
    if exclude:
        active = active[~active["id_estudiante_anon"].astype(str).isin(exclude)]
    if len(active) < needed:
        total = frames["snapshot"]["id_estudiante_anon"].nunique()
        fraction = max(len(active) / max(total, 1), 0.01)
        suggested = math.ceil(needed / min(fraction, ACTIVE_FRACTION_SAFETY) * 1.05)
        raise SystemExit(
            f"El dataset solo tiene {len(active)} estudiantes en {db.PERIOD_ID} y se necesitan {needed}. "
            f"Genera al menos {suggested} estudiantes (use --generate)."
        )
    return active.head(needed).reset_index(drop=True)


def score_cohort(cohort: pd.DataFrame, args) -> tuple[dict[str, float], scoring.ModelInfo, str]:
    settings = scoring.settings_from_env()
    explicit = (args.model_name, args.model_version)
    model = scoring.resolve_model_info(settings, explicit=explicit)
    print(f"Modelo vigente: {model.name} v{model.version} (despliegue {settings.deployment})")
    records = [scoring.clean_record(row, REQUIRED_RAW_FEATURES) for row in cohort.to_dict("records")]
    probabilities = scoring.score_records(
        records, settings, batch_size=args.batch_size, timeout=args.timeout, retries=args.retries,
    )
    after = scoring.resolve_model_info(settings, explicit=explicit)
    if after != model:
        raise SystemExit(
            f"La versión del modelo cambió durante el scoring ({model.version} -> {after.version}); repite el sembrado."
        )
    scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ids = cohort["id_estudiante_anon"].astype(str)
    return dict(zip(ids, probabilities)), model, scored_at


def build(frames, cohort, probabilities, model, scored_at, first_number, numbers=None):
    ids = set(cohort["id_estudiante_anon"].astype(str))
    in_ids = lambda frame: frame[frame["id_estudiante_anon"].astype(str).isin(ids)]  # noqa: E731
    courses = in_ids(frames["courses"])
    wellbeing = in_ids(frames["wellbeing"])
    targets = in_ids(frames["targets"])
    return build_cohort_entities(
        snapshot_rows=cohort.to_dict("records"),
        probabilities=probabilities,
        course_rows=courses[courses["periodo_id"] == db.PERIOD_ID].to_dict("records"),
        wellbeing_rows=wellbeing[wellbeing["periodo_id"] == db.PERIOD_ID].to_dict("records"),
        target_rows=targets[targets["periodo_id"] == db.PERIOD_ID].to_dict("records"),
        program_names={code: name for code, name, _ in db._PROGRAMS},
        campus_names={code: name for code, name, _, _ in db._CAMPUSES},
        first_number=first_number,
        numbers=numbers,
        model_name=model.name,
        model_version=model.version,
        scored_at=scored_at,
        feature_columns=REQUIRED_RAW_FEATURES,
    )


def summarize(entities: dict) -> None:
    snapshots = entities[db.TABLE_SNAPSHOTS]
    probabilities = [row["ModelProbability"] for row in snapshots]
    risks = Counter(row["RiskLevel"] for row in snapshots)
    targets = [row["TargetDesercion"] for row in entities[db.TABLE_TARGETS]]
    programs = Counter(row["ProgramCode"] for row in entities[db.TABLE_STUDENTS])
    campuses = Counter(row["CampusCode"] for row in entities[db.TABLE_STUDENTS])
    n = max(len(snapshots), 1)
    print(f"Estudiantes: {len(snapshots)}  filas por tabla: " + ", ".join(f"{k}={len(v)}" for k, v in entities.items()))
    print(f"Probabilidad media={sum(probabilities) / n:.3f}  riesgo={dict(risks)}")
    if targets:
        print(f"Tasa de deserción real (tabla de targets, separada)={sum(targets) / len(targets):.3f}")
    print(f"Programas: {dict(sorted(programs.items()))}")
    print(f"Sedes: {dict(sorted(campuses.items()))}")


async def write_rows(table, rows: list[dict]) -> None:
    same_partition = len({row["PartitionKey"] for row in rows}) == 1
    if same_partition and len(rows) > 1:
        for offset in range(0, len(rows), TRANSACTION_SIZE):
            chunk = rows[offset : offset + TRANSACTION_SIZE]
            try:
                await table.submit_transaction([("create", row) for row in chunk])
            except Exception:
                await asyncio.gather(*(db._create_if_missing(table, row) for row in chunk))
        return
    semaphore = asyncio.Semaphore(WRITE_CONCURRENCY)

    async def create(row):
        async with semaphore:
            await db._create_if_missing(table, row)

    await asyncio.gather(*(create(row) for row in rows))


async def seed(entities: dict, first_number: int, total_new: int) -> None:
    from azure.data.tables import UpdateMode

    async with db._table_clients() as tables:
        done = 0
        while done < total_new:
            low, high = first_number + done, first_number + min(done + CHECKPOINT_STUDENTS, total_new)
            for name in SEED_ORDER:
                rows = [
                    row for row in entities[name]
                    if low <= db._student_number(row["StudentId"]) < high
                ]
                await write_rows(tables[name], rows)
            done += CHECKPOINT_STUDENTS
            await tables[db.TABLE_CONTROL].upsert_entity(
                entity={
                    "PartitionKey": "control", "RowKey": "poc",
                    "SeedVersion": db.SEED_VERSION, "StudentCount": high - 1,
                },
                mode=UpdateMode.MERGE,
            )
            print(f"  escritos hasta ST-SYN-{high - 1:06d}")
        await db._ensure_operational_data(tables)


async def stored_count() -> int:
    async with db._table_clients() as tables:
        await db._ensure_database(tables)
        state = await tables[db.TABLE_CONTROL].get_entity(partition_key="control", row_key="poc")
        return int(state.get("StudentCount", 0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=db.SYNTHETIC_STUDENT_COUNT, help="Total de estudiantes objetivo")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--generate", action="store_true", help="Genera un dataset con el generador de entrenamiento")
    parser.add_argument("--model-name", default="", help="Nombre del modelo; si falta se resuelve desde el despliegue")
    parser.add_argument("--model-version", default="", help="Versión del modelo; si falta se resuelve desde el despliegue")
    parser.add_argument("--batch-size", type=int, default=scoring.DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout", type=float, default=scoring.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=scoring.DEFAULT_RETRIES)
    parser.add_argument("--existing", type=int, default=None, help="Con --dry-run: estudiantes ya sembrados")
    parser.add_argument("--dry-run", action="store_true", help="Construye y resume sin escribir en Azure")
    args = parser.parse_args()
    if not 1 <= args.count <= db.MAX_SYNTHETIC_STUDENT_COUNT:
        raise SystemExit(f"--count debe estar entre 1 y {db.MAX_SYNTHETIC_STUDENT_COUNT}")

    existing = args.existing if args.dry_run and args.existing is not None else (
        db.COLD_START_LIMIT if args.dry_run else asyncio.run(stored_count())
    )
    if existing > args.count:
        raise SystemExit("--count no puede reducir una cohorte ya sembrada.")
    needed = args.count - existing
    print(f"Sembrados: {existing}  objetivo: {args.count}  nuevos: {needed}")
    if needed == 0:
        print("Nada que sembrar.")
        return 0

    data_dir = args.data_dir
    if args.generate:
        students = math.ceil(needed / ACTIVE_FRACTION_SAFETY)
        data_dir = generate_dataset(students, ROOT / "data" / "synthetic_runs" / f"operational_{students}students")
    frames = load_frames(data_dir)
    cohort = select_cohort(frames, needed)
    try:
        probabilities, model, scored_at = score_cohort(cohort, args)
    except scoring.EndpointScoringError as error:
        raise SystemExit(f"Sembrado abortado: {error}")
    entities = build(frames, cohort, probabilities, model, scored_at, existing + 1)
    summarize(entities)
    if args.dry_run:
        print("Dry-run: no se escribió nada.")
        return 0
    asyncio.run(seed(entities, existing + 1, needed))
    print("Cohorte operativa sembrada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
