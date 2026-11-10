import json
from uuid import uuid4

import pytest

from src.persistence.sql_repository import AzureSqlRepository, FakeConnection


@pytest.fixture
def fake_connection():
    return FakeConnection()


def test_repository_can_record_model_release_and_prediction(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)
    release = {
        "model_name": "sat_fumc_lightgbm",
        "model_version": "v1.2.0",
        "dataset_version": "dset-123",
        "code_version_sha256": "a" * 64,
        "decision_threshold": 0.42,
        "promotion_status": "blocked",
        "metrics": {
            "test_recall": 0.79,
            "test_precision": 0.36,
            "test_auc_roc": 0.67,
        },
    }

    repo.record_model_release(**release)
    repo.record_prediction(
        prediction_id=str(uuid4()),
        snapshot_id=str(uuid4()),
        model_name="sat_fumc_lightgbm",
        model_version="v1.2.0",
        probability=0.81,
        risk_level="Alto",
        alert_raised=True,
        inference_source="azure_ml",
    )

    assert fake_connection.executed_sql[0].startswith("INSERT INTO dbo.ModelRelease")
    assert fake_connection.executed_sql[1].startswith("INSERT INTO dbo.Prediction")


def test_repository_rejects_invalid_threshold_and_risk_level(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)

    with pytest.raises(ValueError, match="threshold"):
        repo.record_model_release(
            model_name="sat_fumc_lightgbm",
            model_version="v1.2.0",
            dataset_version="dset-123",
            code_version_sha256="a" * 64,
            decision_threshold=1.5,
            promotion_status="approved",
            metrics={"test_recall": 0.8},
        )

    with pytest.raises(ValueError, match="risk_level"):
        repo.record_prediction(
            prediction_id=str(uuid4()),
            snapshot_id=str(uuid4()),
            model_name="sat_fumc_lightgbm",
            model_version="v1.2.0",
            probability=0.5,
            risk_level="Peligro",
            alert_raised=False,
            inference_source="synthetic_fixture",
        )


def test_repository_schema_is_loaded_from_sql_file(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection, schema_path="azure/agent_platform/infra/sql_schema.sql")
    sql = repo.schema_sql()
    assert "CREATE TABLE dbo.ModelRelease" in sql
    assert "CREATE TABLE dbo.Prediction" in sql
    assert "CREATE TABLE dbo.AgentExecution" in sql


def test_repository_uses_json_payload_for_metrics_and_review_payloads(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)
    report = {"risk": "high", "notes": ["student flagged"]}

    repo.record_review_proposal(
        review_id="review-1",
        prediction_id=str(uuid4()),
        status="pending_approval",
        summary="Review pending",
        recommendations=report,
        limitations={"model_limit": "synthetic only"},
    )

    payload_sql = fake_connection.executed_sql[-1]
    payload_params = fake_connection.executed_params[-1]
    assert "JSON" in payload_sql or "ISJSON" in payload_sql or "RecommendationsJson" in payload_sql
    assert any(json.dumps(report, ensure_ascii=False, separators=(",", ":")) == str(value) for value in payload_params)
