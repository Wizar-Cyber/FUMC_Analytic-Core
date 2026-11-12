"""Estado de lotes de análisis sin Durable Functions.

El flujo usa Service Bus (workers de cada agente) y dos tablas de Azure Tables:

* ``SyntheticBatches``: ``PartitionKey = batch_id``. La fila ``meta`` guarda el estado del lote y
  una fila por caso (``RowKey = review_id``) guarda su estado y el caso a analizar.
* ``SyntheticAgentResults``: ``PartitionKey = review_id``. Una fila por agente con su resultado y
  una fila ``final`` que actúa como cerrojo para finalizar el caso una sola vez.

Todas las operaciones son idempotentes porque Service Bus entrega al menos una vez.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from . import synthetic_database as db

logger = logging.getLogger(__name__)

TABLE_BATCHES = "SyntheticBatches"
TABLE_RESULTS = "SyntheticAgentResults"
AGENTS = ("socioeconomic", "academic", "wellbeing")
META_ROW = "meta"
FINAL_ROW = "final"
_ID_PATTERN = r"[A-Za-z0-9_-]{1,120}"
_tables_ready = False


def batch_timeout() -> timedelta:
    try:
        minutes = int(os.environ.get("BATCH_TIMEOUT_MINUTES", "20"))
    except ValueError:
        minutes = 20
    return timedelta(minutes=max(1, minutes))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    import re

    if not isinstance(value, str) or not re.fullmatch(_ID_PATTERN, value):
        raise ValueError("Identificador de lote o caso no válido.")
    return value


@asynccontextmanager
async def _tables() -> AsyncIterator[tuple[Any, Any]]:
    from azure.data.tables.aio import TableServiceClient
    from azure.identity.aio import DefaultAzureCredential

    global _tables_ready
    async with DefaultAzureCredential() as credential:
        async with TableServiceClient(endpoint=db._table_endpoint(), credential=credential) as service:
            if not _tables_ready:
                for name in (TABLE_BATCHES, TABLE_RESULTS):
                    await service.create_table_if_not_exists(name)
                _tables_ready = True
            yield service.get_table_client(TABLE_BATCHES), service.get_table_client(TABLE_RESULTS)


async def register_batch(batch_id: str, items: list[dict[str, Any]]) -> None:
    """Crea el lote y una fila por caso, todos en estado ``running``."""
    _safe_id(batch_id)
    probabilities = [float(item["case"]["model_probability"]) for item in items]
    now = _now()
    async with _tables() as (batches, _):
        await batches.upsert_entity(
            {
                "PartitionKey": batch_id,
                "RowKey": META_ROW,
                "Status": "running",
                "Total": len(items),
                "MaxProbability": max(probabilities),
                "MinProbability": min(probabilities),
                "CreatedAt": now,
                "UpdatedAt": now,
            }
        )
        semaphore = asyncio.Semaphore(20)

        async def add(item: dict[str, Any]) -> None:
            async with semaphore:
                await batches.upsert_entity(
                    {
                        "PartitionKey": batch_id,
                        "RowKey": _safe_id(item["review_id"]),
                        "CaseId": item["case_id"],
                        "Status": "running",
                        "CaseJson": json.dumps(item["case"], ensure_ascii=False),
                        "UpdatedAt": now,
                    }
                )

        await asyncio.gather(*(add(item) for item in items))


async def get_item(batch_id: str, review_id: str) -> dict[str, Any] | None:
    from azure.core.exceptions import ResourceNotFoundError

    async with _tables() as (batches, _):
        try:
            return dict(await batches.get_entity(partition_key=_safe_id(batch_id), row_key=_safe_id(review_id)))
        except ResourceNotFoundError:
            return None


async def get_batch(batch_id: str) -> dict[str, Any] | None:
    """Resumen del lote con el mismo formato que consume la interfaz."""
    _safe_id(batch_id)
    async with _tables() as (batches, _):
        rows = [dict(row) async for row in batches.query_entities(f"PartitionKey eq '{batch_id}'")]
    meta = next((row for row in rows if row["RowKey"] == META_ROW), None)
    if meta is None:
        return None
    items = [row for row in rows if row["RowKey"] != META_ROW]
    processed = sum(row.get("Status") == "processed" for row in items)
    failed = sum(row.get("Status") == "failed" for row in items)
    running = str(meta.get("Status")) == "running"
    return {
        "batch_id": batch_id,
        "running": running,
        "status": str(meta.get("Status")),
        "total": int(meta.get("Total", len(items))),
        "done": processed + failed,
        "processed": processed,
        "failed": failed,
        "max_probability": meta.get("MaxProbability"),
        "min_probability": meta.get("MinProbability"),
        "results": [
            {"case_id": row.get("CaseId"), "review_id": row["RowKey"], "status": row.get("Status")}
            for row in items
        ],
    }


async def mark_item(batch_id: str, review_id: str, status: str) -> None:
    from azure.data.tables import UpdateMode

    async with _tables() as (batches, _):
        await batches.update_entity(
            {"PartitionKey": _safe_id(batch_id), "RowKey": _safe_id(review_id), "Status": status, "UpdatedAt": _now()},
            mode=UpdateMode.MERGE,
        )


async def complete_batch_if_done(batch_id: str) -> bool:
    """Cierra el lote cuando no quedan casos en curso. Devuelve True solo a quien lo cierra."""
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceModifiedError
    from azure.data.tables import UpdateMode

    _safe_id(batch_id)
    async with _tables() as (batches, _):
        rows = [dict(row) async for row in batches.query_entities(f"PartitionKey eq '{batch_id}'")]
        items = [row for row in rows if row["RowKey"] != META_ROW]
        if any(row.get("Status") == "running" for row in items):
            return False
        meta = await batches.get_entity(partition_key=batch_id, row_key=META_ROW)
        if meta.get("Status") != "running":
            return False
        failed = any(row.get("Status") == "failed" for row in items)
        meta["Status"] = "completed_with_errors" if failed else "completed"
        meta["UpdatedAt"] = _now()
        try:
            await batches.update_entity(
                meta,
                mode=UpdateMode.MERGE,
                etag=meta.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except ResourceModifiedError:
            return False
        return True


async def store_agent_result(review_id: str, agent: str, result: dict[str, Any]) -> None:
    from azure.data.tables import UpdateMode

    if agent not in AGENTS:
        raise ValueError("Agente desconocido.")
    async with _tables() as (_, results):
        await results.upsert_entity(
            {
                "PartitionKey": _safe_id(review_id),
                "RowKey": agent,
                "ResultJson": json.dumps(result, ensure_ascii=False),
                "UpdatedAt": _now(),
            },
            mode=UpdateMode.REPLACE,
        )


async def load_agent_results(review_id: str) -> dict[str, dict[str, Any]]:
    _safe_id(review_id)
    async with _tables() as (_, results):
        rows = [dict(row) async for row in results.query_entities(f"PartitionKey eq '{review_id}'")]
    return {row["RowKey"]: json.loads(row["ResultJson"]) for row in rows if row["RowKey"] in AGENTS}


async def claim_finalization(review_id: str) -> bool:
    """Cerrojo: solo una entrega concurrente finaliza el caso."""
    from azure.core.exceptions import ResourceExistsError

    async with _tables() as (_, results):
        try:
            await results.create_entity({"PartitionKey": _safe_id(review_id), "RowKey": FINAL_ROW, "ClaimedAt": _now()})
        except ResourceExistsError:
            return False
        return True


async def stale_running_batches() -> list[str]:
    cutoff = (datetime.now(timezone.utc) - batch_timeout()).isoformat()
    async with _tables() as (batches, _):
        rows = [
            dict(row)
            async for row in batches.query_entities(f"RowKey eq '{META_ROW}' and Status eq 'running'")
        ]
    return [row["PartitionKey"] for row in rows if str(row.get("CreatedAt", "")) < cutoff]


async def fail_unfinished(batch_id: str) -> bool:
    """Marca como fallidos los casos sin resultado, los devuelve a ``pending`` y cierra el lote."""
    _safe_id(batch_id)
    async with _tables() as (batches, _):
        rows = [dict(row) async for row in batches.query_entities(f"PartitionKey eq '{batch_id}'")]
    for row in rows:
        if row["RowKey"] == META_ROW or row.get("Status") != "running":
            continue
        try:
            await db.update_synthetic_case_status(str(row.get("CaseId")), "pending")
        except Exception:
            logger.exception("No se pudo devolver el caso %s a pendiente.", row.get("CaseId"))
        await mark_item(batch_id, row["RowKey"], "failed")
    return await complete_batch_if_done(batch_id)


def _case_partition(case_id: str) -> str:
    return "case-" + _safe_id(case_id)


async def store_case_agent_result(case_id: str, agent: str, result: dict[str, Any]) -> None:
    """Guarda el resultado del agente por caso para no volver a pagarlo si la síntesis falla."""
    from azure.data.tables import UpdateMode

    if agent not in AGENTS:
        raise ValueError("Agente desconocido.")
    async with _tables() as (_, results):
        await results.upsert_entity(
            {
                "PartitionKey": _case_partition(case_id),
                "RowKey": agent,
                "ResultJson": json.dumps(result, ensure_ascii=False),
                "UpdatedAt": _now(),
            },
            mode=UpdateMode.REPLACE,
        )


async def load_case_agent_results(case_id: str) -> dict[str, dict[str, Any]]:
    partition = _case_partition(case_id)
    async with _tables() as (_, results):
        rows = [dict(row) async for row in results.query_entities(f"PartitionKey eq '{partition}'")]
    return {row["RowKey"]: json.loads(row["ResultJson"]) for row in rows if row["RowKey"] in AGENTS}
