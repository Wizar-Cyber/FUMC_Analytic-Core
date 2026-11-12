"""Reemplazo de los estudiantes heredados (sin variables de entrenamiento) de las tablas operativas.

Un snapshot es heredado solo si FeaturesJson, ModelName y TrainingStudentId están vacíos:
cualquier fila puntuada por el modelo queda protegida. El orden de borrado deja los
snapshots para el final, de modo que una ejecución interrumpida pueda reanudarse
(el conjunto de heredados se recalcula desde los snapshots que quedan).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Protocol

from .synthetic_database import (
    PERIOD_ID,
    TABLE_ACADEMICS,
    TABLE_ALERTS,
    TABLE_FINANCE,
    TABLE_FOLLOWUPS,
    TABLE_SNAPSHOTS,
    TABLE_STUDENTS,
    TABLE_TARGETS,
    TABLE_TRENDS,
    TABLE_WELLBEING,
    _student_number,
)

log = logging.getLogger("legacy_replacement")

TRANSACTION_SIZE = 100
DELETE_CONCURRENCY = 50

# Orden de borrado: dependientes primero, snapshots al final (marcador para reanudar).
DELETE_ORDER = (
    TABLE_ALERTS,
    TABLE_FOLLOWUPS,
    TABLE_TRENDS,
    TABLE_ACADEMICS,
    TABLE_FINANCE,
    TABLE_WELLBEING,
    TABLE_TARGETS,
    TABLE_STUDENTS,
    TABLE_SNAPSHOTS,
)


class BackupMismatchError(RuntimeError):
    pass


class ReviewStore(Protocol):
    async def export(self, review_id: str) -> dict[str, Any] | None: ...

    async def delete(self, review_id: str) -> None: ...


async def _scan(table: Any, query_filter: str | None = None) -> AsyncIterator[dict[str, Any]]:
    result = (
        table.query_entities(query_filter=query_filter)
        if query_filter
        else table.list_entities()
    )
    if inspect.isawaitable(result):
        result = await result
    async for row in result:
        yield dict(row)


def is_legacy_snapshot(snapshot: dict[str, Any]) -> bool:
    """Heredado = sin variables de entrenamiento, sin modelo y sin id de entrenamiento."""
    features = snapshot.get("FeaturesJson")
    if features is not None and str(features).strip() not in {"", "{}", "null"}:
        return False
    if str(snapshot.get("ModelName") or "").strip():
        return False
    if str(snapshot.get("TrainingStudentId") or "").strip():
        return False
    return True


async def find_legacy(tables: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[int]]:
    """Devuelve los snapshots heredados por StudentId y los números ya ocupados por filas protegidas."""
    legacy: dict[str, dict[str, Any]] = {}
    protected_numbers: set[int] = set()
    async for snapshot in _scan(tables[TABLE_SNAPSHOTS], f"PartitionKey eq '{PERIOD_ID}'"):
        student_id = str(snapshot["StudentId"])
        if is_legacy_snapshot(snapshot):
            legacy[student_id] = snapshot
        else:
            protected_numbers.add(_student_number(student_id))
    return legacy, protected_numbers


async def collect_rows(
    tables: dict[str, Any], legacy_ids: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Filas completas a respaldar y borrar por tabla; solo pertenecientes a estudiantes heredados."""
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in DELETE_ORDER}
    scans = (
        (TABLE_STUDENTS, "PartitionKey eq 'students'", lambda r: str(r["RowKey"])),
        (TABLE_SNAPSHOTS, f"PartitionKey eq '{PERIOD_ID}'", lambda r: str(r["RowKey"])),
        (TABLE_TARGETS, f"PartitionKey eq '{PERIOD_ID}'", lambda r: str(r["RowKey"])),
        (TABLE_FINANCE, None, lambda r: str(r["PartitionKey"])),
        (TABLE_WELLBEING, None, lambda r: str(r["PartitionKey"])),
        (TABLE_ACADEMICS, None, lambda r: str(r["PartitionKey"])),
        (TABLE_ALERTS, "PartitionKey eq 'alerts'", lambda r: str(r.get("StudentId", ""))),
        (TABLE_FOLLOWUPS, "PartitionKey eq 'followups'", lambda r: str(r.get("StudentId", ""))),
    )
    for name, query_filter, student_of in scans:
        async for row in _scan(tables[name], query_filter):
            if student_of(row) in legacy_ids:
                rows[name].append(row)
    async for row in _scan(tables[TABLE_TRENDS], "PartitionKey eq 'dashboard'"):
        if row.get("DataSource") == "simulated-history":
            rows[TABLE_TRENDS].append(row)
    return rows


def missing_numbers(protected_numbers: Iterable[int], target: int) -> list[int]:
    occupied = set(protected_numbers)
    if occupied and max(occupied) > target:
        raise ValueError("Hay estudiantes protegidos con número mayor al objetivo; --count no puede reducir la cohorte.")
    return [number for number in range(1, target + 1) if number not in occupied]


async def used_training_ids(tables: dict[str, Any]) -> set[str]:
    used: set[str] = set()
    async for snapshot in _scan(tables[TABLE_SNAPSHOTS], f"PartitionKey eq '{PERIOD_ID}'"):
        training_id = str(snapshot.get("TrainingStudentId") or "")
        if training_id:
            used.add(training_id)
    return used


def _count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


async def backup_rows(
    rows: dict[str, list[dict[str, Any]]],
    reviews: ReviewStore | None,
    review_ids: Iterable[str],
    directory: Path,
) -> dict[str, int]:
    """Exporta a JSONL y verifica que lo escrito coincida con lo leído; si no, lanza BackupMismatchError."""
    directory.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, table_rows in rows.items():
        path = directory / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for row in table_rows:
                handle.write(json.dumps({"table": name, "entity": row}, ensure_ascii=False, default=str) + "\n")
        written = _count_lines(path)
        if written != len(table_rows):
            raise BackupMismatchError(
                f"Respaldo de {name}: se leyeron {len(table_rows)} filas y se exportaron {written}. No se borró nada."
            )
        counts[name] = written
    review_rows = []
    if reviews is not None:
        for review_id in sorted(set(review_ids)):
            exported = await reviews.export(review_id)
            if exported is not None:
                review_rows.append({"review_id": review_id, **exported})
    path = directory / "reviews.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in review_rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    if _count_lines(path) != len(review_rows):
        raise BackupMismatchError("Respaldo de reviews: el conteo exportado no coincide con el leído. No se borró nada.")
    counts["reviews"] = len(review_rows)
    return counts


async def _delete_one(table: Any, partition_key: str, row_key: str) -> None:
    from azure.core.exceptions import ResourceNotFoundError

    try:
        await table.delete_entity(partition_key=partition_key, row_key=row_key)
    except ResourceNotFoundError:
        pass


async def delete_rows(table: Any, rows: list[dict[str, Any]]) -> int:
    """Borra por lotes (transacción por partición con respaldo fila a fila); idempotente."""
    by_partition: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_partition.setdefault(str(row["PartitionKey"]), []).append(row)
    semaphore = asyncio.Semaphore(DELETE_CONCURRENCY)

    async def delete(row: dict[str, Any]) -> None:
        async with semaphore:
            await _delete_one(table, str(row["PartitionKey"]), str(row["RowKey"]))

    async def delete_partition(partition_rows: list[dict[str, Any]]) -> None:
        if len(partition_rows) > 1:
            for offset in range(0, len(partition_rows), TRANSACTION_SIZE):
                chunk = partition_rows[offset : offset + TRANSACTION_SIZE]
                try:
                    async with semaphore:
                        await table.submit_transaction(
                            [("delete", {"PartitionKey": r["PartitionKey"], "RowKey": r["RowKey"]}) for r in chunk]
                        )
                except Exception:
                    await asyncio.gather(*(delete(row) for row in chunk))
        else:
            await delete(partition_rows[0])

    # Todas las particiones en paralelo: con una partición por estudiante, hacerlo en serie
    # reduce el borrado a ~8 filas/s.
    await asyncio.gather(*(delete_partition(group) for group in by_partition.values()))
    return len(rows)


async def delete_legacy(
    tables: dict[str, Any],
    rows: dict[str, list[dict[str, Any]]],
    reviews: ReviewStore | None,
    review_ids: Iterable[str],
) -> dict[str, int]:
    deleted: dict[str, int] = {}
    if reviews is not None:
        for review_id in sorted(set(review_ids)):
            await reviews.delete(review_id)
        deleted["reviews"] = len(set(review_ids))
    for name in DELETE_ORDER:
        deleted[name] = await delete_rows(tables[name], rows[name])
        log.info("Borradas %s filas de %s", deleted[name], name)
    return deleted
