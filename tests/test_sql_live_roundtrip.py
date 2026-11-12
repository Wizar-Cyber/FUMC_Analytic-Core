"""Roundtrip real contra Azure SQL. Se omite sin SAT_SQL_SERVER / SAT_SQL_DATABASE (usa az login o Managed Identity)."""
import os
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not (os.environ.get("SAT_SQL_SERVER") and os.environ.get("SAT_SQL_DATABASE")),
    reason="requiere SAT_SQL_SERVER y SAT_SQL_DATABASE",
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azure" / "agent_platform"))


def _cleanup(repo, review_id, model_name, student_id):
    cursor_sql = [
        "DELETE FROM dbo.Intervention WHERE HumanDecisionId IN (SELECT HumanDecisionId FROM dbo.HumanDecision WHERE ReviewId = ?)",
        "DELETE FROM dbo.HumanDecision WHERE ReviewId = ?",
        "DELETE FROM dbo.ReviewProposal WHERE ReviewId = ?",
    ]
    with repo.transaction():
        for sql in cursor_sql:
            repo._execute(sql, (review_id,))
        repo._execute("DELETE FROM dbo.Prediction WHERE ModelName = ?", (model_name,))
        repo._execute("DELETE FROM dbo.ModelRelease WHERE ModelName = ?", (model_name,))
        repo._execute("DELETE FROM dbo.StudentSnapshot WHERE PseudonymizedStudentId = ?", (student_id,))
        repo._execute("DELETE FROM dbo.AuditEvent WHERE EntityId = ?", (review_id,))


def test_review_lifecycle_roundtrip_in_azure_sql(monkeypatch):
    from sat_agents import audit_sql
    from src.persistence.sql_repository import AzureSqlRepository, connect_entra

    suffix = uuid.uuid4().hex[:8]
    review_id = f"live-test-{suffix}"
    student_id = f"ST-LIVE-{suffix}"
    model_name = f"LIVE_TEST_MODEL_{suffix}"
    monkeypatch.setenv("SQL_SERVER", os.environ["SAT_SQL_SERVER"])
    monkeypatch.setenv("SQL_DATABASE", os.environ["SAT_SQL_DATABASE"])
    monkeypatch.setenv("SQL_MODEL_NAME", model_name)
    monkeypatch.setenv("SQL_MODEL_VERSION", "test")

    repo = AzureSqlRepository(connect_entra(os.environ["SAT_SQL_SERVER"], os.environ["SAT_SQL_DATABASE"]))
    try:
        proposal = {
            "review_id": review_id,
            "student_id": student_id,
            "model_probability": 0.72,
            "recommendation": {
                "summary": "Resumen de prueba",
                "proposed_actions": ["academic_advisor_review"],
                "limitations": ["datos sintéticos"],
            },
        }
        audit_sql._write_pending_review(proposal)
        audit_sql._write_pending_review(proposal)  # idempotente

        stored = repo.get_review_proposal(review_id)
        assert stored["Status"] == "pending_approval"
        assert stored["RecommendationsJson"]["proposed_actions"] == ["academic_advisor_review"]
        prediction = repo.get_prediction(str(stored["PredictionId"]))
        assert prediction["RiskLevel"] == "Alto" and float(prediction["Probability"]) == pytest.approx(0.72)

        approval = {"decision": "approved", "note": "ok", "approved_action": None}
        followup = {"followup_id": f"f-{suffix}", "action": "academic_advisor_review", "student_id": student_id}
        reviewer = str(uuid.uuid4())
        audit_sql._write_decision(review_id, reviewer, approval, followup)
        audit_sql._write_decision(review_id, reviewer, approval, followup)  # idempotente

        decision = repo.get_human_decision(review_id)
        assert decision["Decision"] == "approved"
        assert repo.get_review_proposal(review_id)["Status"] == "approved"
        interventions = [
            row for row in repo.list_interventions(limit=1000)
            if str(row["HumanDecisionId"]).lower() == str(decision["HumanDecisionId"]).lower()
        ]
        assert len(interventions) == 1 and interventions[0]["Status"] == "open"
        events = repo.list_audit_events(entity_type="review", entity_id=review_id)
        assert {event["ActionCode"] for event in events} >= {"review.proposed", "review.approved"}
    finally:
        _cleanup(repo, review_id, model_name, student_id)
        repo.connection.close()
