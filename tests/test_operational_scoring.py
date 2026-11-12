import asyncio
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))

from sat_agents.rescoring import rescore_snapshots  # noqa: E402
from src.ml import endpoint_scoring as scoring  # noqa: E402

SETTINGS = scoring.EndpointSettings(url="https://sat.example/score", key="SECRET-KEY", deployment="blue")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ok(probabilities):
    body = {
        "status": "success",
        "predictions": [
            {"probabilidad_desercion": p, "nivel_riesgo": "Bajo", "alerta_activa": False}
            for p in probabilities
        ],
    }
    return FakeResponse(json.dumps(body).encode())


def http_error(code):
    return urllib.error.HTTPError(
        "https://sat.example/score", code, "err", {}, io.BytesIO(b"detalle SECRET-KEY")
    )


class Opener:
    def __init__(self, steps):
        self.steps = list(steps)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(request) if callable(step) else step


def echo(request):
    count = len(json.loads(request.data)["data"])
    return ok([0.5] * count)


def no_sleep(_):
    return None


def test_scores_in_batches_with_payload_contract_and_headers():
    opener = Opener([echo, echo, echo])
    records = [{"programa": "FIS", "saldo_mora": None}] * 5
    result = scoring.score_records(
        records, SETTINGS, batch_size=2, timeout=7, opener=opener, sleep=no_sleep
    )

    assert result == [0.5] * 5
    assert [len(json.loads(r.data)["data"]) for r, _ in opener.requests] == [2, 2, 1]
    request, timeout = opener.requests[0]
    assert timeout == 7
    assert request.get_header("Authorization") == "Bearer SECRET-KEY"
    assert request.get_header("Azureml-model-deployment") == "blue"


def test_retries_transient_errors_then_succeeds():
    opener = Opener([http_error(503), TimeoutError(), echo])
    result = scoring.score_records([{"a": 1}], SETTINGS, retries=3, opener=opener, sleep=no_sleep)
    assert result == [0.5]
    assert len(opener.requests) == 3


def test_fails_clearly_without_fallback_and_never_leaks_key():
    opener = Opener([http_error(503)] * 3)
    with pytest.raises(scoring.EndpointScoringError) as error:
        scoring.score_records([{"a": 1}], SETTINGS, retries=2, opener=opener, sleep=no_sleep)
    assert "3 intentos" in str(error.value) and "fallback" in str(error.value)
    assert "SECRET-KEY" not in str(error.value) and "SECRET-KEY" not in repr(SETTINGS)


def test_client_errors_are_not_retried():
    opener = Opener([http_error(401), echo])
    with pytest.raises(scoring.EndpointScoringError, match="401"):
        scoring.score_records([{"a": 1}], SETTINGS, opener=opener, sleep=no_sleep)
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "response",
    [
        ok([0.4, 0.5]),
        ok([1.5]),
        FakeResponse(b"no es json"),
        FakeResponse(json.dumps({"status": "error"}).encode()),
    ],
)
def test_rejects_invalid_endpoint_responses(response):
    with pytest.raises(scoring.EndpointScoringError):
        scoring.score_records([{"a": 1}], SETTINGS, opener=Opener([response]), sleep=no_sleep)


def test_settings_require_environment_and_clean_records_remove_nan():
    with pytest.raises(scoring.EndpointScoringError, match="AZURE_ML_ENDPOINT_URL"):
        scoring.settings_from_env({})
    settings = scoring.settings_from_env({"AZURE_ML_ENDPOINT_URL": "u", "AZURE_ML_ENDPOINT_KEY": "k"})
    assert settings.deployment == "blue"
    assert scoring.clean_record({"a": float("nan"), "b": 2}, ["a", "b", "c"]) == {
        "a": None,
        "b": 2,
        "c": None,
    }


def test_model_info_resolution_order_and_parsing():
    info = scoring.parse_model_id(
        "azureml:/subscriptions/x/workspaces/w/models/SAT_FUMC_LightGBM_Model/versions/3"
    )
    assert (info.name, info.version) == ("SAT_FUMC_LightGBM_Model", "3")
    assert scoring.parse_model_id("azureml:SAT_FUMC_LightGBM_Model:2").version == "2"
    assert scoring.resolve_model_info(SETTINGS, explicit=("M", "9"), env={}) == scoring.ModelInfo("M", "9")
    env = {"AZURE_ML_MODEL_NAME": "E", "AZURE_ML_MODEL_VERSION": "4"}
    assert scoring.resolve_model_info(SETTINGS, env=env) == scoring.ModelInfo("E", "4")
    described = scoring.resolve_model_info(
        SETTINGS, env={}, describe_deployment=lambda: "azureml:M:5"
    )
    assert described == scoring.ModelInfo("M", "5")
    with pytest.raises(scoring.EndpointScoringError):
        scoring.parse_model_id("desconocido")


class FakeSnapshots:
    def __init__(self, rows):
        self.rows = {r["RowKey"]: dict(r) for r in rows}

    def query_entities(self, query_filter):
        async def iterate():
            for row in list(self.rows.values()):
                yield dict(row)

        return iterate()

    async def upsert_entity(self, entity, mode=None):
        self.rows[entity["RowKey"]].update(entity)


def snapshot(number, probability, features=True, status="processed"):
    return {
        "PartitionKey": "2025-2",
        "RowKey": f"ST-SYN-{number:06d}",
        "StudentId": f"ST-SYN-{number:06d}",
        "ModelProbability": probability,
        "RiskLevel": "Bajo",
        "Status": status,
        "ReviewId": "rev-1",
        "BatchId": "b-1",
        "FeaturesJson": json.dumps({"saldo_mora": 10}) if features else "",
    }


def test_rescore_updates_model_fields_only_and_skips_legacy_rows():
    table = FakeSnapshots([snapshot(1, 0.1), snapshot(2, 0.1), snapshot(3, 0.1, features=False)])
    batches = []

    def score_batch(batch):
        batches.append(len(batch))
        return [0.9, 0.2]

    stats = asyncio.run(
        rescore_snapshots(
            table,
            score_batch,
            model_name="M",
            model_version="4",
            scored_at="2026-11-10T00:00:00+00:00",
            batch_size=10,
        )
    )

    assert stats["scored"] == 2
    assert stats["skipped_without_features"] == 1
    assert stats["risk_changed"] == 1
    first = table.rows["ST-SYN-000001"]
    assert (first["ModelProbability"], first["RiskLevel"], first["ModelVersion"]) == (0.9, "Alto", "4")
    assert first["Status"] == "processed" and first["ReviewId"] == "rev-1" and first["BatchId"] == "b-1"
    assert table.rows["ST-SYN-000003"]["ModelProbability"] == 0.1
    assert batches == [2]


def test_rescore_dry_run_and_endpoint_failure_leave_data_untouched():
    table = FakeSnapshots([snapshot(1, 0.1)])
    asyncio.run(
        rescore_snapshots(
            table, lambda b: [0.95], model_name="M", model_version="4", scored_at="t", dry_run=True
        )
    )
    assert table.rows["ST-SYN-000001"]["ModelProbability"] == 0.1

    def failing(batch):
        raise scoring.EndpointScoringError("sin respuesta")

    with pytest.raises(scoring.EndpointScoringError):
        asyncio.run(
            rescore_snapshots(table, failing, model_name="M", model_version="4", scored_at="t")
        )
    assert table.rows["ST-SYN-000001"]["ModelProbability"] == 0.1
