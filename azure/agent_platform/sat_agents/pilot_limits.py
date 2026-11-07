from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any


MAX_EVALUATIONS_PER_PILOT = 10_000
MAX_CONCURRENT_CASES = 1
_COUNTER_BLOB = "pilot/evaluation-counter.json"
_MAX_ETAG_RETRIES = 20


class PilotLimitReached(RuntimeError):
    pass


class PilotConcurrencyLimitReached(RuntimeError):
    pass


def reserve_from_state(
    state: dict[str, Any], instance_id: str, evaluation_count: int = 1
) -> dict[str, Any]:
    accepted = state.get("accepted_count", 0)
    active = state.get("active_instance_ids", [])
    if (
        isinstance(accepted, bool)
        or not isinstance(accepted, int)
        or accepted < 0
        or not isinstance(active, list)
        or any(not isinstance(item, str) for item in active)
    ):
        raise RuntimeError("El contador de evaluaciones del piloto no es válido.")
    if (
        isinstance(evaluation_count, bool)
        or not isinstance(evaluation_count, int)
        or evaluation_count < 1
    ):
        raise ValueError("evaluation_count debe ser un entero positivo.")
    if instance_id in active:
        return state
    if accepted + evaluation_count > MAX_EVALUATIONS_PER_PILOT:
        raise PilotLimitReached(
            "Se alcanzó el límite de 10.000 evaluaciones de este piloto."
        )
    if len(active) >= MAX_CONCURRENT_CASES:
        raise PilotConcurrencyLimitReached(
            "Ya hay una evaluación o lote activo; espere a que termine antes de iniciar otro."
        )
    return {
        "accepted_count": accepted + evaluation_count,
        "active_instance_ids": [*active, instance_id],
    }


def release_from_state(
    state: dict[str, Any], instance_id: str
) -> dict[str, Any]:
    active = state.get("active_instance_ids", [])
    if not isinstance(active, list):
        raise RuntimeError("El contador de evaluaciones del piloto no es válido.")
    return {
        **state,
        "active_instance_ids": [item for item in active if item != instance_id],
    }


def _counter_blob_url() -> tuple[str, str]:
    account_url = os.environ.get("BLOB_STORAGE_URL")
    container_name = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    if not account_url:
        raise RuntimeError("Configure BLOB_STORAGE_URL para aplicar el límite del piloto.")
    return account_url, container_name


async def _update_counter(
    update: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    from azure.core import MatchConditions
    from azure.core.exceptions import (
        ResourceExistsError,
        ResourceModifiedError,
        ResourceNotFoundError,
    )
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob import ContentSettings
    from azure.storage.blob.aio import BlobServiceClient

    account_url, container_name = _counter_blob_url()
    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            blob = service.get_blob_client(
                container=container_name,
                blob=_COUNTER_BLOB,
            )
            for _ in range(_MAX_ETAG_RETRIES):
                try:
                    downloader = await blob.download_blob()
                    state = json.loads(await downloader.readall())
                    etag = downloader.properties.etag
                    if not isinstance(state, dict) or not isinstance(etag, str):
                        raise RuntimeError("El contador del piloto no es válido.")
                except ResourceNotFoundError:
                    state = {"accepted_count": 0, "active_instance_ids": []}
                    updated = update(state)
                    try:
                        await blob.upload_blob(
                            json.dumps(updated),
                            overwrite=False,
                            content_settings=ContentSettings(
                                content_type="application/json"
                            ),
                        )
                        return updated
                    except ResourceExistsError:
                        continue

                updated = update(state)
                try:
                    await blob.upload_blob(
                        json.dumps(updated),
                        overwrite=True,
                        etag=etag,
                        match_condition=MatchConditions.IfNotModified,
                        content_settings=ContentSettings(
                            content_type="application/json"
                        ),
                    )
                    return updated
                except (ResourceModifiedError, ResourceNotFoundError):
                    continue
    raise RuntimeError("No se pudo actualizar de forma segura el contador del piloto.")


async def reserve_evaluation_slot(
    instance_id: str, evaluation_count: int = 1
) -> dict[str, Any]:
    try:
        return await _update_counter(
            lambda state: reserve_from_state(state, instance_id, evaluation_count)
        )
    except (PilotLimitReached, PilotConcurrencyLimitReached, RuntimeError):
        raise
    except Exception as error:
        raise RuntimeError("No se pudo validar el contador del piloto.") from error


async def release_evaluation_slot(instance_id: str) -> None:
    try:
        await _update_counter(lambda state: release_from_state(state, instance_id))
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("No se pudo liberar el cupo del piloto.") from error


async def get_pilot_counter() -> dict[str, Any]:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    account_url, container_name = _counter_blob_url()
    try:
        async with DefaultAzureCredential() as credential:
            async with BlobServiceClient(account_url, credential=credential) as service:
                blob = service.get_blob_client(
                    container=container_name,
                    blob=_COUNTER_BLOB,
                )
                try:
                    downloader = await blob.download_blob()
                except ResourceNotFoundError:
                    return {"accepted_count": 0, "active_instance_ids": []}
                state = json.loads(await downloader.readall())
                if not isinstance(state, dict):
                    raise RuntimeError("El contador del piloto no es válido.")
                return state
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("No se pudo consultar el contador del piloto.") from error
