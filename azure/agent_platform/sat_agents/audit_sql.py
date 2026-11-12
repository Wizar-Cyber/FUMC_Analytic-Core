"""Registro de auditoría en Azure SQL (SQL_PERSISTENCE_ENABLED=true).

Table Storage sigue siendo la fuente de la UI; SQL guarda predicción, propuesta,
decisión humana e intervención. Ningún error de SQL se propaga al llamador.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

from .policy import classify_risk

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("5a7f1b1e-6f0e-4b0e-9a55-5a7f5a7f5a7f")
_DATA_MODE = "synthetic"


def is_enabled() -> bool:
    return os.environ.get("SQL_PERSISTENCE_ENABLED", "").strip().lower() == "true"


def stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "|".join(parts)))


def as_object_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return stable_uuid("principal", value)


def _connect():
    from src.persistence.sql_repository import AzureSqlRepository, connect_entra

    server = os.environ.get("SQL_SERVER")
    database = os.environ.get("SQL_DATABASE")
    if not server or not database:
        raise RuntimeError("Configure SQL_SERVER y SQL_DATABASE.")
    return AzureSqlRepository(connect_entra(server, database))


def _model_identity() -> tuple[str, str]:
    return (
        os.environ.get("SQL_MODEL_NAME", "SAT_FUMC_LightGBM_Model"),
        os.environ.get("SQL_MODEL_VERSION", "2"),
    )


_AGENT_OUTPUTS = (
    ("socioeconomic", "socioeconomic_analysis"),
    ("academic", "academic_analysis"),
    ("wellbeing", "wellbeing_analysis"),
    ("synthesis", "recommendation"),
)


def _record_agent_outputs(repo: Any, proposal: dict[str, Any], prediction_id: str, review_id: str) -> None:
    """Una fila de AgentExecution por agente: su salida, tokens y modelo usado.

    Idempotente por revisión: si la propuesta se reintenta, no se duplica. Si el mismo caso
    se analiza de nuevo en otra revisión, queda como un intento nuevo del mismo agente.
    """
    calls = (proposal.get("token_usage") or {}).get("calls") or {}
    deployment = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "sin-despliegue")[:100]
    prompt_version = os.environ.get("AGENT_PROMPT_VERSION", "agents-v3")[:80]
    created_at = str(proposal.get("created_at") or "") or None
    for agent, field in _AGENT_OUTPUTS:
        output = proposal.get(field)
        if not isinstance(output, dict):
            continue
        execution_id = stable_uuid("agent-execution", review_id, agent)
        if repo._fetch("SELECT 1 AS found FROM dbo.AgentExecution WHERE AgentExecutionId = ?", (execution_id,)):
            continue
        attempt = repo._fetch(
            "SELECT ISNULL(MAX(AttemptNumber), 0) + 1 AS next FROM dbo.AgentExecution WHERE PredictionId = ? AND AgentName = ?",
            (prediction_id, agent),
        )[0]["next"]
        usage = calls.get(agent) or {}
        repo.record_agent_execution(
            agent_execution_id=execution_id,
            prediction_id=prediction_id,
            agent_name=agent,
            attempt_number=int(attempt),
            status="succeeded",
            prompt_version=prompt_version,
            deployment_name=deployment,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            output_json=output,
            started_at=created_at,
            finished_at=created_at,
        )


def _write_pending_review(proposal: dict[str, Any]) -> None:
    from .synthetic_database import PERIOD_ID, SNAPSHOT_CUT

    probability = float(proposal["model_probability"])
    review_id = str(proposal["review_id"])
    student_id = str(proposal.get("student_id") or review_id)
    model_name, model_version = _model_identity()
    snapshot_id = stable_uuid("snapshot", student_id, PERIOD_ID, SNAPSHOT_CUT)
    prediction_id = stable_uuid("prediction", snapshot_id, model_name, model_version)
    recommendation = proposal.get("recommendation") or {}
    risk_level = classify_risk(probability)

    repo = _connect()
    try:
        with repo.transaction():
            repo.ensure_model_release(model_name=model_name, model_version=model_version)
            repo.ensure_student_snapshot(
                snapshot_id=snapshot_id,
                data_mode=_DATA_MODE,
                student_id=student_id,
                academic_period=str(PERIOD_ID)[:6],
                prediction_cut=SNAPSHOT_CUT,
                feature_schema_version="digital-twin-v2",
                source_dataset_version="synthetic-poc",
            )
            repo.ensure_prediction(
                prediction_id=prediction_id,
                snapshot_id=snapshot_id,
                model_name=model_name,
                model_version=model_version,
                probability=probability,
                risk_level=risk_level,
                alert_raised=risk_level == "Alto",
                inference_source=os.environ.get("SQL_INFERENCE_SOURCE", "synthetic_fixture"),
            )
            _record_agent_outputs(repo, proposal, prediction_id, review_id)
            repo.ensure_review_proposal(
                review_id=review_id,
                prediction_id=prediction_id,
                status="pending_approval",
                summary=str(recommendation.get("summary") or "")[:2000],
                recommendations={"proposed_actions": recommendation.get("proposed_actions") or []},
                limitations={"limitations": recommendation.get("limitations") or []},
            )
            repo.record_audit_event(
                actor_object_id=None,
                action_code="review.proposed",
                entity_type="review",
                entity_id=review_id,
                data_mode=_DATA_MODE,
                metadata={"prediction_id": prediction_id, "risk_level": risk_level},
            )
    finally:
        repo.connection.close()


def _write_decision(
    review_id: str,
    reviewer_id: str | None,
    approval: dict[str, Any],
    followup: dict[str, Any] | None,
) -> None:
    decision_id = stable_uuid("decision", review_id)
    reviewer_object_id = as_object_id(reviewer_id) or stable_uuid("principal", "unknown")
    repo = _connect()
    try:
        with repo.transaction():
            if repo.get_review_proposal(review_id) is None:
                raise LookupError(f"La propuesta {review_id} no está en SQL.")
            if repo.get_human_decision(review_id) is None:
                repo.record_human_decision(
                    human_decision_id=decision_id,
                    review_id=review_id,
                    reviewer_object_id=reviewer_object_id,
                    decision=approval["decision"],
                    approved_action=(approval.get("approved_action") or None),
                    decision_note=(approval.get("note") or None),
                )
                repo.update_review_status(review_id, approval["decision"])
            if followup and approval["decision"] in {"approved", "edited"}:
                intervention_id = stable_uuid("intervention", decision_id)
                existing = [
                    row
                    for row in repo.list_interventions(limit=1000)
                    if str(row["InterventionId"]).lower() == intervention_id
                ]
                if not existing:
                    repo.record_intervention(
                        intervention_id=intervention_id,
                        human_decision_id=decision_id,
                        action_code=str(followup.get("action") or approval.get("approved_action") or "review")[:40],
                        status="open",
                        owner_object_id=None,
                    )
            repo.record_audit_event(
                actor_object_id=reviewer_object_id,
                action_code=f"review.{approval['decision']}",
                entity_type="review",
                entity_id=review_id,
                data_mode=_DATA_MODE,
                metadata={"has_followup": bool(followup)},
            )
    finally:
        repo.connection.close()


def _write_followup_event(followup: dict[str, Any], actor_id: str | None) -> None:
    repo = _connect()
    try:
        with repo.transaction():
            repo.record_audit_event(
                actor_object_id=as_object_id(actor_id),
                action_code="followup.created",
                entity_type="followup",
                entity_id=str(followup.get("followup_id") or followup.get("FollowupId") or "unknown"),
                data_mode=_DATA_MODE,
                metadata={
                    "student_id": followup.get("student_id"),
                    "action": followup.get("action"),
                    "review_id": followup.get("review_id") or None,
                },
            )
    finally:
        repo.connection.close()


async def _run(label: str, func, *args: Any) -> bool:
    if not is_enabled():
        return False
    for attempt in range(2):
        try:
            await asyncio.to_thread(func, *args)
            return True
        except Exception as error:
            # Un choque de claves entre transacciones simultáneas se resuelve al reintentar:
            # la segunda pasada encuentra las filas ya creadas y no las duplica.
            if attempt == 0 and "IntegrityError" in type(error).__name__:
                await asyncio.sleep(0.5)
                continue
            logger.exception("Falló la persistencia SQL (%s); la UI no se ve afectada.", label)
            return False
    return False


async def persist_pending_review(proposal: dict[str, Any]) -> bool:
    return await _run("pending_review", _write_pending_review, proposal)


async def persist_decision(
    review_id: str,
    reviewer_id: str | None,
    approval: dict[str, Any],
    followup: dict[str, Any] | None,
) -> bool:
    return await _run("decision", _write_decision, review_id, reviewer_id, approval, followup)


async def persist_followup_event(followup: dict[str, Any], actor_id: str | None) -> bool:
    return await _run("followup", _write_followup_event, followup, actor_id)


_CONNECTION_CHECKED = {"done": False}


def _check_connection() -> None:
    repo = _connect()
    try:
        repo._fetch("SELECT 1 AS ok")
    finally:
        repo.connection.close()


async def check_connection_once() -> None:
    """Deja en el registro si la app puede escribir en Azure SQL (una vez por instancia)."""
    if not is_enabled() or _CONNECTION_CHECKED["done"]:
        return
    _CONNECTION_CHECKED["done"] = True
    try:
        await asyncio.to_thread(_check_connection)
        logger.warning("Persistencia SQL activa: conexión a Azure SQL verificada.")
    except Exception:
        logger.exception("Persistencia SQL activa pero sin conexión a Azure SQL.")
