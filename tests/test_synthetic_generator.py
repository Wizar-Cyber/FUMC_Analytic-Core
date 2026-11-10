import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "src" / "data_generation" / "generate_digital_twin.py"


def _generate(tmp_path, *, students=300, scenario="baseline", seed=42):
    output = tmp_path / "dataset"
    environment = os.environ.copy()
    environment.update(
        {
            "SAT_SYNTHETIC_STUDENTS": str(students),
            "SAT_SYNTHETIC_SEED": str(seed),
            "SAT_SYNTHETIC_SCENARIO": scenario,
            "SAT_OUTPUT_DIR": str(output),
        }
    )
    subprocess.run(
        [sys.executable, str(GENERATOR)],
        check=True,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    return output


def test_generator_writes_future_mature_targets_and_reproducibility_manifest(tmp_path):
    output = _generate(tmp_path)

    main = pd.read_parquet(output / "estudiante_periodo_corte.parquet")
    target = pd.read_parquet(output / "target_trazabilidad.parquet")
    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    merged = main[["id_estudiante_anon", "periodo_id"]].merge(
        target,
        on=["id_estudiante_anon", "periodo_id"],
        validate="one_to_one",
    )
    mature = merged[merged["target_observado"]]
    immature = merged[~merged["target_observado"]]

    assert manifest["students_observed"] == 300
    assert manifest["generator_version"] == "2.0.0"
    assert manifest["dataset_version"]
    assert manifest["parquet_sha256"]
    assert set(mature["target_desercion"].dropna().unique()) == {0, 1}
    assert immature["target_desercion"].isna().all()
    period_order = lambda value: int(value[:4]) * 2 + int(value[5])
    assert all(
        period_order(start) > period_order(period)
        for period, start in zip(
            mature["periodo_id"], mature["periodo_inicio_horizonte"]
        )
    )
    assert not {
        "target_desercion",
        "target_observado",
        "evento_simulado",
        "probabilidad_riesgo_simulada",
        "nivel_riesgo_simulado",
    }.intersection(main.columns)
    assert set(main["periodo_id"]).issubset(set(manifest["periods"]))


def test_generator_refuses_nonempty_output_directory_without_explicit_override(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("preserve", encoding="utf-8")
    environment = os.environ.copy()
    environment.update(
        {
            "SAT_SYNTHETIC_STUDENTS": "20",
            "SAT_OUTPUT_DIR": str(output),
        }
    )

    result = subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "ya contiene archivos" in result.stderr
    assert (output / "keep.txt").read_text(encoding="utf-8") == "preserve"
