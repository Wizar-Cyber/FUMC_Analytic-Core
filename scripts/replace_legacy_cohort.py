"""Reemplaza los estudiantes heredados por registros del generador de entrenamiento puntuados por el endpoint.

Heredados = snapshots sin FeaturesJson, sin ModelName y sin TrainingStudentId. Las filas ya
puntuadas por el modelo nunca se tocan. Por defecto es un dry-run que solo imprime conteos;
para ejecutar de verdad hay que pasar --apply.

Con --apply, en este orden:
  1. puntúa el reemplazo contra el endpoint (si falla, aborta sin borrar nada);
  2. respalda a JSONL en outputs/backups/legacy_replacement_<fecha>/ y verifica los conteos;
  3. borra los heredados y sus dependientes (alertas, seguimientos, reviews, tendencias, casos);
  4. siembra el reemplazo reutilizando los números libres ST-SYN-<n> hasta la cohorte objetivo;
  5. ajusta StudentCount y OperationalStudentCount y regenera alertas y seguimientos.

Es reanudable: si se interrumpe, volver a ejecutar el mismo comando continúa donde quedó.
Recomendado: pausar la POC (/api/poc/state) mientras corre.

Uso:
  python scripts/replace_legacy_cohort.py --count 20000 --data-dir <carpeta>
  python scripts/replace_legacy_cohort.py --count 20000 --data-dir <carpeta> --apply

Variables: AZURE_ML_ENDPOINT_URL, AZURE_ML_ENDPOINT_KEY (no se imprimen ni se registran),
BLOB_STORAGE_URL, REVIEWS_CONTAINER (opcional). Requiere `az login` con permisos sobre las tablas.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))
sys.path.insert(0, str(ROOT / "scripts"))

import seed_operational_data as seeding  # noqa: E402
from sat_agents import legacy_replacement as legacy  # noqa: E402
from sat_agents import synthetic_database as db  # noqa: E402
from src.ml import endpoint_scoring as scoring  # noqa: E402

STATE_ROW = "legacy-replacement"
log = logging.getLogger("legacy_replacement")


class BlobReviewStore:
    def __init__(self, container) -> None:
        self.container = container

    async def _read(self, name: str):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            stream = await self.container.get_blob_client(name).download_blob()
            return json.loads(await stream.readall())
        except ResourceNotFoundError:
            return None

    async def export(self, review_id: str):
        proposal = await self._read(f"reviews/{review_id}/proposal.json")
        approval = await self._read(f"reviews/{review_id}/approval.json")
        if proposal is None and approval is None:
            return None
        return {"proposal": proposal, "approval": approval}

    async def delete(self, review_id: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        for name in (f"reviews/{review_id}/proposal.json", f"reviews/{review_id}/approval.json"):
            try:
                await self.container.get_blob_client(name).delete_blob()
            except ResourceNotFoundError:
                pass


@asynccontextmanager
async def open_review_store():
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    account_url = os.environ.get("BLOB_STORAGE_URL")
    if not account_url:
        raise SystemExit("Configura BLOB_STORAGE_URL.")
    container = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            yield BlobReviewStore(service.get_container_client(container))


def setup_logging(log_path: Path | None) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers, force=True
    )
    # El log HTTP de cada petición al SDK de Azure ralentiza el proceso y llena el disco.
    for noisy in ("azure", "azure.core.pipeline.policies.http_logging_policy", "azure.identity", "msal"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def get_state(tables) -> dict:
    from azure.core.exceptions import ResourceNotFoundError

    try:
        return dict(await tables[db.TABLE_CONTROL].get_entity(partition_key="control", row_key=STATE_ROW))
    except ResourceNotFoundError:
        return {}


async def set_state(tables, **values) -> None:
    from azure.data.tables import UpdateMode

    await tables[db.TABLE_CONTROL].upsert_entity(
        entity={"PartitionKey": "control", "RowKey": STATE_ROW, **values}, mode=UpdateMode.MERGE
    )


def describe_plan(legacy_snapshots, rows, protected, missing) -> dict:
    return {
        "heredados": len(legacy_snapshots),
        "protegidos_por_modelo": len(protected),
        "casos_pendientes_a_borrar": sum(1 for s in legacy_snapshots.values() if s.get("Status") == "pending"),
        "casos_en_proceso_o_procesados": sum(1 for s in legacy_snapshots.values() if s.get("Status") != "pending"),
        "reviews_a_borrar": len({s["ReviewId"] for s in legacy_snapshots.values() if s.get("ReviewId")}),
        "filas_a_borrar": {name: len(items) for name, items in rows.items()},
        "estudiantes_a_sembrar": len(missing),
    }


def load_cohort(args, needed: int, exclude: set[str], *, strict: bool):
    data_dir = args.data_dir
    if args.generate and needed:
        students = math.ceil(needed / seeding.ACTIVE_FRACTION_SAFETY)
        data_dir = seeding.generate_dataset(
            students, ROOT / "data" / "synthetic_runs" / f"operational_{students}students"
        )
    try:
        frames = seeding.load_frames(data_dir)
    except FileNotFoundError:
        if strict:
            raise SystemExit(f"No se encontró el dataset en {data_dir}; usa --data-dir o --generate.")
        log.warning("Dataset no disponible en %s; no se puede confirmar la disponibilidad del reemplazo.", data_dir)
        return None, None
    try:
        return frames, seeding.select_cohort(frames, needed, exclude)
    except SystemExit as error:
        if strict:
            raise
        log.warning("%s", error)
        return frames, None


async def run(args) -> int:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = args.backup_root / f"legacy_replacement_{timestamp}"
    setup_logging(backup_dir / "run.log" if args.apply else None)
    log.info("Modo: %s  objetivo: %s estudiantes", "APPLY" if args.apply else "DRY-RUN", args.count)

    async with db._table_clients() as tables, open_review_store() as reviews:
        state = await get_state(tables)
        resuming = state.get("Phase") in {"backup_verified", "deleted"}
        legacy_snapshots, protected = await legacy.find_legacy(tables)
        missing = legacy.missing_numbers(
            {n for n in protected}, args.count
        )
        rows = await legacy.collect_rows(tables, set(legacy_snapshots))
        plan = describe_plan(legacy_snapshots, rows, protected, missing)
        log.info("Plan: %s", json.dumps(plan, ensure_ascii=False))
        if resuming:
            log.info("Reanudando (fase previa: %s, respaldo: %s)", state.get("Phase"), state.get("BackupDir"))

        if not args.apply:
            exclude = await legacy.used_training_ids(tables)
            _, cohort = load_cohort(args, len(missing), exclude, strict=False)
            log.info(
                "Reemplazo disponible en el dataset: %s",
                "sí" if cohort is not None or not missing else "NO (use --generate o un --data-dir mayor)",
            )
            log.info("Dry-run: no se modificó nada. Agrega --apply para ejecutar.")
            return 0

        if not legacy_snapshots and not missing and state.get("Phase", "done") == "done":
            log.info("No hay heredados ni números libres: nada que hacer.")
            return 0

        # 1. Scoring previo: si el endpoint falla, no se borra nada.
        entities = None
        if missing:
            exclude = await legacy.used_training_ids(tables)
            frames, cohort = load_cohort(args, len(missing), exclude, strict=True)
            try:
                probabilities, model, scored_at = seeding.score_cohort(cohort, args)
            except scoring.EndpointScoringError as error:
                log.error("Abortado antes de borrar: %s", error)
                return 2
            entities = seeding.build(frames, cohort, probabilities, model, scored_at, 1, numbers=missing)
            log.info("Reemplazo puntuado con %s v%s", model.name, model.version)

        # 2. Respaldo verificado (se omite al reanudar: ya quedó verificado).
        review_ids = {s["ReviewId"] for s in legacy_snapshots.values() if s.get("ReviewId")}
        if not resuming:
            counts = await legacy.backup_rows(rows, reviews, review_ids, backup_dir)
            log.info("Respaldo verificado en %s: %s", backup_dir, json.dumps(counts))
            await set_state(tables, Phase="backup_verified", BackupDir=str(backup_dir))

        # 3. Borrado por lotes.
        await set_state(tables, Phase="deleting")
        deleted = await legacy.delete_legacy(tables, rows, reviews, review_ids)
        log.info("Borrado completo: %s", json.dumps(deleted))
        await set_state(tables, Phase="deleted")

        # 4. Siembra del reemplazo (reanudable por create-if-missing).
        if entities is not None:
            await seed_replacement(tables, entities, missing)

        # 5. Control y regeneración operativa.
        from azure.data.tables import UpdateMode

        await tables[db.TABLE_CONTROL].upsert_entity(
            entity={
                "PartitionKey": "control", "RowKey": "poc",
                "SeedVersion": db.SEED_VERSION, "StudentCount": args.count,
                "OperationalStudentCount": 0,
            },
            mode=UpdateMode.MERGE,
        )
        await db._ensure_operational_data(tables)
        await set_state(tables, Phase="done", CompletedAt=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        log.info("Reemplazo completado: %s estudiantes sembrados, StudentCount=%s.", len(missing), args.count)
    return 0


async def seed_replacement(tables, entities: dict, numbers: list[int]) -> None:
    for offset in range(0, len(numbers), seeding.CHECKPOINT_STUDENTS):
        chunk = set(numbers[offset : offset + seeding.CHECKPOINT_STUDENTS])
        for name in seeding.SEED_ORDER:
            rows = [r for r in entities[name] if db._student_number(r["StudentId"]) in chunk]
            await seeding.write_rows(tables[name], rows)
        log.info("Sembrados %s/%s estudiantes de reemplazo", min(offset + len(chunk), len(numbers)), len(numbers))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Ejecuta de verdad (sin esto es dry-run)")
    parser.add_argument("--count", type=int, default=db.SYNTHETIC_STUDENT_COUNT)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "raw")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--backup-root", type=Path, default=ROOT / "outputs" / "backups")
    parser.add_argument("--model-name", default="")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--batch-size", type=int, default=scoring.DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout", type=float, default=scoring.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=scoring.DEFAULT_RETRIES)
    args = parser.parse_args()
    if not 1 <= args.count <= db.MAX_SYNTHETIC_STUDENT_COUNT:
        raise SystemExit(f"--count debe estar entre 1 y {db.MAX_SYNTHETIC_STUDENT_COUNT}")
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
