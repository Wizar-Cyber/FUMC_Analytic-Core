"""Re-puntúa todos los snapshots operativos contra la versión vigente del modelo.

Úsalo tras un reentrenamiento. Solo cambia ModelProbability, RiskLevel, ModelName,
ModelVersion y ScoredAt; los estados de casos, revisiones, alertas y seguimientos no se tocan.
Los estudiantes sembrados por el generador heredado (sin FeaturesJson) se omiten y se cuentan.

Uso:
  python scripts/rescore_students.py --dry-run
  python scripts/rescore_students.py
  python scripts/rescore_students.py --model-name SAT_FUMC_LightGBM_Model --model-version 3

Requiere AZURE_ML_ENDPOINT_URL, AZURE_ML_ENDPOINT_KEY (no se imprimen), BLOB_STORAGE_URL
y una sesión `az login` con rol Storage Table Data Contributor. Si el endpoint no
responde, el proceso falla sin modificar los lotes pendientes.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "azure" / "agent_platform"))

from sat_agents import synthetic_database as db  # noqa: E402
from sat_agents.rescoring import rescore_snapshots  # noqa: E402
from src.ml import endpoint_scoring as scoring  # noqa: E402


async def run(args: argparse.Namespace) -> dict:
    settings = scoring.settings_from_env()
    explicit = (args.model_name, args.model_version)
    model = scoring.resolve_model_info(settings, explicit=explicit)
    print(f"Modelo vigente: {model.name} v{model.version} (despliegue {settings.deployment})")

    def score_batch(batch):
        return scoring.score_records(
            batch, settings, batch_size=len(batch), timeout=args.timeout, retries=args.retries,
        )

    scored_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    async with db._table_clients() as tables:
        stats = await rescore_snapshots(
            tables[db.TABLE_SNAPSHOTS], score_batch,
            model_name=model.name, model_version=model.version, scored_at=scored_at,
            batch_size=args.batch_size, dry_run=args.dry_run, limit=args.limit,
        )
    after = scoring.resolve_model_info(settings, explicit=explicit)
    if after != model:
        print(f"AVISO: la versión vigente cambió durante el proceso ({model.version} -> {after.version}); vuelve a ejecutar.")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-name", default="")
    parser.add_argument("--model-version", default="")
    parser.add_argument("--batch-size", type=int, default=scoring.DEFAULT_BATCH_SIZE)
    parser.add_argument("--timeout", type=float, default=scoring.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--retries", type=int, default=scoring.DEFAULT_RETRIES)
    parser.add_argument("--limit", type=int, default=None, help="Máximo de snapshots a puntuar")
    parser.add_argument("--dry-run", action="store_true", help="Puntúa y resume sin escribir")
    args = parser.parse_args()
    try:
        stats = asyncio.run(run(args))
    except scoring.EndpointScoringError as error:
        raise SystemExit(f"Re-scoring abortado: {error}")
    print(
        f"Puntuados: {stats['scored']}  sin features (heredados): {stats['skipped_without_features']}  "
        f"cambios de nivel de riesgo: {stats['risk_changed']}  probabilidad media: {stats['mean_probability']:.3f}"
    )
    print("Dry-run: no se escribió nada." if args.dry_run else "Snapshots actualizados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
