from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_bicep_infra_includes_sql_operational_store():
    template = (ROOT / 'azure' / 'agent_platform' / 'infra' / 'main.bicep').read_text(encoding='utf-8')
    assert 'Microsoft.Sql/servers@' in template
    assert 'Microsoft.Sql/servers/databases@' in template
    assert 'sqlAdminPassword' in template
    assert 'SATFUMCOperational' in template


def test_sql_schema_declares_core_operational_tables():
    schema = (ROOT / 'azure' / 'agent_platform' / 'infra' / 'sql_schema.sql').read_text(encoding='utf-8')
    for table_name in [
        'dbo.ModelRelease',
        'dbo.StudentSnapshot',
        'dbo.Prediction',
        'dbo.AgentExecution',
        'dbo.ReviewProposal',
        'dbo.HumanDecision',
        'dbo.Intervention',
        'dbo.OutcomeTarget',
        'dbo.AuditEvent',
    ]:
        assert table_name in schema
