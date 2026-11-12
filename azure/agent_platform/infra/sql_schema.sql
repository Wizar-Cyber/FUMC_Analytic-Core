-- SAT-FUMC operational persistence schema. Apply only to an approved Azure SQL database.
-- No direct identifiers or clinical notes belong in these tables.
SET XACT_ABORT ON;
GO

IF OBJECT_ID('dbo.SchemaVersion', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.SchemaVersion (
        Version int NOT NULL,
        Name nvarchar(100) NOT NULL,
        ChecksumSha256 char(64) NOT NULL,
        AppliedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_SchemaVersion_AppliedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_SchemaVersion PRIMARY KEY (Version)
    );
END;
GO

IF OBJECT_ID('dbo.ModelRelease', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ModelRelease (
        ModelName nvarchar(100) NOT NULL,
        ModelVersion nvarchar(80) NOT NULL,
        DatasetVersion nvarchar(128) NOT NULL,
        CodeVersionSha256 char(64) NOT NULL,
        DecisionThreshold decimal(8,7) NOT NULL,
        PromotionStatus varchar(40) NOT NULL,
        MetricsJson nvarchar(max) NOT NULL,
        CreatedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_ModelRelease_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_ModelRelease PRIMARY KEY (ModelName, ModelVersion),
        CONSTRAINT CK_ModelRelease_Threshold CHECK (DecisionThreshold >= 0 AND DecisionThreshold <= 1),
        CONSTRAINT CK_ModelRelease_MetricsJson CHECK (ISJSON(MetricsJson) = 1)
    );
END;
GO

IF OBJECT_ID('dbo.StudentSnapshot', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.StudentSnapshot (
        SnapshotId uniqueidentifier NOT NULL,
        DataMode varchar(20) NOT NULL,
        PseudonymizedStudentId nvarchar(128) NOT NULL,
        AcademicPeriod char(6) NOT NULL,
        PredictionCut varchar(32) NOT NULL,
        ObservedAt datetimeoffset(3) NOT NULL,
        FeatureSchemaVersion varchar(40) NOT NULL,
        SourceDatasetVersion nvarchar(128) NOT NULL,
        CreatedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_StudentSnapshot_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_StudentSnapshot PRIMARY KEY (SnapshotId),
        CONSTRAINT UQ_StudentSnapshot_NaturalKey UNIQUE (DataMode, PseudonymizedStudentId, AcademicPeriod, PredictionCut, SourceDatasetVersion),
        CONSTRAINT CK_StudentSnapshot_DataMode CHECK (DataMode IN ('synthetic', 'institutional'))
    );
    CREATE INDEX IX_StudentSnapshot_StudentPeriod ON dbo.StudentSnapshot (PseudonymizedStudentId, AcademicPeriod, PredictionCut);
END;
GO

IF OBJECT_ID('dbo.Prediction', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Prediction (
        PredictionId uniqueidentifier NOT NULL,
        SnapshotId uniqueidentifier NOT NULL,
        ModelName nvarchar(100) NOT NULL,
        ModelVersion nvarchar(80) NOT NULL,
        Probability decimal(8,7) NOT NULL,
        RiskLevel varchar(16) NOT NULL,
        AlertRaised bit NOT NULL,
        InferenceSource varchar(32) NOT NULL,
        CreatedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_Prediction_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Prediction PRIMARY KEY (PredictionId),
        CONSTRAINT UQ_Prediction_SnapshotModel UNIQUE (SnapshotId, ModelName, ModelVersion),
        CONSTRAINT FK_Prediction_Snapshot FOREIGN KEY (SnapshotId) REFERENCES dbo.StudentSnapshot(SnapshotId),
        CONSTRAINT FK_Prediction_ModelRelease FOREIGN KEY (ModelName, ModelVersion) REFERENCES dbo.ModelRelease(ModelName, ModelVersion),
        CONSTRAINT CK_Prediction_Probability CHECK (Probability >= 0 AND Probability <= 1),
        CONSTRAINT CK_Prediction_RiskLevel CHECK (RiskLevel IN ('Bajo', 'Medio', 'Alto', 'Crítico')),
        CONSTRAINT CK_Prediction_Source CHECK (InferenceSource IN ('azure_ml', 'synthetic_fixture'))
    );
    CREATE INDEX IX_Prediction_RiskCreated ON dbo.Prediction (RiskLevel, CreatedAt DESC);
END;
GO

IF OBJECT_ID('dbo.AgentExecution', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.AgentExecution (
        AgentExecutionId uniqueidentifier NOT NULL,
        PredictionId uniqueidentifier NOT NULL,
        AgentName varchar(40) NOT NULL,
        AttemptNumber int NOT NULL,
        Status varchar(20) NOT NULL,
        PromptVersion varchar(80) NOT NULL,
        DeploymentName varchar(100) NOT NULL,
        InputTokens int NULL,
        OutputTokens int NULL,
        DurationMs int NULL,
        OutputJson nvarchar(max) NULL,
        ErrorCode varchar(80) NULL,
        StartedAt datetimeoffset(3) NOT NULL,
        FinishedAt datetimeoffset(3) NULL,
        CONSTRAINT PK_AgentExecution PRIMARY KEY (AgentExecutionId),
        CONSTRAINT UQ_AgentExecution_Attempt UNIQUE (PredictionId, AgentName, AttemptNumber),
        CONSTRAINT FK_AgentExecution_Prediction FOREIGN KEY (PredictionId) REFERENCES dbo.Prediction(PredictionId),
        CONSTRAINT CK_AgentExecution_Status CHECK (Status IN ('queued', 'running', 'succeeded', 'failed', 'timed_out')),
        CONSTRAINT CK_AgentExecution_OutputJson CHECK (OutputJson IS NULL OR ISJSON(OutputJson) = 1)
    );
    CREATE INDEX IX_AgentExecution_Prediction ON dbo.AgentExecution (PredictionId, StartedAt);
END;
GO

IF OBJECT_ID('dbo.ReviewProposal', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.ReviewProposal (
        ReviewId nvarchar(100) NOT NULL,
        PredictionId uniqueidentifier NOT NULL,
        Status varchar(24) NOT NULL,
        Summary nvarchar(2000) NOT NULL,
        RecommendationsJson nvarchar(max) NOT NULL,
        LimitationsJson nvarchar(max) NOT NULL,
        CreatedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_ReviewProposal_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_ReviewProposal PRIMARY KEY (ReviewId),
        CONSTRAINT UQ_ReviewProposal_Prediction UNIQUE (PredictionId),
        CONSTRAINT FK_ReviewProposal_Prediction FOREIGN KEY (PredictionId) REFERENCES dbo.Prediction(PredictionId),
        CONSTRAINT CK_ReviewProposal_Status CHECK (Status IN ('pending_approval', 'approved', 'edited', 'rejected')),
        CONSTRAINT CK_ReviewProposal_Recommendations CHECK (ISJSON(RecommendationsJson) = 1),
        CONSTRAINT CK_ReviewProposal_Limitations CHECK (ISJSON(LimitationsJson) = 1)
    );
END;
GO

IF OBJECT_ID('dbo.HumanDecision', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.HumanDecision (
        HumanDecisionId uniqueidentifier NOT NULL,
        ReviewId nvarchar(100) NOT NULL,
        ReviewerObjectId uniqueidentifier NOT NULL,
        Decision varchar(16) NOT NULL,
        ApprovedAction varchar(40) NULL,
        DecisionNote nvarchar(1000) NULL,
        DecidedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_HumanDecision_DecidedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_HumanDecision PRIMARY KEY (HumanDecisionId),
        CONSTRAINT UQ_HumanDecision_Review UNIQUE (ReviewId),
        CONSTRAINT FK_HumanDecision_Review FOREIGN KEY (ReviewId) REFERENCES dbo.ReviewProposal(ReviewId),
        CONSTRAINT CK_HumanDecision_Decision CHECK (Decision IN ('approved', 'edited', 'rejected'))
    );
END;
GO

IF OBJECT_ID('dbo.Intervention', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.Intervention (
        InterventionId uniqueidentifier NOT NULL,
        HumanDecisionId uniqueidentifier NOT NULL,
        ActionCode varchar(40) NOT NULL,
        Status varchar(20) NOT NULL,
        OwnerObjectId uniqueidentifier NULL,
        DueAt datetimeoffset(3) NULL,
        CreatedAt datetimeoffset(3) NOT NULL CONSTRAINT DF_Intervention_CreatedAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_Intervention PRIMARY KEY (InterventionId),
        CONSTRAINT UQ_Intervention_Decision UNIQUE (HumanDecisionId),
        CONSTRAINT FK_Intervention_Decision FOREIGN KEY (HumanDecisionId) REFERENCES dbo.HumanDecision(HumanDecisionId),
        CONSTRAINT CK_Intervention_Status CHECK (Status IN ('open', 'in_progress', 'completed', 'cancelled'))
    );
END;
GO

IF OBJECT_ID('dbo.OutcomeTarget', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.OutcomeTarget (
        SnapshotId uniqueidentifier NOT NULL,
        Mature bit NOT NULL,
        TargetDesercion bit NULL,
        OutcomePeriod char(6) NULL,
        SourceVersion nvarchar(128) NOT NULL,
        ObservedAt datetimeoffset(3) NULL,
        CONSTRAINT PK_OutcomeTarget PRIMARY KEY (SnapshotId),
        CONSTRAINT FK_OutcomeTarget_Snapshot FOREIGN KEY (SnapshotId) REFERENCES dbo.StudentSnapshot(SnapshotId),
        CONSTRAINT CK_OutcomeTarget_Maturity CHECK (
            (Mature = 1 AND TargetDesercion IS NOT NULL AND ObservedAt IS NOT NULL)
            OR (Mature = 0 AND TargetDesercion IS NULL)
        )
    );
END;
GO

IF OBJECT_ID('dbo.AuditEvent', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.AuditEvent (
        AuditEventId bigint IDENTITY(1,1) NOT NULL,
        ActorObjectId uniqueidentifier NULL,
        ActionCode varchar(80) NOT NULL,
        EntityType varchar(40) NOT NULL,
        EntityId nvarchar(128) NOT NULL,
        DataMode varchar(20) NOT NULL,
        MetadataJson nvarchar(max) NOT NULL,
        OccurredAt datetimeoffset(3) NOT NULL CONSTRAINT DF_AuditEvent_OccurredAt DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_AuditEvent PRIMARY KEY (AuditEventId),
        CONSTRAINT CK_AuditEvent_DataMode CHECK (DataMode IN ('synthetic', 'institutional')),
        CONSTRAINT CK_AuditEvent_Metadata CHECK (ISJSON(MetadataJson) = 1)
    );
    CREATE INDEX IX_AuditEvent_Entity ON dbo.AuditEvent (EntityType, EntityId, OccurredAt DESC);
END;
GO
