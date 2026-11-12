"""Consolidación ejecutiva del análisis multiagente.

Los agentes (socioeconómico, académico, bienestar y sintetizador) actúan como motores
internos: su salida nunca se muestra tal cual. Este módulo la combina con los datos del
expediente y produce una única vista institucional con límites fijos de tamaño:

- resumen: nivel de riesgo con su probabilidad, prioridad de atención y estado;
- un único diagnóstico explicativo (máx. ``MAX_WORDS`` palabras) que integra lo que
  analizaron los agentes; si aún no hay análisis, uno preliminar a partir de los datos;
- hasta ``MAX_FACTORS`` factores con su evidencia numérica e impacto relativo
  (cada dato aparece una sola vez: no hay tarjetas que repitan los factores);
- hasta ``MAX_ACTIONS`` acciones concretas en formato checklist;
- hasta ``MAX_TIMELINE`` eventos de intervención.

El tamaño de la salida es independiente del volumen de estudiantes y del texto que
generen los agentes, lo que garantiza una lectura de pocos segundos por caso.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .policy import (
    CRITICAL_PROBABILITY_THRESHOLD,
    FOLLOWUP_ACTION_LABELS,
    RISK_HIGH_THRESHOLD,
    RISK_MEDIUM_THRESHOLD,
)

MAX_FACTORS = 4
MAX_ACTIONS = 4
MAX_TIMELINE = 5
MAX_WORDS = 150
MAX_FACTOR_CHARS = 70
MAX_LAYOUT_WORDS = 100

ATTENDANCE_THRESHOLD = 75.0
PASSING_GRADE = 3.0

CONTACT_ACTION = "retention_contact"

# Etiquetas institucionales; los códigos internos solo viajan como identificadores.
ACTION_LABELS = {
    CONTACT_ACTION: "Contacto desde permanencia",
    "academic_advisor_review": "Cita con asesor académico",
    "tutoring_review": "Tutoría en asignaturas críticas",
    "financial_aid_review": "Evaluación de apoyo financiero",
    "wellbeing_review": "Seguimiento en bienestar universitario",
}

_LEVELS = (
    # (umbral mínimo, etiqueta, tono)
    (CRITICAL_PROBABILITY_THRESHOLD, "Crítico", "critical"),
    (RISK_HIGH_THRESHOLD, "Alto", "high"),
    (RISK_MEDIUM_THRESHOLD, "Medio", "medium"),
    (0.0, "Bajo", "low"),
)

_FOLLOWUP_DONE = {"completed", "closed"}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default  # descarta NaN


def risk_band(probability: float) -> dict[str, str]:
    for threshold, label, tone in _LEVELS:
        if probability >= threshold:
            return {"label": label, "tone": tone}
    return {"label": "Bajo", "tone": "low"}


def _format_cop(value: float) -> str:
    return "$" + f"{int(round(value)):,}".replace(",", ".")


def _academic_stats(signals: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in signals if isinstance(row, Mapping)]
    grades = [_number(row.get("grade")) for row in rows if row.get("grade") is not None]
    attendance = [
        _number(row.get("attendance_pct"))
        for row in rows
        if row.get("attendance_pct") is not None
    ]
    return {
        "courses": len(rows),
        "critical_courses": sum(1 for grade in grades if grade < PASSING_GRADE),
        "average_grade": sum(grades) / len(grades) if grades else None,
        "average_attendance": sum(attendance) / len(attendance) if attendance else None,
    }


def _factors(
    probability: float,
    finance: Mapping[str, Any],
    wellbeing: Mapping[str, Any],
    stats: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    arrears = int(_number(finance.get("arrears_months")))
    balance = _number(finance.get("arrears_balance_cop"))
    if arrears > 0:
        months = f"{arrears} {'mes' if arrears == 1 else 'meses'}"
        candidates.append(
            {
                "label": "Morosidad financiera activa",
                "detail": f"{months} · {_format_cop(balance)}" if balance > 0 else months,
                "area": "financiero",
                "impact": min(100, 40 + arrears * 15),
                "action": "financial_aid_review",
            }
        )
    critical = int(stats["critical_courses"])
    if critical > 0:
        candidates.append(
            {
                "label": "Bajo rendimiento en asignaturas críticas",
                "detail": f"{critical} {'asignatura' if critical == 1 else 'asignaturas'}",
                "area": "académico",
                "impact": min(100, 35 + critical * 18),
                "action": "tutoring_review",
            }
        )
    attendance = stats["average_attendance"]
    if attendance is not None and attendance < ATTENDANCE_THRESHOLD:
        candidates.append(
            {
                "label": "Inasistencia recurrente",
                "detail": f"{round(attendance)}% asistencia",
                "area": "académico",
                "impact": min(100, round(30 + (ATTENDANCE_THRESHOLD - attendance) * 2)),
                "action": "academic_advisor_review",
            }
        )
    sessions = int(_number(wellbeing.get("sessions")))
    if probability >= RISK_MEDIUM_THRESHOLD and (sessions == 0 or not wellbeing.get("attended")):
        candidates.append(
            {
                "label": "Uso insuficiente de servicios de acompañamiento",
                "detail": "sin asistencia registrada" if sessions == 0 else "sesiones sin asistir",
                "area": "bienestar",
                "impact": 35 if probability < RISK_HIGH_THRESHOLD else 50,
                "action": "wellbeing_review",
            }
        )
    if not candidates and probability >= RISK_HIGH_THRESHOLD:
        candidates.append(
            {
                "label": "Combinación de señales de riesgo de abandono",
                "detail": "sin un factor dominante",
                "area": "general",
                "impact": round(probability * 100),
                "action": "academic_advisor_review",
            }
        )
    candidates.sort(key=lambda item: item["impact"], reverse=True)
    return candidates[:MAX_FACTORS]


def _actions(
    probability: float,
    factors: list[dict[str, Any]],
    proposed: Iterable[Any],
    followups: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ordered: list[str] = []
    if probability >= RISK_HIGH_THRESHOLD:
        ordered.append(CONTACT_ACTION)
    for factor in factors:
        if factor["action"] not in ordered:
            ordered.append(factor["action"])
    for code in proposed or []:
        if isinstance(code, str) and code in ACTION_LABELS and code not in ordered:
            ordered.append(code)
    if not ordered and probability >= RISK_MEDIUM_THRESHOLD:
        ordered.append("academic_advisor_review")

    state_by_action: dict[str, str] = {}
    for followup in followups:
        code = followup.get("action")
        status = "done" if followup.get("status") in _FOLLOWUP_DONE else "in_progress"
        if isinstance(code, str) and state_by_action.get(code) != "done":
            state_by_action[code] = status
    if followups:
        state_by_action.setdefault(CONTACT_ACTION, "done")

    return [
        {
            "code": code,
            "label": ACTION_LABELS[code],
            "state": state_by_action.get(code, "pending"),
            "assignable": code != CONTACT_ACTION,
        }
        for code in ordered[:MAX_ACTIONS]
    ]


def _priority(probability: float, factors: list[dict[str, Any]], open_followups: int) -> dict[str, Any]:
    top = [factor["impact"] for factor in factors[:3]]
    severity = sum(top) / len(top) if top else 0
    score = probability * 70 + severity * 0.3
    if open_followups:
        score -= 10  # ya existe una intervención en curso
    score = int(max(0, min(100, round(score))))
    if score >= 75:
        label, tone = "Inmediata", "critical"
    elif score >= 55:
        label, tone = "Alta", "high"
    elif score >= 30:
        label, tone = "Programada", "medium"
    else:
        label, tone = "Monitoreo", "low"
    return {"score": score, "label": label, "tone": tone}


def _status(
    followups: list[Mapping[str, Any]], review_status: str | None
) -> dict[str, str]:
    active = [item for item in followups if item.get("status") not in _FOLLOWUP_DONE]
    if active:
        return {"label": "En seguimiento", "tone": "medium"}
    if followups:
        return {"label": "Intervención completada", "tone": "low"}
    if review_status == "pending_approval":
        return {"label": "Plan por validar", "tone": "high"}
    if review_status == "rejected":
        return {"label": "Plan descartado", "tone": "neutral"}
    return {"label": "Sin intervención", "tone": "neutral"}


_TIMELINE_STATUS = {"open": "Abierta", "in_progress": "En curso", "completed": "Completada", "closed": "Cerrada"}


def _timeline(followups: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    events = sorted(
        followups,
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    timeline = []
    for item in events[:MAX_TIMELINE]:
        code = item.get("action")
        label = ACTION_LABELS.get(code) if isinstance(code, str) else None
        timeline.append(
            {
                "date": str(item.get("updated_at") or item.get("created_at") or "")[:10],
                "label": label or str(item.get("action_label") or "Intervención")[:60],
                "status": _TIMELINE_STATUS.get(str(item.get("status")), "Registrada"),
                "owner": str(item.get("owner") or "")[:40],
            }
        )
    return timeline


_LEVEL_PHRASE = {
    "Crítico": "Riesgo crítico",
    "Alto": "Riesgo alto",
    "Medio": "Riesgo medio",
    "Bajo": "Riesgo bajo",
}


_AREA_PHRASE = {
    "académico": "académicas",
    "financiero": "financieras",
    "bienestar": "de bienestar",
}


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " y " + parts[-1]


def _preliminary_explanation(level: str, factors: list[dict[str, Any]]) -> str:
    if not factors:
        return f"{_LEVEL_PHRASE[level]}: sin señales académicas, financieras ni de bienestar relevantes en el periodo."
    # Solo nombra las áreas: las cifras ya aparecen en la evidencia, no se repiten.
    areas: list[str] = []
    for factor in factors:
        area = _AREA_PHRASE.get(factor["area"])
        if area and area not in areas:
            areas.append(area)
    if not areas:
        return f"{_LEVEL_PHRASE[level]} por una combinación de señales sin un factor dominante."
    if len(areas) == 1:
        return f"{_LEVEL_PHRASE[level]} concentrado en señales {areas[0]}."
    return f"{_LEVEL_PHRASE[level]} por la coincidencia de señales {_join(areas)}."


def _clean_explanation(text: str) -> str:
    # Los códigos internos de acción nunca se muestran; se reemplazan por su etiqueta.
    for code, label in {**FOLLOWUP_ACTION_LABELS, **ACTION_LABELS}.items():
        text = text.replace(code, label.lower())
    words = " ".join(text.split()).split(" ")
    if len(words) > MAX_WORDS:
        return " ".join(words[:MAX_WORDS]).rstrip(" ,;:.") + "…"
    return " ".join(words)


def _explanation(
    level: str, factors: list[dict[str, Any]], recommendation: Mapping[str, Any]
) -> dict[str, str]:
    summary = recommendation.get("summary")
    if isinstance(summary, str) and summary.strip():
        return {"text": _clean_explanation(summary), "source": "consolidated"}
    return {"text": _preliminary_explanation(level, factors), "source": "preliminary"}


def build_executive_view(
    profile: Mapping[str, Any],
    review: Mapping[str, Any] | None = None,
    followups: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Construye la vista ejecutiva de un estudiante con tamaño acotado."""
    student = profile.get("student") or {}
    probability = max(0.0, min(1.0, _number(student.get("model_probability"))))
    finance = profile.get("finance") or {}
    wellbeing = profile.get("wellbeing") or {}
    stats = _academic_stats(profile.get("academic_signals") or [])
    followup_list = [item for item in followups if isinstance(item, Mapping)]
    open_followups = sum(1 for item in followup_list if item.get("status") not in _FOLLOWUP_DONE)

    recommendation = (review or {}).get("recommendation") or {}
    proposed = recommendation.get("proposed_actions") or []

    factors = _factors(probability, finance, wellbeing, stats)
    band = risk_band(probability)
    view = {
        "risk": {**band, "probability_pct": round(probability * 100, 1)},
        "explanation": _explanation(band["label"], factors, recommendation),
        "priority": _priority(probability, factors, open_followups),
        "status": _status(followup_list, (review or {}).get("status")),
        "factors": [
            {
                "label": factor["label"][:MAX_FACTOR_CHARS],
                "detail": factor["detail"],
                "area": factor["area"],
                "impact": int(factor["impact"]),
            }
            for factor in factors
        ],
        "actions": _actions(probability, factors, proposed, followup_list),
        "timeline": _timeline(followup_list),
        "analyzed": bool(review),
        "pending_validation": (review or {}).get("status") == "pending_approval",
    }
    return view


def executive_word_count(view: Mapping[str, Any]) -> int:
    """Palabras visibles fuera del diagnóstico (etiquetas, factores, acciones, eventos)."""
    parts: list[str] = [
        view["risk"]["label"],
        view["priority"]["label"],
        view["status"]["label"],
    ]
    for factor in view["factors"]:
        parts += [factor["label"], factor["detail"]]
    parts += [action["label"] for action in view["actions"]]
    for event in view["timeline"]:
        parts += [event["label"], event["status"], event["owner"]]
    return sum(len(part.split()) for part in parts)
