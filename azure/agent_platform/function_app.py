from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import sys
import urllib.request
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import azure.durable_functions as df
import azure.functions as func

_FUNCTION_ROOT = Path(__file__).resolve().parent
REPO_ROOT = next(
    (
        candidate
        for candidate in Path(__file__).resolve().parents
        if (candidate / "src" / "ml" / "feedback_loop.py").is_file()
    ),
    _FUNCTION_ROOT,
)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ml.feedback_loop import append_feedback_event, summarize_feedback

from sat_agents.agents import (
    analyze_academic,
    analyze_socioeconomic,
    analyze_wellbeing,
    synthesize_recommendation,
)
from sat_agents.contracts import (
    AnalysisCase,
    ContractError,
    parse_agent_result,
    parse_approval,
)
from sat_agents.reviews import record_approval, save_pending_review
from sat_agents.reviews import (
    _public_review,
    get_review,
    list_review_report_rows,
    list_reviews,
)
from sat_agents.pilot_limits import (
    MAX_EVALUATIONS_PER_PILOT,
    PilotConcurrencyLimitReached,
    PilotLimitReached,
    get_pilot_counter,
    release_evaluation_slot,
    reserve_evaluation_slot,
)
from sat_agents.usage import build_usage_report
from sat_agents.synthetic_database import (
    MAX_BATCH_SIZE,
    claim_synthetic_cases,
    create_synthetic_followup,
    get_database_summary,
    get_pending_synthetic_cases,
    get_poc_enabled,
    get_synthetic_dashboard,
    get_synthetic_student,
    list_synthetic_alerts,
    list_synthetic_followups,
    list_synthetic_students,
    list_synthetic_cases,
    set_poc_enabled,
    update_synthetic_alert,
    update_synthetic_case_status as update_synthetic_case_record,
    update_synthetic_followup,
)


logger = logging.getLogger(__name__)
app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

AZURE_ML_ENDPOINT_URL = os.environ.get("AZURE_ML_ENDPOINT_URL", "").rstrip("/")
AZURE_ML_ENDPOINT_KEY = os.environ.get("AZURE_ML_ENDPOINT_KEY", "")
AZURE_ML_DEPLOYMENT_NAME = os.environ.get("AZURE_ML_DEPLOYMENT_NAME", "blue")


def _call_azure_ml_endpoint(payload: dict[str, Any]) -> tuple[int, str]:
    endpoint_url = AZURE_ML_ENDPOINT_URL or os.environ.get("AZUREML_ENDPOINT_URL", "").rstrip("/")
    endpoint_key = AZURE_ML_ENDPOINT_KEY or os.environ.get("AZUREML_ENDPOINT_KEY", "")
    deployment_name = AZURE_ML_DEPLOYMENT_NAME or os.environ.get("AZUREML_DEPLOYMENT_NAME", "blue")

    if not endpoint_url or not endpoint_key:
        raise RuntimeError(
            "Falta la configuración del endpoint Azure ML. Define AZURE_ML_ENDPOINT_URL y AZURE_ML_ENDPOINT_KEY."
        )

    request = urllib.request.Request(
        endpoint_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {endpoint_key}",
            "azureml-model-deployment": deployment_name,
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=180) as response:
        status = response.getcode()
        body = response.read().decode("utf-8")
    return status, body


_QUEUE_SOCIOECONOMIC = "socioeconomic-analysis"
_QUEUE_ACADEMIC = "academic-analysis"
_QUEUE_WELLBEING = "wellbeing-analysis"
_QUEUE_RESULTS = "agent-results"
_REVIEW_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_MAX_HTTP_BODY_BYTES = 16_384
_MAX_MODEL_REQUEST_BYTES = 1_048_576
_STATIC_DIR = Path(__file__).parent / "static"
_STATIC_ASSETS = {
    "dashboard.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "logo.png": "image/png",
    "logo-transparent.png": "image/png",
    "logo-symbol.png": "image/png",
}


def _static_response(filename: str) -> func.HttpResponse:
    if filename != "index.html" and filename not in _STATIC_ASSETS:
        return func.HttpResponse("Not Found", status_code=404)
    content_type = (
        "text/html; charset=utf-8"
        if filename == "index.html"
        else _STATIC_ASSETS[filename]
    )
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if filename == "index.html":
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; "
            "style-src 'self' https://fonts.googleapis.com; "
            "style-src-attr 'unsafe-inline'; "
            "font-src 'self' https://fonts.gstatic.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'"
        )
        headers["X-Frame-Options"] = "DENY"
        headers["Referrer-Policy"] = "no-referrer"
    body = (_STATIC_DIR / filename).read_bytes()
    return func.HttpResponse(body=body, mimetype=content_type, headers=headers)


@app.route(route="api/ml/predict", methods=["POST"])
def predict_with_azure_ml(req: func.HttpRequest) -> func.HttpResponse:
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(req)
    if auth_error:
        return auth_error
    if len(req.get_body()) > _MAX_MODEL_REQUEST_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 1 MB.", status_code=413)
    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "El cuerpo debe ser JSON válido."}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )

    if not isinstance(body, dict) or not isinstance(body.get("data"), list):
        return func.HttpResponse(
            json.dumps({"error": "Se espera un JSON con la propiedad 'data' como lista."}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )

    try:
        status_code, response_body = _call_azure_ml_endpoint(body)
        return func.HttpResponse(response_body, status_code=status_code, mimetype="application/json")
    except Exception as error:
        logger.exception("Error al invocar el endpoint de Azure ML.")
        return func.HttpResponse(
            json.dumps({"error": "No se pudo completar la inferencia."}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json",
        )


@app.route(route="/", methods=["GET"])
def serve_index(req: func.HttpRequest) -> func.HttpResponse:
    return _static_response("index.html")


@app.route(route="{asset}", methods=["GET"])
def serve_static_asset(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    filename = request.route_params.get("asset", "")
    return _static_response(filename)


def _decode_message(message: func.ServiceBusMessage) -> dict[str, Any]:
    try:
        result = json.loads(message.get_body().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError("El mensaje de Service Bus no contiene JSON válido.") from error
    if not isinstance(result, dict):
        raise ContractError("El mensaje de Service Bus debe ser un objeto JSON.")
    return result


def _require_synthetic_mode() -> None:
    if os.environ.get("DATA_MODE") != "synthetic":
        raise RuntimeError(
            "La app solo admite DATA_MODE=synthetic hasta aprobar una integración "
            "institucional."
        )


async def _require_poc_enabled() -> None:
    if not await get_poc_enabled():
        raise RuntimeError("El procesamiento de la POC está pausado.")


async def _send_queue_message(queue_name: str, body: dict[str, Any], message_id: str):
    from azure.identity.aio import DefaultAzureCredential
    from azure.servicebus import ServiceBusMessage
    from azure.servicebus.aio import ServiceBusClient

    namespace = os.environ.get("SERVICEBUS_NAMESPACE")
    if not namespace:
        raise RuntimeError("Configure SERVICEBUS_NAMESPACE.")
    async with DefaultAzureCredential() as credential:
        async with ServiceBusClient(
            fully_qualified_namespace=namespace,
            credential=credential,
        ) as client:
            async with client.get_queue_sender(queue_name) as sender:
                await sender.send_messages(
                    ServiceBusMessage(
                        json.dumps(body, ensure_ascii=False),
                        message_id=message_id,
                        content_type="application/json",
                    )
                )


@app.route(route="api/poc/status", methods=["GET"])
async def get_poc_status(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        enabled = await get_poc_enabled()
        database = await get_database_summary()
        cases = await list_synthetic_cases(limit=25)
        counter = await get_pilot_counter()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    return func.HttpResponse(
        json.dumps(
            {
                "enabled": enabled,
                "database": database,
                "cases": cases,
                "active_operations": len(counter.get("active_instance_ids", [])),
                "accepted_count": counter.get("accepted_count", 0),
                "evaluation_limit": MAX_EVALUATIONS_PER_PILOT,
            },
            ensure_ascii=False,
        ),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/model/feedback", methods=["POST"])
def submit_model_feedback(req: func.HttpRequest) -> func.HttpResponse:
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    reviewer_id, auth_error = _authorize_reviewer(req)
    if auth_error:
        return auth_error
    if len(req.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "El cuerpo debe ser JSON válido."}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )

    if not isinstance(payload, dict):
        return func.HttpResponse(
            json.dumps({"error": "Se espera un JSON con la revisión del modelo."}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )

    if not isinstance(payload.get("student_id"), str) or not payload["student_id"].startswith("ST-SYN-"):
        return func.HttpResponse(
            json.dumps({"error": "Solo se acepta feedback de casos sintéticos."}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )
    payload["reviewer_id"] = reviewer_id

    try:
        event = append_feedback_event(payload)
    except ValueError as error:
        return func.HttpResponse(
            json.dumps({"error": str(error)}, ensure_ascii=False),
            status_code=400,
            mimetype="application/json",
        )
    except Exception as error:  # pragma: no cover - safety net for runtime envs
        logger.exception("No se pudo registrar el feedback del modelo.")
        return func.HttpResponse(
            json.dumps({"error": str(error)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json",
        )

    return func.HttpResponse(
        json.dumps({"status": "ok", "event": event}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/model/feedback", methods=["GET"])
def list_model_feedback(req: func.HttpRequest) -> func.HttpResponse:
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(req)
    if auth_error:
        return auth_error
    try:
        summary = summarize_feedback()
    except Exception as error:  # pragma: no cover - safety net for runtime envs
        logger.exception("No se pudo consultar el feedback del modelo.")
        return func.HttpResponse(
            json.dumps({"error": str(error)}, ensure_ascii=False),
            status_code=500,
            mimetype="application/json",
        )

    return func.HttpResponse(
        json.dumps(summary, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/dashboard", methods=["GET"])
async def get_synthetic_dashboard_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        dashboard = await get_synthetic_dashboard(
            campus=request.params.get("campus", ""),
            program=request.params.get("program", ""),
        )
        reviews = await list_reviews()
        dashboard["review_aggregate"] = reviews.get("aggregate", {})
        dashboard["pending_reviews"] = reviews.get("pending_reviews", [])
        dashboard["pending_truncated"] = reviews.get("pending_truncated", False)
        dashboard["generated_reviews"] = reviews.get("generated_reviews", [])
        dashboard["generated_truncated"] = reviews.get("generated_truncated", False)
        return func.HttpResponse(
            json.dumps(dashboard, ensure_ascii=False),
            status_code=200,
            mimetype="application/json",
        )
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    except Exception:
        return func.HttpResponse("No se pudo cargar el dashboard sintético.", status_code=503)


@app.route(route="api/poc/alerts", methods=["GET"])
async def list_synthetic_alerts_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        items = await list_synthetic_alerts(
            status=request.params.get("status", "open"),
            limit=int(request.params.get("limit", "100")),
            campus=request.params.get("campus", ""),
            program=request.params.get("program", ""),
        )
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        return func.HttpResponse("No se pudieron consultar las alertas.", status_code=503)
    return func.HttpResponse(
        json.dumps({"items": items}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/alerts/{alert_id}/status", methods=["POST"])
async def update_synthetic_alert_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    reviewer_id, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        payload = request.get_json()
    except ValueError:
        return func.HttpResponse("El cuerpo debe ser JSON válido.", status_code=400)
    if not isinstance(payload, dict) or set(payload) != {"status"}:
        return func.HttpResponse("Envíe únicamente status.", status_code=400)
    try:
        alert = await update_synthetic_alert(
            request.route_params.get("alert_id", ""), payload["status"], reviewer_id
        )
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        return func.HttpResponse("No se pudo actualizar la alerta.", status_code=503)
    return func.HttpResponse(
        json.dumps({"alert": alert}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/followups", methods=["GET"])
async def list_synthetic_followups_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        items = await list_synthetic_followups(
            status=request.params.get("status", "active"),
            limit=int(request.params.get("limit", "100")),
        )
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        return func.HttpResponse("No se pudieron consultar los seguimientos.", status_code=503)
    return func.HttpResponse(
        json.dumps({"items": items}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/followups", methods=["POST"])
async def create_synthetic_followup_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    reviewer_id, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        payload = request.get_json()
    except ValueError:
        return func.HttpResponse("El cuerpo debe ser JSON válido.", status_code=400)
    if (
        not isinstance(payload, dict)
        or set(payload) - {"student_id", "action", "due_date", "owner"}
        or not isinstance(payload.get("student_id"), str)
        or not isinstance(payload.get("action"), str)
        or (payload.get("due_date") is not None and not isinstance(payload["due_date"], str))
        or (payload.get("owner") is not None and not isinstance(payload["owner"], str))
    ):
        return func.HttpResponse("student_id y action son obligatorios; due_date y owner son opcionales.", status_code=400)
    try:
        followup = await create_synthetic_followup(
            student_id=payload["student_id"],
            action=payload["action"],
            due_date=payload.get("due_date"),
            owner=payload.get("owner"),
            created_by=reviewer_id,
        )
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        return func.HttpResponse("No se pudo crear el seguimiento.", status_code=503)
    return func.HttpResponse(
        json.dumps({"followup": followup}, ensure_ascii=False),
        status_code=201,
        mimetype="application/json",
    )


@app.route(route="api/poc/followups/{followup_id}/status", methods=["POST"])
async def update_synthetic_followup_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    reviewer_id, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        payload = request.get_json()
    except ValueError:
        return func.HttpResponse("El cuerpo debe ser JSON válido.", status_code=400)
    if (
        not isinstance(payload, dict)
        or set(payload) - {"status", "owner"}
        or not isinstance(payload.get("status"), str)
        or (payload.get("owner") is not None and not isinstance(payload["owner"], str))
    ):
        return func.HttpResponse("status es obligatorio; owner es opcional.", status_code=400)
    try:
        followup = await update_synthetic_followup(
            followup_id=request.route_params.get("followup_id", ""),
            status=payload["status"],
            owner=payload.get("owner"),
            updated_by=reviewer_id,
        )
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception:
        return func.HttpResponse("No se pudo actualizar el seguimiento.", status_code=503)
    return func.HttpResponse(
        json.dumps({"followup": followup}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/students", methods=["GET"])
async def list_synthetic_students_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        limit = int(request.params.get("limit", "50"))
        offset = int(request.params.get("offset", "0"))
        min_probability = float(request.params.get("min_probability", "0"))
        result = await list_synthetic_students(
            search=request.params.get("search", ""),
            program=request.params.get("program", ""),
            campus=request.params.get("campus", ""),
            city=request.params.get("city", ""),
            faculty=request.params.get("faculty", ""),
            semester=request.params.get("semester", ""),
            risk=request.params.get("risk", ""),
            min_probability=min_probability,
            status=request.params.get("status", ""),
            limit=limit,
            offset=offset,
        )
    except (ValueError, TypeError) as error:
        return func.HttpResponse(str(error) or "Filtros inválidos.", status_code=400)
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/students/{student_id}", methods=["GET"])
async def get_synthetic_student_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    student_id = request.route_params.get("student_id", "")
    try:
        result = await get_synthetic_student(student_id)
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    except Exception as error:
        from azure.core.exceptions import ResourceNotFoundError

        if isinstance(error, ResourceNotFoundError):
            return func.HttpResponse("No existe el estudiante sintético.", status_code=404)
        return func.HttpResponse("No se pudo cargar el expediente sintético.", status_code=503)

    review_id = result["student"].get("review_id")
    result["analysis_result"] = None
    if review_id:
        try:
            proposal, decision_record = await get_review(review_id)
            public_review = _public_review(proposal)
            decision = (
                decision_record.get("approval")
                if isinstance(decision_record, dict)
                else None
            )
            if isinstance(decision, dict) and decision.get("decision"):
                public_review["status"] = decision["decision"]
            result["analysis_result"] = {
                "review": public_review,
                "status": public_review.get("status"),
                "decision": decision,
            }
        except LookupError:
            result["human_review"] = None
        except RuntimeError as error:
            return func.HttpResponse(str(error), status_code=503)
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/poc/state", methods=["POST"])
async def set_poc_status(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        payload = request.get_json()
    except ValueError:
        return func.HttpResponse("El cuerpo debe ser JSON válido.", status_code=400)
    if (
        not isinstance(payload, dict)
        or set(payload) != {"enabled"}
        or not isinstance(payload.get("enabled"), bool)
    ):
        return func.HttpResponse("Envíe únicamente enabled como booleano.", status_code=400)

    enabled = payload["enabled"]
    try:
        await set_poc_enabled(enabled)
        if not enabled:
            counter = await get_pilot_counter()
            database = await get_database_summary()
            if counter.get("active_instance_ids") or database.get("processing", 0):
                await set_poc_enabled(True)
                return func.HttpResponse(
                    "Espere a que finalice la evaluación o el lote activo antes de pausar.",
                    status_code=409,
                )
        return func.HttpResponse(
            json.dumps({"enabled": await get_poc_enabled()}),
            status_code=200,
            mimetype="application/json",
        )
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)


@app.route(route="api/batches", methods=["POST"])
@app.durable_client_input(client_name="durable_client")
async def start_synthetic_batch(
    req: func.HttpRequest, durable_client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    return await _start_synthetic_batch(req, durable_client)


async def _start_synthetic_batch(
    req: func.HttpRequest, durable_client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        await _require_poc_enabled()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        payload = request.get_json() if request.get_body() else {}
    except ValueError:
        return func.HttpResponse("El cuerpo debe ser JSON válido.", status_code=400)
    if not isinstance(payload, dict) or set(payload) - {"limit"}:
        return func.HttpResponse("El cuerpo solo puede contener limit.", status_code=400)
    limit = payload.get("limit", MAX_BATCH_SIZE)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BATCH_SIZE:
        return func.HttpResponse(
            f"limit debe ser un entero entre 1 y {MAX_BATCH_SIZE}.",
            status_code=400,
        )

    try:
        cases = await get_pending_synthetic_cases(limit)
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    except ValueError as error:
        return func.HttpResponse(str(error), status_code=400)
    if not cases:
        return func.HttpResponse(
            "No hay casos sintéticos pendientes de procesamiento.",
            status_code=409,
        )

    batch_id = uuid.uuid4().hex
    items = [
        {
            "case_id": case["case_id"],
            "review_id": f"{batch_id}-{index + 1:03d}",
            "case": case,
        }
        for index, case in enumerate(cases)
    ]
    try:
        await reserve_evaluation_slot(batch_id, evaluation_count=len(items))
    except PilotLimitReached as error:
        return func.HttpResponse(str(error), status_code=429)
    except PilotConcurrencyLimitReached as error:
        response = func.HttpResponse(str(error), status_code=429)
        response.headers["Retry-After"] = "10"
        return response
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)

    try:
        await _require_poc_enabled()
        await claim_synthetic_cases(
            [item["case_id"] for item in items], batch_id
        )
    except Exception as error:
        await release_evaluation_slot(batch_id)
        return func.HttpResponse(str(error), status_code=503)

    try:
        await durable_client.start_new(
            "batch_orchestrator",
            instance_id=batch_id,
            client_input={"batch_id": batch_id, "cases": items},
        )
    except Exception:
        for item in items:
            try:
                await update_synthetic_case_record(item["case_id"], "pending")
            except Exception:
                logger.exception("No se pudo liberar un caso sintético del lote.")
        await release_evaluation_slot(batch_id)
        raise

    return func.HttpResponse(
        json.dumps(
            {
                "batchId": batch_id,
                "selected": len(items),
                "statusUrl": f"/api/batches/{batch_id}",
            }
        ),
        status_code=202,
        mimetype="application/json",
    )


@app.route(route="api/cases", methods=["POST"])
@app.durable_client_input(client_name="durable_client")
async def start_case(
    req: func.HttpRequest, durable_client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        await _require_poc_enabled()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    try:
        case = AnalysisCase.from_dict(request.get_json())
    except (ValueError, ContractError) as error:
        return func.HttpResponse(str(error), status_code=400)

    instance_id = uuid.uuid4().hex
    try:
        await reserve_evaluation_slot(instance_id)
    except PilotLimitReached as error:
        return func.HttpResponse(str(error), status_code=429)
    except PilotConcurrencyLimitReached as error:
        response = func.HttpResponse(str(error), status_code=429)
        response.headers["Retry-After"] = "10"
        return response
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)

    try:
        await _require_poc_enabled()
    except RuntimeError as error:
        await release_evaluation_slot(instance_id)
        return func.HttpResponse(str(error), status_code=503)
    try:
        await durable_client.start_new(
            "analysis_orchestrator",
            instance_id=instance_id,
            client_input=case.to_dict(),
        )
    except Exception:
        await release_evaluation_slot(instance_id)
        raise
    return func.HttpResponse(
        json.dumps(
            {
                "instanceId": instance_id,
                "statusUrl": f"/api/cases/{instance_id}",
            }
        ),
        status_code=202,
        mimetype="application/json",
    )


@app.orchestration_trigger(context_name="context")
def analysis_orchestrator(context: df.DurableOrchestrationContext):
    orchestration_input = context.get_input()
    if (
        isinstance(orchestration_input, dict)
        and "case" in orchestration_input
        and "release_slot" in orchestration_input
    ):
        case = orchestration_input["case"]
        release_slot = bool(orchestration_input["release_slot"])
    else:
        case = orchestration_input
        release_slot = True
    instance_id = context.instance_id
    try:
        yield context.call_activity(
            "dispatch_agents",
            {"instance_id": instance_id, "case": case},
        )

        result_tasks = context.task_all(
            [
                context.wait_for_external_event("socioeconomic_result"),
                context.wait_for_external_event("academic_result"),
                context.wait_for_external_event("wellbeing_result"),
            ]
        )
        timeout_task = context.create_timer(
            context.current_utc_datetime + timedelta(minutes=15)
        )
        yield context.task_any([result_tasks, timeout_task])
        if not result_tasks.is_completed:
            raise TimeoutError("Los agentes no respondieron dentro de 15 minutos.")
        timeout_task.cancel()
        socioeconomic, academic, wellbeing = yield result_tasks

        return (
            yield context.call_activity(
                "create_pending_review",
                {
                    "review_id": instance_id,
                    "case": case,
                    "socioeconomic": socioeconomic,
                    "academic": academic,
                    "wellbeing": wellbeing,
                },
            )
        )
    finally:
        if release_slot:
            yield context.call_activity(
                "release_case_slot",
                {"instance_id": instance_id},
            )


@app.orchestration_trigger(context_name="context")
def batch_orchestrator(context: df.DurableOrchestrationContext):
    batch = context.get_input()
    batch_id = batch["batch_id"]
    cases = batch["cases"]
    results = []
    failed = False
    try:
        for index, item in enumerate(cases):
            try:
                yield context.call_sub_orchestrator(
                    "analysis_orchestrator",
                    {"case": item["case"], "release_slot": False},
                    instance_id=item["review_id"],
                )
            except Exception:
                failed = True
                yield context.call_activity(
                    "update_synthetic_case_status",
                    {"case_id": item["case_id"], "status": "pending"},
                )
                for remaining in cases[index + 1 :]:
                    yield context.call_activity(
                        "update_synthetic_case_status",
                        {"case_id": remaining["case_id"], "status": "pending"},
                    )
                results.append({"case_id": item["case_id"], "status": "failed"})
                break

            yield context.call_activity(
                "update_synthetic_case_status",
                {
                    "case_id": item["case_id"],
                    "status": "processed",
                    "batch_id": batch_id,
                    "review_id": item["review_id"],
                },
            )
            results.append(
                {
                    "case_id": item["case_id"],
                    "review_id": item["review_id"],
                    "status": "processed",
                }
            )
    finally:
        yield context.call_activity(
            "release_case_slot",
            {"instance_id": batch_id},
        )
    return {
        "batch_id": batch_id,
        "status": "completed_with_errors" if failed else "completed",
        "processed_count": sum(item["status"] == "processed" for item in results),
        "failed_count": sum(item["status"] == "failed" for item in results),
        "results": results,
    }


@app.activity_trigger(input_name="data")
async def dispatch_agents(data: dict) -> dict[str, bool]:
    _require_synthetic_mode()
    case = AnalysisCase.from_dict(data["case"]).to_dict()
    instance_id = data["instance_id"]
    await asyncio.gather(
        _send_queue_message(
            _QUEUE_SOCIOECONOMIC,
            {"instance_id": instance_id, "case": case},
            f"{instance_id}:socioeconomic",
        ),
        _send_queue_message(
            _QUEUE_ACADEMIC,
            {"instance_id": instance_id, "case": case},
            f"{instance_id}:academic",
        ),
        _send_queue_message(
            _QUEUE_WELLBEING,
            {"instance_id": instance_id, "case": case},
            f"{instance_id}:wellbeing",
        ),
    )
    return {"dispatched": True}


@app.activity_trigger(input_name="data")
async def release_case_slot(data: dict) -> None:
    await release_evaluation_slot(data["instance_id"])


@app.activity_trigger(input_name="data")
async def update_synthetic_case_status(data: dict) -> None:
    await update_synthetic_case_record(
        data["case_id"],
        data["status"],
        batch_id=data.get("batch_id", ""),
        review_id=data.get("review_id", ""),
    )


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name=_QUEUE_SOCIOECONOMIC,
    connection="ServiceBusConnection",
)
async def socioeconomic_worker(message: func.ServiceBusMessage) -> None:
    _require_synthetic_mode()
    payload = _decode_message(message)
    result = await analyze_socioeconomic(payload["case"])
    await _send_queue_message(
        _QUEUE_RESULTS,
        {
            "instance_id": payload["instance_id"],
            "agent": "socioeconomic",
            "result": result,
        },
        f"{payload['instance_id']}:socioeconomic:result",
    )


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name=_QUEUE_ACADEMIC,
    connection="ServiceBusConnection",
)
async def academic_worker(message: func.ServiceBusMessage) -> None:
    _require_synthetic_mode()
    payload = _decode_message(message)
    result = await analyze_academic(payload["case"])
    await _send_queue_message(
        _QUEUE_RESULTS,
        {
            "instance_id": payload["instance_id"],
            "agent": "academic",
            "result": result,
        },
        f"{payload['instance_id']}:academic:result",
    )


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name=_QUEUE_WELLBEING,
    connection="ServiceBusConnection",
)
async def wellbeing_worker(message: func.ServiceBusMessage) -> None:
    _require_synthetic_mode()
    payload = _decode_message(message)
    result = await analyze_wellbeing(payload["case"])
    await _send_queue_message(
        _QUEUE_RESULTS,
        {
            "instance_id": payload["instance_id"],
            "agent": "wellbeing",
            "result": result,
        },
        f"{payload['instance_id']}:wellbeing:result",
    )


@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name=_QUEUE_RESULTS,
    connection="ServiceBusConnection",
)
@app.durable_client_input(client_name="durable_client")
async def collect_agent_result(
    message: func.ServiceBusMessage,
    durable_client: df.DurableOrchestrationClient,
) -> None:
    _require_synthetic_mode()
    payload = _decode_message(message)
    agent = payload.get("agent")
    instance_id = payload.get("instance_id")
    if agent not in {"socioeconomic", "academic", "wellbeing"}:
        raise ContractError("El resultado tiene un agente desconocido.")
    if not isinstance(instance_id, str) or not _REVIEW_ID.fullmatch(instance_id):
        raise ContractError("El resultado no contiene un instance_id válido.")
    result = parse_agent_result(agent, payload.get("result"))
    await durable_client.raise_event(
        instance_id,
        f"{agent}_result",
        result,
    )


@app.activity_trigger(input_name="data")
async def create_pending_review(data: dict) -> dict[str, Any]:
    _require_synthetic_mode()
    case = AnalysisCase.from_dict(data["case"])
    socioeconomic = data["socioeconomic"]
    academic = data["academic"]
    wellbeing = data["wellbeing"]
    synthesis = await synthesize_recommendation(
        case.model_probability,
        socioeconomic["analysis"],
        academic,
        wellbeing["analysis"],
    )
    recommendation = synthesis["recommendation"]
    recommendation["human_review_required"] = True
    recommendation["automated_decision"] = False
    recommendation["display_status"] = "pending_human_review"
    usage_report = build_usage_report(
        socioeconomic["token_usage"],
        academic["token_usage"],
        synthesis["token_usage"],
        wellbeing=wellbeing["token_usage"],
    )
    proposal = {
        "review_id": data["review_id"],
        "student_id": (
            case.case_id[4:].upper()
            if re.fullmatch(r"syn-st-syn-\d{6}", case.case_id, re.IGNORECASE)
            else None
        ),
        "status": "pending_approval",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model_probability": case.model_probability,
        "recommendation": recommendation,
        "socioeconomic_analysis": socioeconomic["analysis"],
        "academic_analysis": {
            "analysis": academic["analysis"],
            "sources": academic["sources"],
        },
        "wellbeing_analysis": wellbeing["analysis"],
        "token_usage": {
            "calls": usage_report["calls"],
            "total": usage_report["total"],
        },
        "cost_estimate": usage_report["cost_estimate"],
    }
    await save_pending_review(data["review_id"], proposal)
    return proposal


def _reviewer_identity(request: func.HttpRequest) -> str | None:
    if os.environ.get("REVIEWER_AUTH_ENFORCED", "").lower() != "true":
        raise RuntimeError(
            "La autenticación Entra ID del revisor no está habilitada."
        )
    allowed_principal_ids = {
        principal_id.strip().lower()
        for principal_id in os.environ.get(
            "CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS", ""
        ).split(",")
        if principal_id.strip()
    }
    if not allowed_principal_ids:
        raise RuntimeError("Configure CASE_REVIEWER_ALLOWED_PRINCIPAL_IDS.")
    encoded_principal = request.headers.get("x-ms-client-principal")
    if not encoded_principal:
        return None
    try:
        padding = "=" * (-len(encoded_principal) % 4)
        principal = json.loads(
            base64.urlsafe_b64decode(encoded_principal + padding)
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ContractError("El principal de Entra ID no es válido.") from error

    if not isinstance(principal, dict):
        raise ContractError("El principal de Entra ID no es válido.")
    claims = principal.get("claims", [])
    if not isinstance(claims, list):
        raise ContractError("El principal de Entra ID no contiene claims válidos.")
    principal_id = next(
        (
            claim.get("val")
            for claim in claims
            if isinstance(claim, dict)
            and isinstance(claim.get("typ"), str)
            and claim.get("typ").lower()
            in {
                "oid",
                "objectidentifier",
                "http://schemas.microsoft.com/identity/claims/objectidentifier",
            }
            and isinstance(claim.get("val"), str)
            and claim.get("val")
        ),
        None,
    )
    if not isinstance(principal_id, str) or not principal_id:
        principal_id = principal.get("userId")
    if not isinstance(principal_id, str) or not principal_id:
        return None
    if principal_id.lower() not in allowed_principal_ids:
        return None
    return principal_id


def _authorize_reviewer(
    request: func.HttpRequest,
) -> tuple[str | None, func.HttpResponse | None]:
    try:
        reviewer_id = _reviewer_identity(request)
    except RuntimeError as error:
        return None, func.HttpResponse(str(error), status_code=503)
    except ContractError as error:
        return None, func.HttpResponse(str(error), status_code=401)
    if reviewer_id is None:
        status = 403 if request.headers.get("x-ms-client-principal") else 401
        message = (
            "El usuario autenticado no está autorizado como revisor."
            if status == 403
            else "Se requiere autenticación de Entra ID."
        )
        return None, func.HttpResponse(message, status_code=status)
    return reviewer_id, None


@app.route(
    route="api/cases/{instance_id}", methods=["GET"]
)
@app.durable_client_input(client_name="durable_client")
async def get_case_status(
    req: func.HttpRequest, durable_client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    request = req
    if os.environ.get("DATA_MODE") != "synthetic":
        return func.HttpResponse("La app solo admite DATA_MODE=synthetic.", status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    instance_id = request.route_params.get("instance_id", "")
    if not _REVIEW_ID.fullmatch(instance_id):
        return func.HttpResponse("instance_id no válido.", status_code=400)
    status = await durable_client.get_status(instance_id, show_input=False)
    if status is None:
        return func.HttpResponse("No existe la evaluación.", status_code=404)
    runtime_status = getattr(status.runtime_status, "value", status.runtime_status)
    response = {
        "instanceId": instance_id,
        "runtimeStatus": str(runtime_status),
    }
    output = getattr(status, "output", None)
    if isinstance(output, dict) and output.get("review_id"):
        response["review"] = _public_review(output)
    return func.HttpResponse(
        json.dumps(response, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/batches/{batch_id}", methods=["GET"])
@app.durable_client_input(client_name="durable_client")
async def get_batch_status(
    req: func.HttpRequest, durable_client: df.DurableOrchestrationClient
) -> func.HttpResponse:
    request = req
    if os.environ.get("DATA_MODE") != "synthetic":
        return func.HttpResponse("La app solo admite DATA_MODE=synthetic.", status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    batch_id = request.route_params.get("batch_id", "")
    if not _REVIEW_ID.fullmatch(batch_id):
        return func.HttpResponse("batch_id no válido.", status_code=400)
    status = await durable_client.get_status(batch_id, show_input=False)
    if status is None:
        return func.HttpResponse("No existe el lote.", status_code=404)
    runtime_status = getattr(status.runtime_status, "value", status.runtime_status)
    output = status.output if isinstance(status.output, dict) else {}
    return func.HttpResponse(
        json.dumps(
            {
                "batchId": batch_id,
                "runtimeStatus": str(runtime_status),
                "status": output.get("status"),
                "processedCount": output.get("processed_count", 0),
                "failedCount": output.get("failed_count", 0),
                "results": output.get("results", []),
            },
            ensure_ascii=False,
        ),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/reviews", methods=["GET"])
async def get_reviews(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    if os.environ.get("DATA_MODE") != "synthetic":
        return func.HttpResponse("La app solo admite DATA_MODE=synthetic.", status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        result = await list_reviews()
        counter = await get_pilot_counter()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    except Exception:
        return func.HttpResponse(
            "No se pudo consultar el panel de revisiones.", status_code=503
        )
    result["aggregate"]["evaluations_accepted"] = counter.get("accepted_count", 0)
    result["aggregate"]["active_cases"] = len(
        counter.get("active_instance_ids", [])
    )
    result["aggregate"]["evaluation_limit"] = MAX_EVALUATIONS_PER_PILOT
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(route="api/reports/reviews", methods=["GET"])
async def get_review_report_rows_api(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    if os.environ.get("DATA_MODE") != "synthetic":
        return func.HttpResponse(
            "La app solo admite DATA_MODE=synthetic.", status_code=503
        )
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    try:
        rows = await list_review_report_rows()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    except Exception:
        return func.HttpResponse(
            "No se pudieron consultar los resultados para el reporte.",
            status_code=503,
        )
    return func.HttpResponse(
        json.dumps({"rows": rows}, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(
    route="api/reviews/{review_id}", methods=["GET"]
)
async def get_review_detail(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    if os.environ.get("DATA_MODE") != "synthetic":
        return func.HttpResponse("La app solo admite DATA_MODE=synthetic.", status_code=503)
    _, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    review_id = request.route_params.get("review_id", "")
    if not _REVIEW_ID.fullmatch(review_id):
        return func.HttpResponse("review_id no válido.", status_code=400)
    try:
        proposal, decision_record = await get_review(review_id)
    except LookupError as error:
        return func.HttpResponse(str(error), status_code=404)
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    except Exception:
        return func.HttpResponse(
            "No se pudo cargar la propuesta de revisión.", status_code=503
        )
    public_review = _public_review(proposal)
    result = {"review": public_review, "decision": None}
    if isinstance(decision_record, dict):
        approval = decision_record.get("approval", {})
        if approval.get("decision"):
            public_review["status"] = approval["decision"]
        result["decision"] = {
            "decision": approval.get("decision"),
            "approved_action": approval.get("approved_action"),
        }
    return func.HttpResponse(
        json.dumps(result, ensure_ascii=False),
        status_code=200,
        mimetype="application/json",
    )


@app.route(
    route="api/reviews/{review_id}/approval",
    methods=["POST"],
)
async def approve_review(req: func.HttpRequest) -> func.HttpResponse:
    request = req
    try:
        _require_synthetic_mode()
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    reviewer_id, auth_error = _authorize_reviewer(request)
    if auth_error:
        return auth_error
    review_id = request.route_params.get("review_id", "")
    if not _REVIEW_ID.fullmatch(review_id):
        return func.HttpResponse("review_id no válido.", status_code=400)
    if len(request.get_body()) > _MAX_HTTP_BODY_BYTES:
        return func.HttpResponse("El cuerpo excede el límite de 16 KB.", status_code=413)
    followup = None
    already_recorded = False
    try:
        approval = parse_approval(request.get_json())
        proposal, _ = await get_review(review_id)
        try:
            await record_approval(review_id, reviewer_id, approval)
        except FileExistsError:
            proposal, existing_decision = await get_review(review_id)
            existing_approval = (
                existing_decision.get("approval", {})
                if isinstance(existing_decision, dict)
                else {}
            )
            if (
                existing_decision is None
                or existing_decision.get("reviewer_id") != reviewer_id
                or existing_approval != approval
            ):
                raise
            already_recorded = True

        if approval["decision"] in {"approved", "edited"}:
            recommendation = proposal.get("recommendation") or {}
            proposed_actions = recommendation.get("proposed_actions") or []
            action = approval.get("approved_action") or (
                proposed_actions[0] if proposed_actions else None
            )
            student_id = proposal.get("student_id")
            if student_id and action:
                followup = await create_synthetic_followup(
                    student_id=student_id,
                    action=action,
                    created_by=reviewer_id,
                    review_id=review_id,
                )
    except (ValueError, ContractError) as error:
        return func.HttpResponse(str(error), status_code=400)
    except LookupError as error:
        return func.HttpResponse(str(error), status_code=404)
    except FileExistsError as error:
        return func.HttpResponse(str(error), status_code=409)
    except RuntimeError as error:
        return func.HttpResponse(str(error), status_code=503)
    except Exception:
        return func.HttpResponse(
            "No se pudo guardar la decisión de revisión.", status_code=503
        )

    logger.info("Aprobación registrada para review_id=%s", review_id)
    return func.HttpResponse(
        json.dumps(
            {
                "review_id": review_id,
                "status": "recorded",
                "followup": followup,
            },
            ensure_ascii=False,
        ),
        status_code=200 if already_recorded else 201,
        mimetype="application/json",
    )
