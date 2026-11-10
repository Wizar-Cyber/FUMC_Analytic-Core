from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FakeCursor:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> "FakeCursor":
        self.connection.executed_sql.append(sql)
        self.connection.executed_params.append(params)
        self.connection.last_result = {"sql": sql, "params": list(params)}
        return self

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FakeConnection:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.executed_params: list[tuple[Any, ...]] = []
        self.last_result: dict[str, Any] | None = None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        return FakeCursor(self).execute(sql, params)

    def commit(self) -> None:
        return None


class AzureSqlRepository:
    """Minimal Azure SQL repository contract for the SAT-FUMC platform.

    This adapter intentionally keeps the database contract explicit and testable
    without requiring a live Azure SQL connection at import time. The repository
    accepts either an active DB-API compatible connection or a fake connection for
    unit tests.
    """

    RISK_LEVELS = {"Bajo", "Medio", "Alto", "Crítico"}
    MODEL_RELEASE_STATUS = {"approved", "blocked", "pending_review", "rejected"}
    REVIEW_STATUS = {"pending_approval", "approved", "edited", "rejected"}
    AGENT_STATUS = {"queued", "running", "succeeded", "failed", "timed_out"}
    INTERVENTION_STATUS = {"open", "in_progress", "completed", "cancelled"}

    def __init__(self, connection: Any | None = None, schema_path: str | Path | None = None) -> None:
        self.connection = connection or FakeConnection()
        root_dir = Path(__file__).resolve().parents[2]
        if schema_path is None:
            schema_path = root_dir / "azure" / "agent_platform" / "infra" / "sql_schema.sql"
        self._schema_path = Path(schema_path)
        if not self._schema_path.is_absolute():
            self._schema_path = root_dir / self._schema_path

    def schema_sql(self) -> str:
        if not self._schema_path.exists():
            raise FileNotFoundError(f"SQL schema file not found: {self._schema_path}")
        return self._schema_path.read_text(encoding="utf-8")

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        connection = self.connection
        if hasattr(connection, "execute") and not hasattr(connection, "cursor"):
            return connection.execute(sql, params)
        cursor = connection.cursor()
        return cursor.execute(sql, params)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _validate_probability(value: float, field_name: str) -> float:
        if not 0 <= value <= 1:
            raise ValueError(f"{field_name} must be between 0 and 1.")
        return float(value)

    @staticmethod
    def _validate_threshold(value: float) -> float:
        value = AzureSqlRepository._validate_probability(value, "decision_threshold")
        return value

    def record_model_release(
        self,
        *,
        model_name: str,
        model_version: str,
        dataset_version: str,
        code_version_sha256: str,
        decision_threshold: float,
        promotion_status: str,
        metrics: dict[str, Any],
    ) -> None:
        self._validate_threshold(decision_threshold)
        if promotion_status not in self.MODEL_RELEASE_STATUS:
            raise ValueError(f"promotion_status must be one of {sorted(self.MODEL_RELEASE_STATUS)}.")
        sql = (
            "INSERT INTO dbo.ModelRelease "
            "(ModelName, ModelVersion, DatasetVersion, CodeVersionSha256, DecisionThreshold, PromotionStatus, MetricsJson) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        self._execute(
            sql,
            (
                model_name,
                model_version,
                dataset_version,
                code_version_sha256,
                float(decision_threshold),
                promotion_status,
                self._json(metrics),
            ),
        )

    def record_prediction(
        self,
        *,
        prediction_id: str,
        snapshot_id: str,
        model_name: str,
        model_version: str,
        probability: float,
        risk_level: str,
        alert_raised: bool,
        inference_source: str,
    ) -> None:
        self._validate_probability(probability, "probability")
        if risk_level not in self.RISK_LEVELS:
            raise ValueError(f"risk_level must be one of {sorted(self.RISK_LEVELS)}.")
        sql = (
            "INSERT INTO dbo.Prediction "
            "(PredictionId, SnapshotId, ModelName, ModelVersion, Probability, RiskLevel, AlertRaised, InferenceSource, CreatedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME())"
        )
        self._execute(
            sql,
            (
                prediction_id,
                snapshot_id,
                model_name,
                model_version,
                float(probability),
                risk_level,
                bool(alert_raised),
                inference_source,
            ),
        )

    def record_agent_execution(
        self,
        *,
        agent_execution_id: str,
        prediction_id: str,
        agent_name: str,
        attempt_number: int,
        status: str,
        prompt_version: str,
        deployment_name: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
        output_json: dict[str, Any] | None = None,
        error_code: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        if status not in self.AGENT_STATUS:
            raise ValueError(f"status must be one of {sorted(self.AGENT_STATUS)}.")
        sql = (
            "INSERT INTO dbo.AgentExecution "
            "(AgentExecutionId, PredictionId, AgentName, AttemptNumber, Status, PromptVersion, DeploymentName, InputTokens, OutputTokens, DurationMs, OutputJson, ErrorCode, StartedAt, FinishedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        )
        self._execute(
            sql,
            (
                agent_execution_id,
                prediction_id,
                agent_name,
                int(attempt_number),
                status,
                prompt_version,
                deployment_name,
                input_tokens,
                output_tokens,
                duration_ms,
                self._json(output_json) if output_json is not None else None,
                error_code,
                started_at or "2026-11-09T00:00:00Z",
                finished_at or started_at or "2026-11-09T00:00:00Z",
            ),
        )

    def record_review_proposal(
        self,
        *,
        review_id: str,
        prediction_id: str,
        status: str,
        summary: str,
        recommendations: dict[str, Any],
        limitations: dict[str, Any],
    ) -> None:
        if status not in self.REVIEW_STATUS:
            raise ValueError(f"status must be one of {sorted(self.REVIEW_STATUS)}.")
        sql = (
            "INSERT INTO dbo.ReviewProposal "
            "(ReviewId, PredictionId, Status, Summary, RecommendationsJson, LimitationsJson, CreatedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())"
        )
        self._execute(
            sql,
            (
                review_id,
                prediction_id,
                status,
                summary,
                self._json(recommendations),
                self._json(limitations),
            ),
        )

    def record_human_decision(
        self,
        *,
        human_decision_id: str,
        review_id: str,
        reviewer_object_id: str,
        decision: str,
        approved_action: str | None = None,
        decision_note: str | None = None,
        decided_at: str | None = None,
    ) -> None:
        if decision not in {"approved", "edited", "rejected"}:
            raise ValueError("decision must be approved, edited or rejected.")
        sql = (
            "INSERT INTO dbo.HumanDecision "
            "(HumanDecisionId, ReviewId, ReviewerObjectId, Decision, ApprovedAction, DecisionNote, DecidedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        self._execute(
            sql,
            (
                human_decision_id,
                review_id,
                reviewer_object_id,
                decision,
                approved_action,
                decision_note,
                decided_at or "2026-11-09T00:00:00Z",
            ),
        )

    def record_intervention(
        self,
        *,
        intervention_id: str,
        human_decision_id: str,
        action_code: str,
        status: str,
        owner_object_id: str | None = None,
        due_at: str | None = None,
    ) -> None:
        if status not in self.INTERVENTION_STATUS:
            raise ValueError(f"status must be one of {sorted(self.INTERVENTION_STATUS)}.")
        sql = (
            "INSERT INTO dbo.Intervention "
            "(InterventionId, HumanDecisionId, ActionCode, Status, OwnerObjectId, DueAt, CreatedAt) "
            "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())"
        )
        self._execute(
            sql,
            (
                intervention_id,
                human_decision_id,
                action_code,
                status,
                owner_object_id,
                due_at,
            ),
        )

    def record_outcome_target(
        self,
        *,
        snapshot_id: str,
        mature: bool,
        target_desercion: bool | None,
        outcome_period: str | None,
        source_version: str,
        observed_at: str | None = None,
    ) -> None:
        if mature and target_desercion is None:
            raise ValueError("target_desercion is required when mature is true.")
        if not mature and target_desercion is not None:
            raise ValueError("target_desercion must be null unless mature is true.")
        sql = (
            "INSERT INTO dbo.OutcomeTarget "
            "(SnapshotId, Mature, TargetDesercion, OutcomePeriod, SourceVersion, ObservedAt) "
            "VALUES (?, ?, ?, ?, ?, ?)"
        )
        self._execute(
            sql,
            (
                snapshot_id,
                bool(mature),
                target_desercion,
                outcome_period,
                source_version,
                observed_at or "2026-11-09T00:00:00Z",
            ),
        )

    def record_audit_event(
        self,
        *,
        actor_object_id: str | None,
        action_code: str,
        entity_type: str,
        entity_id: str,
        data_mode: str,
        metadata: dict[str, Any],
    ) -> None:
        if data_mode not in {"synthetic", "institutional"}:
            raise ValueError("data_mode must be synthetic or institutional.")
        sql = (
            "INSERT INTO dbo.AuditEvent "
            "(ActorObjectId, ActionCode, EntityType, EntityId, DataMode, MetadataJson, OccurredAt) "
            "VALUES (?, ?, ?, ?, ?, ?, SYSUTCDATETIME())"
        )
        self._execute(
            sql,
            (
                actor_object_id,
                action_code,
                entity_type,
                entity_id,
                data_mode,
                self._json(metadata),
            ),
        )
