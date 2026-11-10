from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
FEEDBACK_DIR = ROOT_DIR / "data" / "feedback"
FEEDBACK_FILE = FEEDBACK_DIR / "model_feedback.jsonl"

ALLOWED_DECISIONS = {
    "confirmed_risk",
    "rejected_risk",
    "needs_review",
    "approved_action",
    "rejected_action",
    "manual_override",
}


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("El feedback debe ser un objeto JSON.")

    student_id = record.get("student_id")
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id es obligatorio.")

    decision = record.get("decision")
    if not isinstance(decision, str) or decision.strip() not in ALLOWED_DECISIONS:
        raise ValueError(
            "decision inválida. Valores esperados: "
            + ", ".join(sorted(ALLOWED_DECISIONS))
        )

    model_name = record.get("model_name") or record.get("model") or "unknown-model"
    probability = record.get("model_probability")
    if probability is not None:
        try:
            probability = float(probability)
        except (TypeError, ValueError) as exc:
            raise ValueError("model_probability debe ser número entre 0 y 1.") from exc
        if not 0.0 <= probability <= 1.0:
            raise ValueError("model_probability debe estar entre 0 y 1.")

    normalized = {
        "student_id": student_id.strip(),
        "periodo_id": record.get("periodo_id") or "unknown-period",
        "model_name": str(model_name).strip(),
        "model_probability": probability,
        "decision": decision.strip(),
        "feedback_source": record.get("feedback_source") or "manual_review",
        "reviewer_id": record.get("reviewer_id"),
        "note": record.get("note") or "",
        "agent": record.get("agent") or "unknown-agent",
        "recommended_action": record.get("recommended_action") or "",
        "recorded_at": record.get("recorded_at") or datetime.now(timezone.utc).isoformat(),
    }
    return normalized


def _feedback_path(path: str | Path | None = None) -> Path:
    target = Path(path) if path is not None else FEEDBACK_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def append_feedback_event(record: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    normalized = _normalize_record(record)
    target = _feedback_path(path)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")
    return normalized


def load_feedback_events(path: str | Path | None = None) -> list[dict[str, Any]]:
    target = _feedback_path(path)
    if not target.exists():
        return []

    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _label_from_decision(decision: str) -> int | None:
    """Reviewer workflow decisions are not ground-truth dropout outcomes."""
    return None


def build_feedback_dataset(
    path: str | Path | None = None,
    raw_dir: str | Path | None = None,
) -> pd.DataFrame:
    records = load_feedback_events(path)
    if not records:
        return pd.DataFrame(
            columns=[
                "student_id",
                "periodo_id",
                "model_name",
                "model_probability",
                "decision",
                "label",
                "recorded_at",
            ]
        )

    frame = pd.DataFrame(records)
    columns = [
        "student_id",
        "periodo_id",
        "model_name",
        "model_probability",
        "decision",
        "label",
        "recorded_at",
    ]
    if raw_dir is not None:
        target_path = Path(raw_dir) / "target_trazabilidad.parquet"
    else:
        target_path = ROOT_DIR / "data" / "raw" / "target_trazabilidad.parquet"

    if not target_path.exists():
        return pd.DataFrame(columns=columns)

    target_df = pd.read_parquet(target_path)
    required_target_columns = {
        "id_estudiante_anon",
        "periodo_id",
        "target_desercion",
    }
    if not required_target_columns.issubset(target_df.columns):
        return pd.DataFrame(columns=columns)
    target = target_df[
        ["id_estudiante_anon", "periodo_id", "target_desercion"]
    ].rename(columns={"id_estudiante_anon": "student_id"})
    if target["target_desercion"].isna().any() or not target[
        "target_desercion"
    ].isin([0, 1]).all():
        raise ValueError("El target institucional debe ser binario y no nulo.")

    merged = frame.merge(
        target,
        on=["student_id", "periodo_id"],
        how="inner",
        validate="many_to_one",
    )
    merged["label"] = merged.pop("target_desercion").astype(int)
    return merged[columns]


def summarize_feedback(path: str | Path | None = None) -> dict[str, Any]:
    records = load_feedback_events(path)
    total = len(records)
    by_decision: dict[str, int] = {}
    for record in records:
        decision = record.get("decision", "unknown")
        by_decision[decision] = by_decision.get(decision, 0) + 1
    recent = records[-5:]
    return {
        "total_events": total,
        "by_decision": by_decision,
        "most_recent": recent,
        "dataset_rows": len(build_feedback_dataset(path=path)),
    }
