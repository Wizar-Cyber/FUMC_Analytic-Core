from __future__ import annotations

import hashlib
import json
import re
import struct
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from datetime import datetime, timedelta, timezone

SQL_COPT_SS_ACCESS_TOKEN = 1256
SQL_TOKEN_SCOPE = "https://database.windows.net/.default"
_TRANSIENT_ERROR_CODES = ("40613", "40197", "40501", "49918", "10928", "10929", "HYT00", "08S01")


SQL_SS_TIMESTAMPOFFSET = -155


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _datetimeoffset_converter(raw: bytes) -> datetime:
    year, month, day, hour, minute, second, fraction, tz_hours, tz_minutes = struct.unpack("<6hI2h", raw)
    return datetime(
        year, month, day, hour, minute, second, fraction // 1000,
        timezone(timedelta(hours=tz_hours, minutes=tz_minutes)),
    )


def connect_entra(server: str, database: str, *, credential: Any | None = None, retries: int = 4) -> Any:
    """Open a pyodbc connection with a Microsoft Entra token (Managed Identity in Azure, az login locally).

    Serverless databases can be paused; the first attempts may fail while resuming, so transient errors are retried.
    """
    import pyodbc

    if credential is None:
        from azure.identity import DefaultAzureCredential

        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    host = server if "." in server else f"{server}.database.windows.net"
    connection_string = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{host},1433;Database={database};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=60"
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        token = credential.get_token(SQL_TOKEN_SCOPE).token.encode("utf-16-le")
        packed = struct.pack(f"<I{len(token)}s", len(token), token)
        try:
            connection = pyodbc.connect(
                connection_string, attrs_before={SQL_COPT_SS_ACCESS_TOKEN: packed}, autocommit=False
            )
            connection.add_output_converter(SQL_SS_TIMESTAMPOFFSET, _datetimeoffset_converter)
            return connection
        except pyodbc.Error as error:
            last_error = error
            if not any(code in str(error) for code in _TRANSIENT_ERROR_CODES):
                raise
            time.sleep(min(5 * (attempt + 1), 20))
    assert last_error is not None
    raise last_error


class AzureSqlRepository:
    """Azure SQL repository for the SAT-FUMC audit/persistence contract.

    Requires an explicit DB-API connection (see connect_entra); there is no silent in-memory fallback.
    """

    RISK_LEVELS = {"Bajo", "Medio", "Alto", "Crítico"}
    MODEL_RELEASE_STATUS = {"approved", "blocked", "pending_review", "rejected"}
    REVIEW_STATUS = {"pending_approval", "approved", "edited", "rejected"}
    AGENT_STATUS = {"queued", "running", "succeeded", "failed", "timed_out"}
    INTERVENTION_STATUS = {"open", "in_progress", "completed", "cancelled"}

    def __init__(self, connection: Any, schema_path: str | Path | None = None) -> None:
        if connection is None:
            raise ValueError("AzureSqlRepository requires an explicit database connection.")
        self.connection = connection
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
                started_at or _now_iso(),
                finished_at or started_at or _now_iso(),
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
                decided_at or _now_iso(),
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
                observed_at or _now_iso(),
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

    # ---- transacciones y migraciones ----

    @contextmanager
    def transaction(self) -> Iterator["AzureSqlRepository"]:
        try:
            yield self
        except Exception:
            rollback = getattr(self.connection, "rollback", None)
            if rollback:
                rollback()
            raise
        else:
            commit = getattr(self.connection, "commit", None)
            if commit:
                commit()

    def apply_schema(self, *, version: int = 1, name: str = "baseline") -> bool:
        """Apply sql_schema.sql (idempotent) and register it in dbo.SchemaVersion. Returns True if newly registered."""
        schema = self.schema_sql()
        checksum = hashlib.sha256(schema.encode("utf-8")).hexdigest()
        with self.transaction():
            for batch in re.split(r"^\s*GO\s*$", schema, flags=re.MULTILINE | re.IGNORECASE):
                if batch.strip():
                    self._execute(batch)
            existing = self._fetch("SELECT Version FROM dbo.SchemaVersion WHERE Version = ?", (version,))
            if existing:
                return False
            self._execute(
                "INSERT INTO dbo.SchemaVersion (Version, Name, ChecksumSha256) VALUES (?, ?, ?)",
                (version, name, checksum),
            )
            return True

    def list_schema_versions(self) -> list[dict[str, Any]]:
        return self._fetch("SELECT Version, Name, ChecksumSha256, AppliedAt FROM dbo.SchemaVersion ORDER BY Version")

    # ---- altas idempotentes necesarias por las claves foráneas ----

    def ensure_model_release(
        self,
        *,
        model_name: str,
        model_version: str,
        dataset_version: str = "synthetic",
        code_version_sha256: str = "0" * 64,
        decision_threshold: float = 0.5,
        promotion_status: str = "pending_review",
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self._validate_threshold(decision_threshold)
        if promotion_status not in self.MODEL_RELEASE_STATUS:
            raise ValueError(f"promotion_status must be one of {sorted(self.MODEL_RELEASE_STATUS)}.")
        self._execute(
            "IF NOT EXISTS (SELECT 1 FROM dbo.ModelRelease WITH (UPDLOCK, HOLDLOCK) WHERE ModelName = ? AND ModelVersion = ?) "
            "INSERT INTO dbo.ModelRelease (ModelName, ModelVersion, DatasetVersion, CodeVersionSha256, DecisionThreshold, PromotionStatus, MetricsJson) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                model_name,
                model_version,
                model_name,
                model_version,
                dataset_version,
                code_version_sha256,
                float(decision_threshold),
                promotion_status,
                self._json(metrics or {}),
            ),
        )

    def ensure_student_snapshot(
        self,
        *,
        snapshot_id: str,
        data_mode: str,
        student_id: str,
        academic_period: str,
        prediction_cut: str,
        feature_schema_version: str,
        source_dataset_version: str,
        observed_at: str | None = None,
    ) -> None:
        if data_mode not in {"synthetic", "institutional"}:
            raise ValueError("data_mode must be synthetic or institutional.")
        self._execute(
            "IF NOT EXISTS (SELECT 1 FROM dbo.StudentSnapshot WITH (UPDLOCK, HOLDLOCK) WHERE SnapshotId = ?) "
            "INSERT INTO dbo.StudentSnapshot (SnapshotId, DataMode, PseudonymizedStudentId, AcademicPeriod, PredictionCut, ObservedAt, FeatureSchemaVersion, SourceDatasetVersion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                snapshot_id,
                data_mode,
                student_id,
                academic_period,
                prediction_cut,
                observed_at or _now_iso(),
                feature_schema_version,
                source_dataset_version,
            ),
        )

    def ensure_prediction(self, **kwargs: Any) -> None:
        if self._fetch("SELECT 1 AS present FROM dbo.Prediction WITH (UPDLOCK, HOLDLOCK) WHERE PredictionId = ?", (kwargs["prediction_id"],)):
            return
        self.record_prediction(**kwargs)

    def ensure_review_proposal(self, **kwargs: Any) -> None:
        if self._fetch("SELECT 1 AS present FROM dbo.ReviewProposal WITH (UPDLOCK, HOLDLOCK) WHERE ReviewId = ?", (kwargs["review_id"],)):
            return
        self.record_review_proposal(**kwargs)

    def update_review_status(self, review_id: str, status: str) -> None:
        if status not in self.REVIEW_STATUS:
            raise ValueError(f"status must be one of {sorted(self.REVIEW_STATUS)}.")
        self._execute("UPDATE dbo.ReviewProposal SET Status = ? WHERE ReviewId = ?", (status, review_id))

    def update_intervention_status(self, intervention_id: str, status: str) -> None:
        if status not in self.INTERVENTION_STATUS:
            raise ValueError(f"status must be one of {sorted(self.INTERVENTION_STATUS)}.")
        self._execute("UPDATE dbo.Intervention SET Status = ? WHERE InterventionId = ?", (status, intervention_id))

    # ---- lecturas ----

    def _fetch(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self._execute(sql, params)
        description = getattr(cursor, "description", None)
        if not description:
            return []
        columns = [column[0] for column in description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _parse_json_columns(row: dict[str, Any], *columns: str) -> dict[str, Any]:
        for column in columns:
            if isinstance(row.get(column), str):
                row[column] = json.loads(row[column])
        return row

    @staticmethod
    def _limit(limit: int) -> int:
        return max(1, min(int(limit), 1000))

    def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        rows = self._fetch("SELECT * FROM dbo.Prediction WHERE PredictionId = ?", (prediction_id,))
        return rows[0] if rows else None

    def list_predictions(self, *, risk_level: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = f"SELECT TOP ({self._limit(limit)}) * FROM dbo.Prediction"
        params: tuple[Any, ...] = ()
        if risk_level:
            if risk_level not in self.RISK_LEVELS:
                raise ValueError(f"risk_level must be one of {sorted(self.RISK_LEVELS)}.")
            sql += " WHERE RiskLevel = ?"
            params = (risk_level,)
        return self._fetch(sql + " ORDER BY CreatedAt DESC", params)

    def get_review_proposal(self, review_id: str) -> dict[str, Any] | None:
        rows = self._fetch("SELECT * FROM dbo.ReviewProposal WHERE ReviewId = ?", (review_id,))
        return self._parse_json_columns(rows[0], "RecommendationsJson", "LimitationsJson") if rows else None

    def list_review_proposals(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = f"SELECT TOP ({self._limit(limit)}) * FROM dbo.ReviewProposal"
        params: tuple[Any, ...] = ()
        if status:
            if status not in self.REVIEW_STATUS:
                raise ValueError(f"status must be one of {sorted(self.REVIEW_STATUS)}.")
            sql += " WHERE Status = ?"
            params = (status,)
        rows = self._fetch(sql + " ORDER BY CreatedAt DESC", params)
        return [self._parse_json_columns(row, "RecommendationsJson", "LimitationsJson") for row in rows]

    def get_human_decision(self, review_id: str) -> dict[str, Any] | None:
        rows = self._fetch("SELECT * FROM dbo.HumanDecision WHERE ReviewId = ?", (review_id,))
        return rows[0] if rows else None

    def list_interventions(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = f"SELECT TOP ({self._limit(limit)}) * FROM dbo.Intervention"
        params: tuple[Any, ...] = ()
        if status:
            if status not in self.INTERVENTION_STATUS:
                raise ValueError(f"status must be one of {sorted(self.INTERVENTION_STATUS)}.")
            sql += " WHERE Status = ?"
            params = (status,)
        return self._fetch(sql + " ORDER BY CreatedAt DESC", params)

    def list_audit_events(
        self, *, entity_type: str | None = None, entity_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if entity_type:
            clauses.append("EntityType = ?")
            params.append(entity_type)
        if entity_id:
            clauses.append("EntityId = ?")
            params.append(entity_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._fetch(
            f"SELECT TOP ({self._limit(limit)}) * FROM dbo.AuditEvent{where} ORDER BY OccurredAt DESC",
            tuple(params),
        )
        return [self._parse_json_columns(row, "MetadataJson") for row in rows]
