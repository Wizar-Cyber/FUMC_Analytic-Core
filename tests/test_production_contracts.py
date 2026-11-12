import importlib.util
import warnings
from pathlib import Path

import joblib
import pandas as pd
import pytest

from marshmallow.warnings import RemovedInMarshmallow4Warning
from src.agents.agent_quality import AgentQuality
from src.agents.agent_ingestion import AgentIngestion
from src.ml.feature_engineering import (
    engineer_features,
    feature_columns,
    require_feature_schema,
    temporal_holdout,
)


ROOT = Path(__file__).resolve().parents[1]


def _load_scoring_module():
    module_path = ROOT / "azure" / "endpoints" / "score.py"
    spec = importlib.util.spec_from_file_location("sat_fumc_score", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_feature_engineering_is_shared_and_handles_missing_optional_inputs():
    source = pd.DataFrame(
        {
            "saldo_mora": [600_000],
            "historial_prueba_academica": [1],
            "estrato_socioeconomico": [2],
            "semestres_cursados": [1],
        }
    )

    enriched = engineer_features(source)

    assert enriched.loc[0, "mora_x_prueba"] == 600_000
    assert enriched.loc[0, "riesgo_financiero_academico"] == 2
    assert enriched.loc[0, "primer_semestre"] == 1
    assert "engagement_lms" not in enriched
    numeric, categorical = feature_columns(enriched)
    assert "mora_x_prueba" in numeric
    assert categorical == []


def test_temporal_holdout_uses_latest_two_periods():
    frame = pd.DataFrame({"periodo_id": ["2023-1", "2024-2", "2024-1", "2025-1"]})

    train_mask, test_mask, selected = temporal_holdout(frame)

    assert selected == ["2024-2", "2025-1"]
    assert frame.loc[test_mask, "periodo_id"].tolist() == selected
    assert int(train_mask.sum() + test_mask.sum()) == len(frame)


def test_temporal_holdout_rejects_malformed_period():
    with pytest.raises(ValueError, match="Formato de periodo"):
        temporal_holdout(pd.DataFrame({"periodo_id": ["invalid"]}))


def test_training_rejects_incomplete_feature_schema():
    with pytest.raises(ValueError, match="variables requeridas"):
        require_feature_schema(pd.DataFrame({"semestres_cursados": [1]}))


def test_quality_agent_rejects_duplicate_primary_keys():
    main = pd.DataFrame(
        {
            "id_estudiante_anon": ["student-1", "student-1"],
            "periodo_id": ["2025-1", "2025-1"],
        }
    )
    target = pd.DataFrame(
        {
            "id_estudiante_anon": ["student-1"],
            "periodo_id": ["2025-1"],
            "target_desercion": [0],
        }
    )

    with pytest.raises(ValueError, match="validaciones críticas"):
        AgentQuality().run({"main_df": main, "target_df": target})


def test_quality_agent_removes_simulated_outcome_proxies():
    main = pd.DataFrame(
        {
            "id_estudiante_anon": ["student-1"],
            "periodo_id": ["2025-1"],
            "sede": ["MED"],
            "probabilidad_riesgo_simulada": [0.8],
            "nivel_riesgo_simulado": ["Alto"],
        }
    )
    target = pd.DataFrame(
        {
            "id_estudiante_anon": ["student-1"],
            "periodo_id": ["2025-1"],
            "target_desercion": [1],
        }
    )

    result = AgentQuality().run(
        {
            "main_df": main,
            "target_df": target,
            "catalogos": {"catalogos_sedes.parquet": {"MED"}},
        }
    )

    assert "probabilidad_riesgo_simulada" not in result["clean_df"]
    assert "nivel_riesgo_simulado" not in result["clean_df"]
    assert result["metrics_quality"]["fuga_detectada"] is True
    assert result["metrics_quality"]["reglas_auditadas"] == 13


def test_endpoint_init_loads_registered_pickle_artifact(tmp_path, monkeypatch):
    score = _load_scoring_module()
    model_path = tmp_path / "model.pkl"
    joblib.dump(
        joblib.load(ROOT / "outputs" / "sat_fumc_lightgbm.joblib"),
        model_path,
    )
    monkeypatch.setenv("AZUREML_MODEL_DIR", str(tmp_path))
    monkeypatch.setenv("ALERT_THRESHOLD", "0.35")
    monkeypatch.setenv("MAX_BATCH_SIZE", "1000")

    score.init()

    assert callable(score.model.predict_proba)


def test_endpoint_scores_real_model_with_training_feature_contract():
    score = _load_scoring_module()
    score.model = joblib.load(ROOT / "outputs" / "sat_fumc_lightgbm.joblib")
    score.threshold = 0.35
    source = pd.read_parquet(ROOT / "data" / "raw" / "estudiante_periodo_corte.parquet")
    request = {"data": [source.iloc[0].to_dict()]}

    response = score.run(request)

    assert response["status"] == "success"
    assert len(response["predictions"]) == 1
    prediction = response["predictions"][0]
    assert 0 <= prediction["probabilidad_desercion"] <= 1
    assert prediction["nivel_riesgo"] in {"Bajo", "Medio", "Alto", "Crítico"}


def test_endpoint_rejects_invalid_request_without_success_shaped_error():
    score = _load_scoring_module()
    score.model = object()

    with pytest.raises(ValueError, match="propiedad 'data'"):
        score.run({"not_data": []})


def test_ingestion_and_quality_allow_inference_without_target(tmp_path):
    pd.DataFrame(
        {
            "id_estudiante_anon": ["student-1"],
            "periodo_id": ["2025-1"],
            "sede": ["MED"],
            "probabilidad_riesgo_simulada": [0.7],
        }
    ).to_parquet(tmp_path / "estudiante_periodo_corte.parquet")

    ingested = AgentIngestion().run({"data_dir": str(tmp_path)})
    result = AgentQuality().run(ingested)

    assert result["target_df"] is None
    assert result["clean_df"].empty is False
    assert result["metrics_quality"]["target"] is None


def test_ingestion_ignores_available_target_for_inference(tmp_path):
    source = {
        "id_estudiante_anon": ["student-1"],
        "periodo_id": ["2025-1"],
        "sede": ["MED"],
    }
    pd.DataFrame(source).to_parquet(tmp_path / "estudiante_periodo_corte.parquet")
    pd.DataFrame(
        {
            "id_estudiante_anon": ["student-1"],
            "periodo_id": ["2025-1"],
            "target_desercion": [9],
        }
    ).to_parquet(tmp_path / "target_trazabilidad.parquet")

    result = AgentIngestion().run({"data_dir": str(tmp_path)})

    assert result["target_df"] is None


def test_azure_manifests_load_with_azure_ml_sdk():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RemovedInMarshmallow4Warning)
        from azure.ai.ml import (
            load_environment,
            load_job,
            load_online_deployment,
            load_online_endpoint,
        )

        assert load_job(ROOT / "azure" / "components" / "job.yaml").display_name == "sat-fumc-lightgbm-training-100k"
        assert load_job(ROOT / "azure" / "components" / "scoring_job.yaml").display_name == "sat-fumc-multiagent-scoring"
        assert load_environment(ROOT / "azure" / "environments" / "online-environment.yaml").name == "sat-fumc-online"
        assert load_online_endpoint(ROOT / "azure" / "endpoints" / "endpoint.yaml").name == "sat-fumc-endpoint"
        assert load_online_deployment(ROOT / "azure" / "endpoints" / "deployment.yaml").name == "blue"


def test_dashboard_generates_aggregate_only_html(tmp_path):
    from dashboards.render_summary import render_dashboard

    data = pd.DataFrame(
        {
            "id_estudiante_anon": ["private-id-1", "private-id-2"],
            "programa": ["A", "B"],
            "sede": ["MED", "CAL"],
            "probabilidad_desercion": [0.2, 0.8],
            "nivel_riesgo": ["Bajo", "Crítico"],
            "alerta_activa": [False, True],
            "intervencion_sugerida": ["Seguimiento", "Tutoría"],
        }
    )

    output = render_dashboard(data, tmp_path / "dashboard.html")
    rendered = output.read_text(encoding="utf-8")

    assert "Estudiantes evaluados" in rendered
    assert "Riesgo por programa" in rendered
    assert "private-id-1" not in rendered
