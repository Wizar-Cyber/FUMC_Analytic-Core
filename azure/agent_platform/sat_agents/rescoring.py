"""Re-puntúa los snapshots operativos con la versión vigente del modelo.

Solo se actualizan ModelProbability, RiskLevel, ModelName, ModelVersion y ScoredAt
(MERGE): Status, BatchId, ReviewId, alertas y seguimientos no se modifican.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Sequence

from .policy import classify_risk
from .synthetic_database import PERIOD_ID, _query_entities

ScoreBatch = Callable[[Sequence[dict[str, Any]]], Sequence[float]]


async def rescore_snapshots(
    snapshots_table: Any,
    score_batch: ScoreBatch,
    *,
    model_name: str,
    model_version: str,
    scored_at: str,
    batch_size: int = 500,
    dry_run: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    from azure.data.tables import UpdateMode

    stats: dict[str, Any] = {
        "scored": 0,
        "skipped_without_features": 0,
        "risk_changed": 0,
        "probability_sum": 0.0,
    }
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def flush() -> None:
        if not pending:
            return
        probabilities = score_batch([features for _, features in pending])
        if len(probabilities) != len(pending):
            raise RuntimeError("El scorer devolvió un número de probabilidades distinto al enviado.")
        updates = []
        for (snapshot, _), probability in zip(pending, probabilities):
            probability = round(float(probability), 4)
            risk = classify_risk(probability)
            stats["scored"] += 1
            stats["probability_sum"] += probability
            stats["risk_changed"] += int(risk != snapshot.get("RiskLevel"))
            updates.append(
                {
                    "PartitionKey": PERIOD_ID,
                    "RowKey": str(snapshot["RowKey"]),
                    "ModelProbability": probability,
                    "RiskLevel": risk,
                    "ModelName": model_name,
                    "ModelVersion": str(model_version),
                    "ScoredAt": scored_at,
                }
            )
        if not dry_run:
            for offset in range(0, len(updates), 25):
                await asyncio.gather(
                    *(
                        snapshots_table.upsert_entity(entity=entity, mode=UpdateMode.MERGE)
                        for entity in updates[offset : offset + 25]
                    )
                )
        pending.clear()

    async for snapshot in _query_entities(
        snapshots_table, query_filter=f"PartitionKey eq '{PERIOD_ID}'"
    ):
        if limit is not None and stats["scored"] + len(pending) >= limit:
            break
        try:
            features = json.loads(snapshot.get("FeaturesJson") or "")
        except ValueError:
            features = None
        if not isinstance(features, dict) or not features:
            stats["skipped_without_features"] += 1
            continue
        pending.append((dict(snapshot), features))
        if len(pending) >= batch_size:
            await flush()
    await flush()
    stats["mean_probability"] = (
        stats["probability_sum"] / stats["scored"] if stats["scored"] else 0.0
    )
    return stats
