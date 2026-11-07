from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from .policy import ALLOWED_FOLLOWUP_ACTIONS


class ContractError(ValueError):
    """Raised when an external payload violates the agent-platform contract."""


_CASE_ID = re.compile(r"^syn-[A-Za-z0-9_-]{1,76}$")
_COURSE_CODE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_FAMILY_CONTEXTS = {"unknown", "no_dependents", "has_dependents"}
_PROPOSED_ACTIONS = ALLOWED_FOLLOWUP_ACTIONS


def _object(value: Any, name: str, allowed: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"'{name}' debe ser un objeto JSON.")
    unexpected = set(value) - allowed
    if unexpected:
        raise ContractError(
            f"'{name}' contiene campos no permitidos: {', '.join(sorted(unexpected))}."
        )
    return value


def _optional_text(value: Any, name: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError(f"'{name}' debe ser texto de 1 a {limit} caracteres.")
    return value.strip()


def _number(
    value: Any,
    name: str,
    minimum: float,
    maximum: float,
    *,
    integer: bool = False,
) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"'{name}' debe ser numérico.")
    if not math.isfinite(value) or value < minimum or value > maximum:
        raise ContractError(f"'{name}' debe estar entre {minimum} y {maximum}.")
    if integer and not isinstance(value, int):
        raise ContractError(f"'{name}' debe ser entero.")
    return value


@dataclass(frozen=True)
class AcademicSignal:
    course_code: str
    grade: float | None
    attendance_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "course_code": self.course_code,
            "grade": self.grade,
            "attendance_pct": self.attendance_pct,
        }


@dataclass(frozen=True)
class AnalysisCase:
    case_id: str
    model_probability: float
    arrears_months: int | None
    arrears_balance_cop: int | None
    socioeconomic_stratum: int | None
    origin_city: str | None
    family_context: str
    academic_signals: tuple[AcademicSignal, ...]

    @classmethod
    def from_dict(cls, payload: Any) -> "AnalysisCase":
        data = _object(
            payload,
            "payload",
            {"case_id", "model_probability", "economic", "academic_signals"},
        )
        case_id = data.get("case_id")
        if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
            raise ContractError(
                "'case_id' debe ser un token sintético con prefijo 'syn-'; "
                "no se aceptan identificadores institucionales."
            )

        probability = _number(
            data.get("model_probability"), "model_probability", 0, 1
        )
        if probability is None:
            raise ContractError("'model_probability' es obligatorio.")

        economic = _object(
            data.get("economic", {}),
            "economic",
            {
                "arrears_months",
                "arrears_balance_cop",
                "socioeconomic_stratum",
                "origin_city",
                "family_context",
            },
        )
        arrears_months = _number(
            economic.get("arrears_months"),
            "arrears_months",
            0,
            120,
            integer=True,
        )
        arrears_balance = _number(
            economic.get("arrears_balance_cop"),
            "arrears_balance_cop",
            0,
            1_000_000_000,
            integer=True,
        )
        stratum = _number(
            economic.get("socioeconomic_stratum"),
            "socioeconomic_stratum",
            1,
            6,
            integer=True,
        )
        family_context = economic.get("family_context", "unknown")
        if not isinstance(family_context, str) or family_context not in _FAMILY_CONTEXTS:
            raise ContractError(
                "'family_context' debe ser unknown, no_dependents o has_dependents."
            )

        raw_signals = data.get("academic_signals", [])
        if not isinstance(raw_signals, list) or len(raw_signals) > 30:
            raise ContractError("'academic_signals' debe ser una lista de hasta 30.")
        signals = []
        for index, raw_signal in enumerate(raw_signals):
            signal = _object(
                raw_signal,
                f"academic_signals[{index}]",
                {"course_code", "grade", "attendance_pct"},
            )
            course_code = signal.get("course_code")
            if (
                not isinstance(course_code, str)
                or not _COURSE_CODE.fullmatch(course_code)
            ):
                raise ContractError(
                    f"'academic_signals[{index}].course_code' no es válido."
                )
            signals.append(
                AcademicSignal(
                    course_code=course_code,
                    grade=_number(
                        signal.get("grade"),
                        f"academic_signals[{index}].grade",
                        0,
                        5,
                    ),
                    attendance_pct=_number(
                        signal.get("attendance_pct"),
                        f"academic_signals[{index}].attendance_pct",
                        0,
                        100,
                    ),
                )
            )

        return cls(
            case_id=case_id,
            model_probability=probability,
            arrears_months=arrears_months,
            arrears_balance_cop=arrears_balance,
            socioeconomic_stratum=stratum,
            origin_city=_optional_text(
                economic.get("origin_city"), "origin_city", 80
            ),
            family_context=family_context,
            academic_signals=tuple(signals),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "model_probability": self.model_probability,
            "economic": {
                "arrears_months": self.arrears_months,
                "arrears_balance_cop": self.arrears_balance_cop,
                "socioeconomic_stratum": self.socioeconomic_stratum,
                "origin_city": self.origin_city,
                "family_context": self.family_context,
            },
            "academic_signals": [
                signal.to_dict() for signal in self.academic_signals
            ],
        }

    def agent_context(self) -> dict[str, Any]:
        return {
            "model_probability": self.model_probability,
            "economic": {
                "arrears_months": self.arrears_months,
                "arrears_balance_cop": self.arrears_balance_cop,
                "socioeconomic_stratum": self.socioeconomic_stratum,
                "origin_city": self.origin_city,
                "family_context": self.family_context,
            },
            "academic_signals": [
                signal.to_dict() for signal in self.academic_signals
            ],
        }


def parse_analysis_response(
    text: str, allowed_citation_ids: set[str] | None = None
) -> dict[str, Any]:
    import json

    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError("El agente no devolvió JSON válido.") from error
    result = _object(
        result,
        "analysis",
        {"summary", "observations", "limitations", "citation_ids"},
    )
    summary = _optional_text(result.get("summary"), "summary", 1200)
    if summary is None:
        raise ContractError("'summary' es obligatorio.")
    observations = _text_list(result.get("observations"), "observations")
    limitations = _text_list(result.get("limitations"), "limitations")
    citation_ids = result.get("citation_ids", [])
    if (
        not isinstance(citation_ids, list)
        or len(citation_ids) > 8
        or any(not isinstance(item, str) for item in citation_ids)
    ):
        raise ContractError("'citation_ids' debe ser una lista de hasta 8 textos.")
    allowed = allowed_citation_ids or set()
    if any(item not in allowed for item in citation_ids):
        raise ContractError("El agente citó una fuente que no fue recuperada.")
    return {
        "summary": summary,
        "observations": observations,
        "limitations": limitations,
        "citation_ids": citation_ids,
    }


def parse_agent_result(agent: str, payload: Any) -> dict[str, Any]:
    import json

    if agent == "socioeconomic":
        data = _object(payload, "socioeconomic_result", {"analysis", "token_usage"})
        return {
            "analysis": parse_analysis_response(json.dumps(data.get("analysis"))),
            "token_usage": _parse_token_usage(data.get("token_usage")),
        }
    if agent != "academic":
        raise ContractError("El resultado tiene un agente desconocido.")

    data = _object(
        payload, "academic_result", {"analysis", "sources", "token_usage"}
    )
    sources = data.get("sources")
    if not isinstance(sources, list) or len(sources) > 3:
        raise ContractError("'sources' debe contener hasta 3 documentos.")
    validated_sources = []
    for index, source in enumerate(sources):
        source = _object(
            source,
            f"sources[{index}]",
            {"id", "title", "source_uri", "section", "content"},
        )
        values = {}
        for field, limit in (
            ("id", 200),
            ("title", 200),
            ("source_uri", 500),
            ("section", 200),
            ("content", 2000),
        ):
            value = _optional_text(source.get(field), f"sources[{index}].{field}", limit)
            if value is None:
                raise ContractError(f"'sources[{index}].{field}' es obligatorio.")
            values[field] = value
        parsed_uri = urlsplit(values["source_uri"])
        if (
            parsed_uri.scheme != "https"
            or not parsed_uri.netloc
            or parsed_uri.username
            or parsed_uri.password
            or parsed_uri.query
            or parsed_uri.fragment
        ):
            raise ContractError(
                f"'sources[{index}].source_uri' debe ser una URL HTTPS estable, "
                "sin credenciales, query ni fragmento."
            )
        validated_sources.append(values)

    source_ids = {source["id"] for source in validated_sources}
    if len(source_ids) != len(validated_sources):
        raise ContractError("El índice RAG devolvió ids de fuente duplicados.")
    analysis = parse_analysis_response(
        json.dumps(data.get("analysis")),
        source_ids,
    )
    return {
        "analysis": analysis,
        "sources": validated_sources,
        "token_usage": _parse_token_usage(data.get("token_usage")),
    }


def _parse_token_usage(value: Any) -> dict[str, int]:
    data = _object(
        value,
        "token_usage",
        {"input_tokens", "output_tokens", "total_tokens"},
    )
    counts = {}
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        count = data.get(field)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ContractError(f"'token_usage.{field}' debe ser un entero no negativo.")
        counts[field] = count
    if counts["input_tokens"] + counts["output_tokens"] != counts["total_tokens"]:
        raise ContractError("'token_usage.total_tokens' no coincide con sus partes.")
    return counts


def parse_recommendation_response(text: str) -> dict[str, Any]:
    import json

    try:
        result = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError("El sintetizador no devolvió JSON válido.") from error
    result = _object(
        result,
        "recommendation",
        {"summary", "proposed_actions", "limitations"},
    )
    summary = _optional_text(result.get("summary"), "summary", 1200)
    if summary is None:
        raise ContractError("'summary' es obligatorio.")
    actions = result.get("proposed_actions")
    if (
        not isinstance(actions, list)
        or len(actions) > 4
        or any(not isinstance(action, str) for action in actions)
        or any(action not in _PROPOSED_ACTIONS for action in actions)
    ):
        raise ContractError("'proposed_actions' contiene una acción no permitida.")
    return {
        "summary": summary,
        "proposed_actions": actions,
        "limitations": _text_list(result.get("limitations"), "limitations"),
        "human_review_required": True,
        "automated_decision": False,
    }


def _text_list(value: Any, name: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 8:
        raise ContractError(f"'{name}' debe ser una lista de hasta 8 textos.")
    cleaned = []
    for index, item in enumerate(value):
        text = _optional_text(item, f"{name}[{index}]", 500)
        if text is None:
            raise ContractError(f"'{name}[{index}]' no puede estar vacío.")
        cleaned.append(text)
    return cleaned


def parse_approval(payload: Any) -> dict[str, Any]:
    data = _object(
        payload,
        "approval",
        {"decision", "note", "approved_action"},
    )
    decision = data.get("decision")
    if not isinstance(decision, str) or decision not in {
        "approved",
        "edited",
        "rejected",
    }:
        raise ContractError("'decision' debe ser approved, edited o rejected.")
    raw_note = data.get("note")
    if raw_note is None or raw_note == "":
        note = ""
    else:
        note = _optional_text(raw_note, "note", 1000)
    action = data.get("approved_action")
    if action is not None and (
        not isinstance(action, str) or action not in _PROPOSED_ACTIONS
    ):
        raise ContractError("'approved_action' no es una acción permitida.")
    if decision == "edited" and action is None:
        raise ContractError(
            "'approved_action' es obligatorio cuando la propuesta se edita."
        )
    if decision != "edited" and action is not None:
        raise ContractError(
            "'approved_action' solo se admite para una propuesta editada."
        )
    return {
        "decision": decision,
        "note": note or "",
        "approved_action": action,
    }
