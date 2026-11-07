import pytest
import pandas as pd
from pathlib import Path
import joblib

def test_raw_data_exists():
    raw_dir = Path("./data/raw")
    assert (raw_dir / "estudiante_periodo_corte.parquet").exists()
    assert (raw_dir / "target_trazabilidad.parquet").exists()

def test_model_artifact_exists():
    model_path = Path("./outputs/sat_fumc_lightgbm.joblib")
    assert model_path.exists()
    model = joblib.load(model_path)
    assert hasattr(model, "predict_proba")

def test_azure_config_exists():
    cfg_path = Path("./config.json")
    assert cfg_path.exists()

def test_multiagent_output_exists():
    out_dir = Path("./outputs")
    assert (out_dir / "predicciones_multiagente_powerbi.parquet").exists()
    assert (out_dir / "reporte_ejecucion_multiagente.json").exists()
    
    df = pd.read_parquet(out_dir / "predicciones_multiagente_powerbi.parquet")
    assert "probabilidad_desercion" in df.columns
    assert "nivel_riesgo" in df.columns
    assert "intervencion_sugerida" in df.columns
    assert len(df) > 0
