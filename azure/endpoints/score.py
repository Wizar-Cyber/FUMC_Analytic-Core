import json
import os
import sys
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

PROJECT_ROOT = None
for candidate in [Path(__file__).resolve().parent, *Path(__file__).resolve().parents]:
    if (candidate / "src").is_dir():
        PROJECT_ROOT = candidate
        break
if PROJECT_ROOT is None:
    raise ImportError(
        "No se encontró un directorio con 'src/' dentro del bundle de Azure ML. "
        "Asegúrate de enviar el código completo junto con score.py."
    )
sys.path.insert(0, str(PROJECT_ROOT))
from src.ml.feature_engineering import engineer_features

model = None
threshold = float(os.getenv("ALERT_THRESHOLD", "0.35"))
max_batch_size = int(os.getenv("MAX_BATCH_SIZE", "1000"))


def init():
    """Load the registered sklearn model once when the Azure endpoint starts."""
    global model
    model_dir = Path(os.getenv("AZUREML_MODEL_DIR", "."))
    candidates = [
        model_dir / "sat_fumc_lightgbm.joblib",
        model_dir / "model.pkl",
        model_dir / "outputs" / "sat_fumc_lightgbm.joblib",
    ]
    model_path = next((path for path in candidates if path.is_file()), None)
    if model_path is None:
        raise FileNotFoundError(
            "No se encontró el modelo registrado. Rutas comprobadas: "
            + ", ".join(str(path) for path in candidates)
        )
    model = joblib.load(model_path)
    if not callable(getattr(model, "predict_proba", None)):
        raise TypeError(f"El artefacto {model_path.name} no implementa predict_proba.")
    if not 0 <= threshold <= 1:
        raise ValueError("ALERT_THRESHOLD debe estar entre 0 y 1.")
    if max_batch_size < 1:
        raise ValueError("MAX_BATCH_SIZE debe ser mayor que cero.")


def run(raw_data: Any):
    """Score one bounded batch of student records using the registered model."""
    if model is None:
        raise RuntimeError("El modelo no está inicializado; Azure debe ejecutar init() primero.")

    try:
        payload = json.loads(raw_data) if isinstance(raw_data, (str, bytes, bytearray)) else raw_data
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("El cuerpo de la solicitud debe ser JSON válido.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("El JSON debe contener la propiedad 'data' como lista de registros.")
    if not payload["data"]:
        raise ValueError("La lista 'data' no puede estar vacía.")
    if len(payload["data"]) > max_batch_size:
        raise ValueError(f"El lote excede el máximo permitido de {max_batch_size} registros.")
    if not all(isinstance(record, dict) for record in payload["data"]):
        raise ValueError("Cada elemento de 'data' debe ser un objeto JSON.")

    data = engineer_features(pd.DataFrame.from_records(payload["data"]))
    expected_features = list(getattr(model, "feature_names_in_", []))
    if not expected_features:
        raise ValueError("El modelo no expone feature_names_in_; no se puede validar su contrato.")
    missing_features = [name for name in expected_features if name not in data.columns]
    if missing_features:
        raise ValueError(f"Faltan variables requeridas por el modelo: {missing_features}")

    probabilities = model.predict_proba(data[expected_features])[:, 1]
    if not pd.Series(probabilities).map(lambda value: pd.notna(value) and 0 <= value <= 1).all():
        raise ValueError("El modelo devolvió probabilidades inválidas.")

    predictions = []
    for probability in probabilities:
        probability = float(probability)
        risk_level = (
            "Crítico" if probability >= 0.75
            else "Alto" if probability >= 0.50
            else "Medio" if probability >= 0.25
            else "Bajo"
        )
        predictions.append({
            "probabilidad_desercion": round(probability, 4),
            "nivel_riesgo": risk_level,
            "alerta_activa": probability >= threshold,
        })

    return {"status": "success", "predictions": predictions}
