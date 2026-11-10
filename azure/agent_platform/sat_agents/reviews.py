from __future__ import annotations

import json
import os
import re
from typing import Any


def _review_blob_name(review_id: str) -> str:
    return f"reviews/{review_id}/proposal.json"


def _public_review(proposal: dict[str, Any]) -> dict[str, Any]:
    academic = proposal.get("academic_analysis", {})
    sources = academic.get("sources", []) if isinstance(academic, dict) else []
    return {
        "review_id": proposal.get("review_id"),
        "student_id": proposal.get("student_id"),
        "status": proposal.get("status"),
        "created_at": proposal.get("created_at"),
        "model_probability": proposal.get("model_probability"),
        "recommendation": proposal.get("recommendation"),
        "socioeconomic_analysis": proposal.get("socioeconomic_analysis"),
        "academic_analysis": {
            "analysis": academic.get("analysis", {}),
            "sources": [
                {
                    key: source[key]
                    for key in ("id", "title", "source_uri", "section")
                    if key in source
                }
                for source in sources
                if isinstance(source, dict)
            ],
        },
        "wellbeing_analysis": proposal.get("wellbeing_analysis", {}),
        "token_usage": proposal.get("token_usage"),
        "cost_estimate": proposal.get("cost_estimate"),
    }


def _review_report_row(
    proposal: dict[str, Any], decision_record: dict[str, Any] | None
) -> dict[str, Any]:
    review = _public_review(proposal)
    recommendation = review.get("recommendation") or {}
    socioeconomic = review.get("socioeconomic_analysis") or {}
    academic = review.get("academic_analysis") or {}
    academic_analysis = academic.get("analysis") or {}
    wellbeing = review.get("wellbeing_analysis") or {}
    token_usage = review.get("token_usage") or {}
    total_usage = token_usage.get("total") or {}
    cost_estimate = review.get("cost_estimate") or {}
    approval = (
        decision_record.get("approval", {})
        if isinstance(decision_record, dict)
        else {}
    )

    def text_list(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        return "\n".join(item for item in value if isinstance(item, str))

    def token_count(name: str) -> int | None:
        value = total_usage.get(name)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return {
        "id_revision": review.get("review_id"),
        "fecha_generacion": review.get("created_at"),
        "estado_revision": approval.get("decision") or review.get("status"),
        "probabilidad_modelo": review.get("model_probability"),
        "requiere_revision_humana": bool(
            recommendation.get("human_review_required", True)
        ),
        "sintesis_llm": recommendation.get("summary", ""),
        "acciones_propuestas": text_list(recommendation.get("proposed_actions")),
        "limitaciones_sintesis": text_list(recommendation.get("limitations")),
        "resumen_socioeconomico": socioeconomic.get("summary", ""),
        "observaciones_socioeconomicas": text_list(
            socioeconomic.get("observations")
        ),
        "limitaciones_socioeconomicas": text_list(
            socioeconomic.get("limitations")
        ),
        "resumen_academico": academic_analysis.get("summary", ""),
        "observaciones_academicas": text_list(
            academic_analysis.get("observations")
        ),
        "resumen_bienestar": wellbeing.get("summary", ""),
        "observaciones_bienestar": text_list(wellbeing.get("observations")),
        "limitaciones_bienestar": text_list(wellbeing.get("limitations")),
        "limitaciones_academicas": text_list(
            academic_analysis.get("limitations")
        ),
        "citas_reglamentarias": text_list(
            academic_analysis.get("citation_ids")
        ),
        "decision_humana": approval.get("decision"),
        "accion_aprobada": approval.get("approved_action"),
        "tokens_entrada": token_count("input_tokens"),
        "tokens_salida": token_count("output_tokens"),
        "tokens_totales": token_count("total_tokens"),
        "costo_estimado_usd": cost_estimate.get("amount_usd"),
    }


async def save_pending_review(review_id: str, proposal: dict[str, Any]) -> None:
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob import ContentSettings
    from azure.storage.blob.aio import BlobServiceClient

    account_url = os.environ.get("BLOB_STORAGE_URL")
    container_name = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    if not account_url:
        raise RuntimeError("Configure BLOB_STORAGE_URL.")

    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            blob = service.get_blob_client(
                container=container_name,
                blob=_review_blob_name(review_id),
            )
            await blob.upload_blob(
                json.dumps(proposal, ensure_ascii=False),
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )


async def record_approval(
    review_id: str, reviewer_id: str, approval: dict[str, Any]
) -> None:
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob import ContentSettings
    from azure.storage.blob.aio import BlobServiceClient

    account_url = os.environ.get("BLOB_STORAGE_URL")
    container_name = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    if not account_url:
        raise RuntimeError("Configure BLOB_STORAGE_URL.")

    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            container = service.get_container_client(container_name)
            proposal_blob = container.get_blob_client(_review_blob_name(review_id))
            try:
                proposal_data = await proposal_blob.download_blob()
                proposal = json.loads(await proposal_data.readall())
            except ResourceNotFoundError as error:
                raise LookupError("No existe una propuesta para revisión.") from error
            if proposal.get("status") != "pending_approval":
                raise ValueError("La propuesta no está pendiente de aprobación.")

            decision = {
                "review_id": review_id,
                "reviewer_id": reviewer_id,
                "approval": approval,
            }
            approval_blob = container.get_blob_client(
                f"reviews/{review_id}/approval.json"
            )
            try:
                await approval_blob.upload_blob(
                    json.dumps(decision, ensure_ascii=False),
                    overwrite=False,
                    content_settings=ContentSettings(content_type="application/json"),
                )
            except ResourceExistsError as error:
                raise FileExistsError(
                    "Esta propuesta ya tiene una decisión registrada."
                ) from error


async def get_review(review_id: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    account_url = os.environ.get("BLOB_STORAGE_URL")
    container_name = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    if not account_url:
        raise RuntimeError("Configure BLOB_STORAGE_URL.")

    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            container = service.get_container_client(container_name)
            proposal_blob = container.get_blob_client(_review_blob_name(review_id))
            try:
                proposal_data = await proposal_blob.download_blob()
                proposal = json.loads(await proposal_data.readall())
            except ResourceNotFoundError as error:
                raise LookupError("No existe una propuesta para revisión.") from error

            decision_blob = container.get_blob_client(
                f"reviews/{review_id}/approval.json"
            )
            try:
                decision_data = await decision_blob.download_blob()
                decision = json.loads(await decision_data.readall())
            except ResourceNotFoundError:
                decision = None
            return proposal, decision


async def list_reviews(limit: int = 50) -> dict[str, Any]:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    account_url = os.environ.get("BLOB_STORAGE_URL")
    container_name = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    if not account_url:
        raise RuntimeError("Configure BLOB_STORAGE_URL.")

    review_id_pattern = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
    totals = {
        "pending": 0,
        "generated": 0,
        "approved": 0,
        "edited": 0,
        "rejected": 0,
    }
    pending = []
    generated = []
    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            container = service.get_container_client(container_name)
            async for blob_item in container.list_blobs(name_starts_with="reviews/"):
                name = blob_item.name
                if not name.startswith("reviews/") or not name.endswith(
                    "/proposal.json"
                ):
                    continue
                review_id = name[len("reviews/") : -len("/proposal.json")]
                if not review_id_pattern.fullmatch(review_id):
                    continue
                proposal_blob = container.get_blob_client(name)
                proposal_data = await proposal_blob.download_blob()
                proposal = json.loads(await proposal_data.readall())
                decision_blob = container.get_blob_client(
                    f"reviews/{review_id}/approval.json"
                )
                try:
                    decision_data = await decision_blob.download_blob()
                    decision_record = json.loads(await decision_data.readall())
                    decision = decision_record.get("approval", {}).get("decision")
                except ResourceNotFoundError:
                    decision = None
                if decision is None:
                    if proposal.get("status") == "pending_approval":
                        totals["pending"] += 1
                        pending.append(_public_review(proposal))
                    elif proposal.get("status") == "generated":
                        totals["generated"] += 1
                        generated.append(_public_review(proposal))
                elif decision in {"approved", "edited", "rejected"}:
                    totals[decision] += 1

    pending.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    generated.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return {
        "aggregate": totals,
        "pending_reviews": pending[:limit],
        "pending_truncated": len(pending) > limit,
        "generated_reviews": generated[:limit],
        "generated_truncated": len(generated) > limit,
    }


async def list_review_report_rows() -> list[dict[str, Any]]:
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity.aio import DefaultAzureCredential
    from azure.storage.blob.aio import BlobServiceClient

    account_url = os.environ.get("BLOB_STORAGE_URL")
    container_name = os.environ.get("REVIEWS_CONTAINER", "student-case-reviews")
    if not account_url:
        raise RuntimeError("Configure BLOB_STORAGE_URL.")

    review_id_pattern = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
    rows = []
    async with DefaultAzureCredential() as credential:
        async with BlobServiceClient(account_url, credential=credential) as service:
            container = service.get_container_client(container_name)
            async for blob_item in container.list_blobs(name_starts_with="reviews/"):
                name = blob_item.name
                if not name.startswith("reviews/") or not name.endswith(
                    "/proposal.json"
                ):
                    continue
                review_id = name[len("reviews/") : -len("/proposal.json")]
                if not review_id_pattern.fullmatch(review_id):
                    continue

                proposal_data = await container.get_blob_client(name).download_blob()
                proposal = json.loads(await proposal_data.readall())
                decision_record = None
                try:
                    decision_data = await container.get_blob_client(
                        f"reviews/{review_id}/approval.json"
                    ).download_blob()
                    decision_record = json.loads(await decision_data.readall())
                except ResourceNotFoundError:
                    pass
                rows.append(_review_report_row(proposal, decision_record))

    rows.sort(key=lambda row: row.get("fecha_generacion") or "", reverse=True)
    return rows
