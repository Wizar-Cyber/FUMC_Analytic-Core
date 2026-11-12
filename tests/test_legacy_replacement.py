import argparse
import asyncio
import copy
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))
sys.path.insert(0, str(ROOT / "scripts"))

import replace_legacy_cohort as cli  # noqa: E402
from sat_agents import legacy_replacement as legacy  # noqa: E402
from sat_agents import synthetic_database as db  # noqa: E402
from sat_agents.training_cohort import build_cohort_entities  # noqa: E402
from src.ml import endpoint_scoring as scoring  # noqa: E402

SCORED = scoring.ModelInfo("SAT_TEST_MODEL", "3")


class FakeTable:
    def __init__(self, rows=None):
        self.rows = {(r["PartitionKey"], r["RowKey"]): dict(r) for r in (rows or [])}
        self.fail_delete_after = None
        self.deletes = 0

    async def get_entity(self, partition_key, row_key):
        try:
            return dict(self.rows[(partition_key, row_key)])
        except KeyError:
            raise ResourceNotFoundError("missing") from None

    async def create_entity(self, entity):
        key = (entity["PartitionKey"], entity["RowKey"])
        if key in self.rows:
            raise ResourceExistsError("exists")
        self.rows[key] = dict(entity)

    async def upsert_entity(self, entity, mode=None):
        key = (entity["PartitionKey"], entity["RowKey"])
        if mode is not None and "REPLACE" in str(mode):
            self.rows[key] = dict(entity)
        else:
            self.rows[key] = {**self.rows.get(key, {}), **entity}

    async def delete_entity(self, partition_key, row_key):
        if self.fail_delete_after is not None and self.deletes >= self.fail_delete_after:
            raise RuntimeError("fallo parcial simulado")
        if (partition_key, row_key) not in self.rows:
            raise ResourceNotFoundError("missing")
        del self.rows[(partition_key, row_key)]
        self.deletes += 1

    async def submit_transaction(self, operations):
        raise RuntimeError("sin transacciones en el falso: se usa el respaldo fila a fila")

    def _iterate(self, partition=None):
        async def iterate():
            for (pk, _), row in sorted(self.rows.items()):
                if partition is None or pk == partition:
                    yield dict(row)

        return iterate()

    def query_entities(self, query_filter):
        return self._iterate(query_filter.split("'")[1])

    def list_entities(self):
        return self._iterate()


class FakeReviews:
    def __init__(self, reviews):
        self.reviews = dict(reviews)

    async def export(self, review_id):
        return self.reviews.get(review_id)

    async def delete(self, review_id):
        self.reviews.pop(review_id, None)


def training_entities(numbers):
    rows = [
        {
            "id_estudiante_anon": f"ST-{number:06d}", "periodo_id": "2025-2", "programa": "FIS",
            "sede": "MED", "modalidad": "Presencial", "semestres_cursados": 3,
            "estrato_socioeconomico": 3, "jefe_hogar": 0, "monto_matricula": 3_000_000.0,
            "saldo_mora": 0.0, "tipo_financiacion": "ICETEX", "tiene_beca": 0,
        }
        for number in numbers
    ]
    return build_cohort_entities(
        snapshot_rows=rows,
        probabilities={row["id_estudiante_anon"]: 0.8 for row in rows},
        course_rows=[],
        wellbeing_rows=[],
        target_rows=[],
        program_names={"FIS": "Fisioterapia"},
        campus_names={"MED": "Medellín"},
        numbers=list(numbers),
        model_name=SCORED.name,
        model_version=SCORED.version,
        scored_at="2026-11-10T00:00:00+00:00",
        feature_columns=["semestres_cursados"],
    )


def build_tables(legacy_count=30, protected_numbers=(31, 32, 33)):
    seeded = db._generate_entities(legacy_count)
    protected = training_entities(protected_numbers)
    tables = {name: FakeTable() for name in db.TABLE_NAMES}
    for source in (seeded, protected):
        for name, rows in source.items():
            for row in rows:
                tables[name].rows[(row["PartitionKey"], row["RowKey"])] = dict(row)
    legacy_reviewed = seeded[db.TABLE_SNAPSHOTS][0]["RowKey"]
    tables[db.TABLE_SNAPSHOTS].rows[(db.PERIOD_ID, legacy_reviewed)].update(
        {"Status": "processed", "ReviewId": "rev-1"}
    )
    tables[db.TABLE_CONTROL].rows[("control", "poc")] = {
        "PartitionKey": "control", "RowKey": "poc", "StudentCount": legacy_count + len(protected_numbers),
        "SeedVersion": db.SEED_VERSION,
    }
    asyncio.run(db._ensure_operational_data(tables))
    return tables


def snapshot_of(tables):
    return {name: copy.deepcopy(table.rows) for name, table in tables.items()}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    tables = build_tables()
    reviews = FakeReviews({"rev-1": {"proposal": {"a": 1}, "approval": {"ok": True}}})

    @asynccontextmanager
    async def table_clients():
        yield tables

    @asynccontextmanager
    async def review_store():
        yield reviews

    state = {"score_error": None}

    def score_cohort(cohort, args):
        if state["score_error"]:
            raise state["score_error"]
        return {student: 0.8 for student in cohort}, SCORED, "2026-11-10T00:00:00+00:00"

    monkeypatch.setattr(db, "_table_clients", table_clients)
    monkeypatch.setattr(cli, "open_review_store", review_store)
    monkeypatch.setattr(cli, "load_cohort", lambda args, needed, exclude, strict: (None, [f"ST-{i:06d}" for i in range(1, needed + 1)]))
    monkeypatch.setattr(cli.seeding, "score_cohort", score_cohort)
    monkeypatch.setattr(
        cli.seeding, "build",
        lambda frames, cohort, probabilities, model, scored_at, first_number, numbers=None: training_entities(numbers),
    )

    def args(apply, count=40):
        return argparse.Namespace(
            apply=apply, count=count, data_dir=tmp_path, generate=False, backup_root=tmp_path / "backups",
            model_name="", model_version="", batch_size=200, timeout=5, retries=0,
        )

    return argparse.Namespace(tables=tables, reviews=reviews, args=args, state=state, root=tmp_path / "backups")


def test_legacy_detection_protects_every_row_scored_by_the_model():
    assert legacy.is_legacy_snapshot({"StudentId": "ST-SYN-000001"})
    assert legacy.is_legacy_snapshot({"FeaturesJson": "", "ModelName": None})
    assert not legacy.is_legacy_snapshot({"FeaturesJson": '{"a": 1}'})
    assert not legacy.is_legacy_snapshot({"ModelName": "M"})
    assert not legacy.is_legacy_snapshot({"TrainingStudentId": "ST-000001"})
    assert not legacy.is_legacy_snapshot({"FeaturesJson": "no-es-json"})


def test_dry_run_reports_counts_and_changes_nothing(harness):
    before = snapshot_of(harness.tables)

    assert asyncio.run(cli.run(harness.args(apply=False))) == 0

    assert snapshot_of(harness.tables) == before
    assert harness.reviews.reviews.keys() == {"rev-1"}
    assert not harness.root.exists()
    legacy_snapshots, protected = asyncio.run(legacy.find_legacy(harness.tables))
    rows = asyncio.run(legacy.collect_rows(harness.tables, set(legacy_snapshots)))
    plan = cli.describe_plan(legacy_snapshots, rows, protected, legacy.missing_numbers(protected, 40))
    assert plan["heredados"] == 30 and plan["protegidos_por_modelo"] == 3
    assert plan["reviews_a_borrar"] == 1 and plan["estudiantes_a_sembrar"] == 37
    assert plan["filas_a_borrar"][db.TABLE_STUDENTS] == 30


def test_apply_backs_up_replaces_legacy_and_never_touches_model_rows(harness):
    protected_before = {
        key: copy.deepcopy(row)
        for name in (db.TABLE_STUDENTS, db.TABLE_SNAPSHOTS)
        for key, row in harness.tables[name].rows.items()
        if db._student_number(row["StudentId"]) in (31, 32, 33)
    }

    assert asyncio.run(cli.run(harness.args(apply=True))) == 0

    backup = next(path for path in harness.root.iterdir() if (path / f"{db.TABLE_SNAPSHOTS}.jsonl").exists())
    exported = [json.loads(line) for line in (backup / f"{db.TABLE_SNAPSHOTS}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(exported) == 30 and all(item["entity"].get("ModelName") is None for item in exported)
    assert len((backup / "reviews.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert (backup / "run.log").exists()

    snapshots = harness.tables[db.TABLE_SNAPSHOTS].rows
    assert len(snapshots) == 40
    assert all(row["ModelName"] == "SAT_TEST_MODEL" and row["FeaturesJson"] for row in snapshots.values())
    for key, row in protected_before.items():
        table = db.TABLE_STUDENTS if "FirstName" in row else db.TABLE_SNAPSHOTS
        assert harness.tables[table].rows[key] == row
    assert harness.reviews.reviews == {}
    control = harness.tables[db.TABLE_CONTROL].rows[("control", "poc")]
    assert control["StudentCount"] == 40 and control["OperationalStudentCount"] == 40
    assert harness.tables[db.TABLE_CONTROL].rows[("control", cli.STATE_ROW)]["Phase"] == "done"
    assert len(harness.tables[db.TABLE_ALERTS].rows) == 40
    assert len(harness.tables[db.TABLE_FOLLOWUPS].rows) == 40
    assert len(harness.tables[db.TABLE_TRENDS].rows) == 12


def test_backup_count_mismatch_aborts_without_deleting(harness, monkeypatch):
    before = snapshot_of(harness.tables)
    monkeypatch.setattr(legacy, "_count_lines", lambda path: 0)

    with pytest.raises(legacy.BackupMismatchError):
        asyncio.run(cli.run(harness.args(apply=True)))

    control_free = {k: v for k, v in snapshot_of(harness.tables).items()}
    for name in db.TABLE_NAMES:
        if name != db.TABLE_CONTROL:
            assert control_free[name] == before[name]
    assert harness.reviews.reviews.keys() == {"rev-1"}


def test_endpoint_failure_aborts_before_any_deletion(harness):
    before = snapshot_of(harness.tables)
    harness.state["score_error"] = scoring.EndpointScoringError("sin respuesta")

    assert asyncio.run(cli.run(harness.args(apply=True))) == 2

    assert snapshot_of(harness.tables) == before
    assert harness.reviews.reviews.keys() == {"rev-1"}


def test_resume_after_partial_delete_failure_completes_without_second_backup(harness):
    harness.tables[db.TABLE_STUDENTS].fail_delete_after = 10

    with pytest.raises(RuntimeError, match="fallo parcial"):
        asyncio.run(cli.run(harness.args(apply=True)))

    state = harness.tables[db.TABLE_CONTROL].rows[("control", cli.STATE_ROW)]
    assert state["Phase"] == "deleting"
    assert len(harness.tables[db.TABLE_SNAPSHOTS].rows) == 33
    first_backup = state["BackupDir"]

    harness.tables[db.TABLE_STUDENTS].fail_delete_after = None
    assert asyncio.run(cli.run(harness.args(apply=True))) == 0

    final = harness.tables[db.TABLE_CONTROL].rows[("control", cli.STATE_ROW)]
    assert final["Phase"] == "done" and final["BackupDir"] == first_backup
    backups = [p for p in harness.root.iterdir() if (p / f"{db.TABLE_SNAPSHOTS}.jsonl").exists()]
    assert len(backups) == 1
    assert len(harness.tables[db.TABLE_SNAPSHOTS].rows) == 40
    assert all(row["ModelName"] for row in harness.tables[db.TABLE_SNAPSHOTS].rows.values())
    assert len(harness.tables[db.TABLE_STUDENTS].rows) == 40
