import json
from uuid import uuid4

import pytest

from src.persistence.sql_repository import AzureSqlRepository


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


def test_repository_requires_explicit_connection():
    with pytest.raises(ValueError, match="explicit"):
        AzureSqlRepository(connection=None)


def test_apply_schema_runs_batches_and_registers_version_once(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)
    fake_connection.results = [(["Version"], [])]

    assert repo.apply_schema() is True

    assert any("CREATE TABLE dbo.SchemaVersion" in sql for sql in fake_connection.executed_sql)
    assert not any(sql.strip().upper() == "GO" for sql in fake_connection.executed_sql)
    assert fake_connection.executed_sql[-1].startswith("INSERT INTO dbo.SchemaVersion")
    assert fake_connection.commits == 1

    fake_connection.results = [(["Version"], [(1,)])]
    fake_connection.executed_sql.clear()
    assert repo.apply_schema() is False
    assert not any(sql.startswith("INSERT INTO dbo.SchemaVersion") for sql in fake_connection.executed_sql)


def test_transaction_rolls_back_on_error(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)
    with pytest.raises(RuntimeError):
        with repo.transaction():
            raise RuntimeError("boom")
    assert fake_connection.rollbacks == 1
    assert fake_connection.commits == 0


def test_reads_return_dicts_and_parse_json_columns(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)
    fake_connection.results = [
        (
            ["ReviewId", "Status", "RecommendationsJson", "LimitationsJson"],
            [("r-1", "pending_approval", '{"proposed_actions":["tutoria"]}', '{"limitations":[]}')],
        ),
        (["ReviewId"], []),
    ]

    review = repo.get_review_proposal("r-1")
    assert review["RecommendationsJson"] == {"proposed_actions": ["tutoria"]}
    assert repo.get_human_decision("r-1") is None


def test_list_filters_are_validated_and_parameterised(fake_connection):
    repo = AzureSqlRepository(connection=fake_connection)
    with pytest.raises(ValueError):
        repo.list_predictions(risk_level="Peligro")
    with pytest.raises(ValueError):
        repo.list_review_proposals(status="otro")

    repo.list_interventions(status="open", limit=10_000)
    sql = fake_connection.executed_sql[-1]
    assert "TOP (1000)" in sql and "Status = ?" in sql
    assert fake_connection.executed_params[-1] == ("open",)
