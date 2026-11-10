import pandas as pd

from src.ml.feedback_loop import append_feedback_event, build_feedback_dataset, summarize_feedback


def test_feedback_loop_records_and_builds_training_dataset(tmp_path):
    feedback_path = tmp_path / "feedback.jsonl"

    event = append_feedback_event(
        {
            "student_id": "student-101",
            "periodo_id": "2025-1",
            "model_name": "LightGBM",
            "model_probability": 0.72,
            "decision": "confirmed_risk",
            "feedback_source": "human_review",
            "reviewer_id": "analyst-1",
            "note": "Se confirmó riesgo real por reprobación y crisis financiera.",
            "agent": "risk-review-agent",
            "recommended_action": "tutoring_review",
        },
        path=feedback_path,
    )

    assert event["decision"] == "confirmed_risk"

    summary = summarize_feedback(feedback_path)
    assert summary["total_events"] == 1
    assert summary["by_decision"]["confirmed_risk"] == 1

    # A reviewer decision alone is not an observed dropout outcome.
    assert build_feedback_dataset(feedback_path, raw_dir=tmp_path).empty
    pd.DataFrame(
        {
            "id_estudiante_anon": ["student-101"],
            "periodo_id": ["2025-1"],
            "target_desercion": [0],
        }
    ).to_parquet(tmp_path / "target_trazabilidad.parquet", index=False)

    dataset = build_feedback_dataset(feedback_path, raw_dir=tmp_path)
    assert list(dataset.columns) == [
        "student_id",
        "periodo_id",
        "model_name",
        "model_probability",
        "decision",
        "label",
        "recorded_at",
    ]
    assert dataset["label"].tolist() == [0]
    assert summary["dataset_rows"] == 0
