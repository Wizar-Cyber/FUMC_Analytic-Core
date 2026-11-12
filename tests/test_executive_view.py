"""Vista ejecutiva: consolidación multiagente acotada y estable a escala."""

import json
import random
import re
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))

from sat_agents.contracts import (  # noqa: E402
    parse_analysis_response,
    parse_recommendation_response,
    sanitize_analysis_text,
    sanitize_recommendation_text,
)
from sat_agents.executive import (  # noqa: E402
    MAX_ACTIONS,
    MAX_FACTORS,
    MAX_LAYOUT_WORDS,
    MAX_TIMELINE,
    MAX_WORDS,
    build_executive_view,
    executive_word_count,
)
from sat_agents.policy import (  # noqa: E402
    ALLOWED_FOLLOWUP_ACTIONS,
    MAX_AGENT_OBSERVATIONS,
    MAX_SYNTHESIS_WORDS,
)

# Nada de esto debe llegar a la pantalla del directivo.
_TECHNICAL = re.compile(
    r"_review|attended|sessions|token|prompt|LLM|GPT|agente|modelo|arrears|"
    r"probability|feature|true|false|null|None",
    re.IGNORECASE,
)


def _profile(rng: random.Random, probability: float | None = None) -> dict:
    courses = rng.randint(3, 7)
    return {
        "student": {"model_probability": probability if probability is not None else rng.random()},
        "finance": {
            "arrears_months": rng.choice([0, 0, 0, 1, 2, 3, 6]),
            "arrears_balance_cop": rng.choice([0, 450_000, 1_347_388, 3_900_000]),
        },
        "wellbeing": {"sessions": rng.randint(0, 3), "attended": rng.random() < 0.4},
        "academic_signals": [
            {
                "course_code": f"CUR{index:03d}",
                "grade": round(rng.uniform(0.5, 5.0), 1),
                "attendance_pct": round(rng.uniform(30, 100), 0),
            }
            for index in range(courses)
        ],
    }


def _followups(rng: random.Random) -> list[dict]:
    return [
        {
            "action": rng.choice(sorted(ALLOWED_FOLLOWUP_ACTIONS)),
            "action_label": "Revisión",
            "status": rng.choice(["open", "in_progress", "completed"]),
            "owner": "Equipo de permanencia",
            "created_at": f"2026-10-{day:02d}T10:00:00+00:00",
            "updated_at": f"2026-10-{day:02d}T12:00:00+00:00",
        }
        for day in range(1, rng.randint(0, 9) + 1)
    ]


def _visible_strings(view: dict) -> list[str]:
    strings = [view["risk"]["label"], view["priority"]["label"], view["status"]["label"], view["explanation"]["text"]]
    for factor in view["factors"]:
        strings += [factor["label"], factor["detail"]]
    strings += [action["label"] for action in view["actions"]]
    for event in view["timeline"]:
        strings += [event["label"], event["status"]]
    return strings


def test_example_case_matches_institutional_format():
    profile = {
        "student": {"model_probability": 0.84},
        "finance": {"arrears_months": 2, "arrears_balance_cop": 1_347_388},
        "wellbeing": {"sessions": 0, "attended": False},
        "academic_signals": [
            {"course_code": "MAT101", "grade": 2.1, "attendance_pct": 48},
            {"course_code": "FIS101", "grade": 2.6, "attendance_pct": 52},
            {"course_code": "PRG101", "grade": 2.8, "attendance_pct": 50},
            {"course_code": "HUM101", "grade": 3.9, "attendance_pct": 54},
        ],
    }
    review = {
        "status": "pending_approval",
        "recommendation": {
            "summary": "Riesgo crítico asociado a nota inferior a 3,0 en 3 asignaturas, asistencia del 51% "
            "y mora de 2 meses; prioridad: financial_aid_review y tutoría.",
            "proposed_actions": ["wellbeing_review", "financial_aid_review"],
        },
    }
    view = build_executive_view(
        profile,
        review,
        [{"action": "tutoring_review", "status": "open", "owner": "Tutorías", "created_at": "2026-11-01"}],
    )

    assert view["risk"] == {"label": "Crítico", "tone": "critical", "probability_pct": 84.0}
    assert view["status"]["label"] == "En seguimiento"
    assert view["priority"]["label"] in {"Inmediata", "Alta"}
    labels = [factor["label"] for factor in view["factors"]]
    assert labels[0] == "Bajo rendimiento en asignaturas críticas"
    assert set(labels) == {
        "Bajo rendimiento en asignaturas críticas",
        "Inasistencia recurrente",
        "Morosidad financiera activa",
        "Uso insuficiente de servicios de acompañamiento",
    }
    impacts = [factor["impact"] for factor in view["factors"]]
    assert impacts == sorted(impacts, reverse=True)
    actions = {action["label"]: action["state"] for action in view["actions"]}
    assert actions["Contacto desde permanencia"] == "done"
    assert actions["Tutoría en asignaturas críticas"] == "in_progress"
    assert actions["Evaluación de apoyo financiero"] == "pending"
    details = {factor["label"]: factor["detail"] for factor in view["factors"]}
    assert details["Morosidad financiera activa"] == "2 meses · $1.347.388"
    assert details["Bajo rendimiento en asignaturas críticas"] == "3 asignaturas"
    assert details["Inasistencia recurrente"] == "51% asistencia"
    # Un único diagnóstico consolidado, sin códigos internos.
    assert view["explanation"]["source"] == "consolidated"
    assert view["explanation"]["text"].startswith("Riesgo crítico asociado")
    assert "financial_aid_review" not in view["explanation"]["text"]
    assert "indicators" not in view


def test_preliminary_explanation_without_analysis():
    profile = {
        "student": {"model_probability": 0.66},
        "finance": {"arrears_months": 3, "arrears_balance_cop": 2_000_000},
        "wellbeing": {"sessions": 1, "attended": True},
        "academic_signals": [{"course_code": "MAT101", "grade": 2.0, "attendance_pct": 90}],
    }
    view = build_executive_view(profile)
    assert view["explanation"] == {
        "text": "Riesgo alto por la coincidencia de señales financieras y académicas.",
        "source": "preliminary",
    }


def test_low_risk_case_is_quiet():
    profile = {
        "student": {"model_probability": 0.08},
        "finance": {"arrears_months": 0, "arrears_balance_cop": 0},
        "wellbeing": {"sessions": 0, "attended": False},
        "academic_signals": [{"course_code": "MAT101", "grade": 4.2, "attendance_pct": 95}],
    }
    view = build_executive_view(profile)
    assert view["risk"]["label"] == "Bajo"
    assert view["factors"] == []
    assert view["actions"] == []
    assert view["priority"]["label"] == "Monitoreo"
    assert view["explanation"]["source"] == "preliminary"
    assert "sin señales" in view["explanation"]["text"]


@pytest.mark.parametrize("population", [5_000, 10_000, 25_000, 50_000, 100_000])
def test_executive_view_stays_bounded_at_scale(population):
    rng = random.Random(population)
    started = time.perf_counter()
    max_words = max_explanation = max_bytes = 0
    for _ in range(population):
        review = (
            {
                "status": "pending_approval",
                "recommendation": {
                    "summary": "explicación " * rng.randint(20, 400),
                    "proposed_actions": rng.sample(sorted(ALLOWED_FOLLOWUP_ACTIONS), 4),
                },
            }
            if rng.random() < 0.5
            else None
        )
        view = build_executive_view(_profile(rng), review, _followups(rng))
        assert len(view["factors"]) <= MAX_FACTORS
        assert len(view["actions"]) <= MAX_ACTIONS
        assert len(view["timeline"]) <= MAX_TIMELINE
        max_words = max(max_words, executive_word_count(view))
        max_explanation = max(max_explanation, len(view["explanation"]["text"].split()))
        max_bytes = max(max_bytes, len(json.dumps(view, ensure_ascii=False)))
    elapsed = time.perf_counter() - started

    # El volumen de texto por caso no crece con la población.
    assert max_words <= MAX_LAYOUT_WORDS
    assert max_explanation <= MAX_WORDS
    assert max_bytes < 6_000
    # Consolidar toda la cohorte es barato (no depende de llamadas al LLM).
    assert elapsed / population < 0.002


def test_visible_text_has_no_technical_vocabulary():
    rng = random.Random(7)
    for _ in range(2_000):
        view = build_executive_view(_profile(rng), None, _followups(rng))
        for text in _visible_strings(view):
            assert not _TECHNICAL.search(text), text


def test_agent_output_is_capped_before_consolidation():
    verbose = json.dumps(
        {
            "summary": "palabra " * 400,
            "observations": [f"hallazgo {index} " + "detalle " * 80 for index in range(8)] + ["hallazgo 0 " + "detalle " * 80],
            "limitations": ["a", "b", "c"],
            "citation_ids": [],
        }
    )
    parsed = parse_analysis_response(sanitize_analysis_text(verbose))
    assert len(parsed["observations"]) <= MAX_AGENT_OBSERVATIONS
    assert all(len(item) <= 160 for item in parsed["observations"])
    assert len(parsed["summary"]) <= 240
    assert len(parsed["limitations"]) <= 1

    synthesis = json.dumps(
        {"summary": "palabra " * 600, "proposed_actions": ["tutoring_review"], "limitations": ["x", "y"]}
    )
    recommendation = parse_recommendation_response(sanitize_recommendation_text(synthesis))
    assert len(recommendation["summary"].split()) <= MAX_SYNTHESIS_WORDS
    assert len(recommendation["limitations"]) <= 1
