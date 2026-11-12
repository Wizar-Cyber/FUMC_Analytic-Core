"""Evaluación independiente del modelo registrado (no reentrena ni reajusta el umbral).

Carga el modelo desde el registro de Azure ML (o un .joblib/.pkl local), reconstruye el
mismo split temporal por estudiante que usa el entrenamiento y evalúa SOLO sobre la
partición de prueba con el umbral fijado en validación (atributo decision_threshold_).

Uso:
  python scripts/evaluate_model.py --data_dir data/raw
  python scripts/evaluate_model.py --data_dir <carpeta> --model_version 3
  python scripts/evaluate_model.py --data_dir <carpeta> --model_path outputs/model.joblib

Los resultados son de datos sintéticos; no constituyen validación institucional.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    roc_auc_score,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.agent_ingestion import AgentIngestion  # noqa: E402
from src.agents.agent_quality import AgentQuality  # noqa: E402
from src.ml.feature_engineering import (  # noqa: E402
    engineer_features,
    join_mature_targets,
    require_feature_schema,
    temporal_group_train_validation_test_split,
)
from src.ml.model_selection import classification_metrics  # noqa: E402


def load_registered_model(name: str, version: str | None, download_dir: Path):
    from azure.ai.ml import MLClient
    from azure.identity import DefaultAzureCredential

    config = json.loads((ROOT / "azure" / "config.json").read_text(encoding="utf-8"))
    client = MLClient(
        DefaultAzureCredential(),
        config["subscription_id"],
        config["resource_group"],
        config["workspace_name"],
    )
    if version is None:
        version = max((m.version for m in client.models.list(name)), key=int)
    client.models.download(name=name, version=version, download_path=str(download_dir))
    artifact = next(
        (p for p in download_dir.rglob("*") if p.name in {"model.pkl", "sat_fumc_lightgbm.joblib"}),
        None,
    )
    if artifact is None:
        raise FileNotFoundError(f"No se encontró un artefacto de modelo en {download_dir}")
    return joblib.load(artifact), version


def evaluate(model, data_dir: Path, test_periods: list[str] | None) -> dict:
    threshold = getattr(model, "decision_threshold_", None)
    if threshold is None:
        raise ValueError("El modelo no expone decision_threshold_: no hay umbral fijado en validación.")
    threshold = float(threshold)

    ingested = AgentIngestion().run({"data_dir": str(data_dir), "require_target": True})
    quality = AgentQuality().run(ingested)
    df = join_mature_targets(quality["clean_df"], quality["target_df"])
    require_feature_schema(df)
    df = engineer_features(df)

    _, validation_mask, _, test_mask, validation_periods, resolved_test_periods = (
        temporal_group_train_validation_test_split(
            df, test_periods=test_periods, number_of_test_periods=2, number_of_validation_periods=1
        )
    )
    features = list(model.feature_names_in_)
    y_test = df.loc[test_mask, "target_desercion"].to_numpy()
    y_validation = df.loc[validation_mask, "target_desercion"].to_numpy()
    p_test = model.predict_proba(df.loc[test_mask, features])[:, 1]
    p_validation = model.predict_proba(df.loc[validation_mask, features])[:, 1]
    if len(np.unique(y_test)) < 2:
        raise ValueError("La partición de prueba debe contener ambas clases.")

    predicted = p_test >= threshold
    tn, fp, fn, tp = confusion_matrix(y_test, predicted, labels=[0, 1]).ravel()
    test = classification_metrics(y_test, p_test, threshold)
    return {
        "threshold": threshold,
        "validation_periods": validation_periods,
        "test_periods": resolved_test_periods,
        "validation_recall": classification_metrics(y_validation, p_validation, threshold)["recall"],
        "test": {
            **test,
            "auc_roc": float(roc_auc_score(y_test, p_test)),
            "auc_pr": float(average_precision_score(y_test, p_test)),
            "brier_score": float(brier_score_loss(y_test, p_test)),
            "alert_rate": float(predicted.mean()),
            "n_records": int(len(y_test)),
            "prevalence": float(y_test.mean()),
        },
        "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data_dir", required=True)
    parser.add_argument("--model_name", default="SAT_FUMC_LightGBM_Model")
    parser.add_argument("--model_version", default=None)
    parser.add_argument("--model_path", default=None, help="Modelo local (.joblib/.pkl) en lugar del registro.")
    parser.add_argument("--minimum_recall", type=float, default=0.80)
    parser.add_argument("--test_periods", nargs="+", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    if args.model_path:
        model, version = joblib.load(args.model_path), f"local:{Path(args.model_path).name}"
    else:
        with tempfile.TemporaryDirectory() as temp_dir:
            model, version = load_registered_model(args.model_name, args.model_version, Path(temp_dir))

    result = evaluate(model, Path(args.data_dir), args.test_periods)
    recall = result["test"]["recall"]
    report = {
        "model_name": args.model_name,
        "model_version": str(version),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_dir": str(args.data_dir),
        "data_origin": "synthetic",
        "minimum_recall": args.minimum_recall,
        "recall_target_met": bool(recall >= args.minimum_recall),
        **result,
        "note": "Evaluación sobre datos sintéticos; no es validación institucional.",
    }
    output = Path(args.output) if args.output else ROOT / "outputs" / f"evaluation_{args.model_name}_v{str(version).replace(':', '_')}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["recall_target_met"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
