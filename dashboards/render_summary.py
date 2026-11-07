"""Render a self-contained, aggregate-only HTML report from scored records."""

import base64
import os
import tempfile
from io import BytesIO
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "sat-fumc-matplotlib"),
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from html import escape


REQUIRED_COLUMNS = {
    "probabilidad_desercion",
    "nivel_riesgo",
    "programa",
    "sede",
    "intervencion_sugerida",
}


def _chart_data_uri(plotter) -> str:
    figure, axis = plt.subplots(figsize=(8, 4))
    plotter(axis)
    figure.tight_layout()
    image = BytesIO()
    figure.savefig(image, format="png", dpi=130, bbox_inches="tight")
    plt.close(figure)
    return "data:image/png;base64," + base64.b64encode(image.getvalue()).decode("ascii")


def render_dashboard(scored_data: pd.DataFrame, output_path: str | Path) -> Path:
    """Write an offline HTML dashboard containing aggregate statistics only."""
    missing = sorted(REQUIRED_COLUMNS - set(scored_data.columns))
    if missing:
        raise ValueError(f"Faltan columnas para el dashboard: {missing}")
    if scored_data.empty:
        raise ValueError("No se puede generar un dashboard sin predicciones.")

    risk_order = ["Bajo", "Medio", "Alto", "Crítico"]
    risk_counts = scored_data["nivel_riesgo"].value_counts().reindex(risk_order, fill_value=0)
    high_risk = scored_data["nivel_riesgo"].isin(["Alto", "Crítico"])
    rates_by_site = (
        scored_data.assign(riesgo_alto=high_risk)
        .groupby("sede", dropna=False)["riesgo_alto"]
        .mean()
        .mul(100)
        .sort_values(ascending=True)
    )
    intervention_counts = scored_data["intervencion_sugerida"].value_counts().head(10).sort_values()
    probabilities = pd.to_numeric(scored_data["probabilidad_desercion"], errors="coerce").dropna()
    if probabilities.empty or not probabilities.between(0, 1).all():
        raise ValueError("Las probabilidades deben ser numéricas y estar entre 0 y 1.")

    charts = [
        _chart_data_uri(
            lambda axis: (
                risk_counts.plot(kind="bar", color=["#2e7d32", "#f9a825", "#ef6c00", "#c62828"], ax=axis),
                axis.set(title="Estudiantes por nivel de riesgo", xlabel="", ylabel="Estudiantes"),
                axis.tick_params(axis="x", rotation=0),
            )
        ),
        _chart_data_uri(
            lambda axis: (
                rates_by_site.plot(kind="barh", color="#1565c0", ax=axis),
                axis.set(title="Porcentaje en riesgo alto/crítico por sede", xlabel="Porcentaje", ylabel=""),
            )
        ),
        _chart_data_uri(
            lambda axis: (
                intervention_counts.plot(kind="barh", color="#00897b", ax=axis),
                axis.set(title="Intervenciones sugeridas más frecuentes", xlabel="Estudiantes", ylabel=""),
            )
        ),
        _chart_data_uri(
            lambda axis: (
                axis.hist(probabilities, bins=20, color="#5e35b1", edgecolor="white"),
                axis.set(title="Distribución de probabilidad de deserción", xlabel="Probabilidad", ylabel="Estudiantes"),
            )
        ),
    ]

    total = len(scored_data)
    high_risk_count = int(high_risk.sum())
    active_alerts = (
        int(pd.to_numeric(scored_data["alerta_activa"], errors="coerce").fillna(0).sum())
        if "alerta_activa" in scored_data
        else high_risk_count
    )
    cards = (
        ("Estudiantes evaluados", f"{total:,}"),
        ("Riesgo alto/crítico", f"{high_risk_count:,} ({high_risk_count / total:.1%})"),
        ("Alertas activas", f"{active_alerts:,}"),
        ("Probabilidad promedio", f"{probabilities.mean():.1%}"),
    )
    card_html = "".join(
        f'<section class="card"><span>{escape(label)}</span><strong>{escape(value)}</strong></section>'
        for label, value in cards
    )
    chart_html = "".join(
        f'<section class="chart"><img alt="{escape(title)}" src="{uri}"></section>'
        for title, uri in zip(
            (
                "Estudiantes por nivel de riesgo",
                "Riesgo alto o crítico por sede",
                "Intervenciones sugeridas",
                "Distribución de probabilidades",
            ),
            charts,
        )
    )
    program_summary = (
        scored_data.assign(riesgo_alto=high_risk)
        .groupby("programa", dropna=False)
        .agg(estudiantes=("riesgo_alto", "size"), riesgo_alto_pct=("riesgo_alto", "mean"))
        .assign(riesgo_alto_pct=lambda table: (table["riesgo_alto_pct"] * 100).round(1))
        .sort_values("riesgo_alto_pct", ascending=False)
        .rename_axis("Programa")
        .reset_index()
    )
    table_html = program_summary.to_html(index=False, border=0, escape=True, classes="summary")
    html = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Resumen SAT-FUMC</title>
<style>
body{{font-family:Arial,sans-serif;margin:2rem;color:#17324d;background:#f4f7fb}}
h1{{margin-bottom:.25rem}} .subtitle{{color:#526579;margin-top:0}}
.cards,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}}
.card,.chart,.table{{background:white;border-radius:8px;padding:1rem;box-shadow:0 1px 5px #ccd5df}}
.card span,.card strong{{display:block}} .card strong{{font-size:1.6rem;margin-top:.5rem}}
.chart img{{width:100%;height:auto}} .table{{margin-top:1rem;overflow-x:auto}}
table{{border-collapse:collapse;width:100%}} th,td{{padding:.6rem;border-bottom:1px solid #e5eaf0;text-align:left}}
footer{{margin-top:1.5rem;color:#687b8f;font-size:.85rem}}
</style></head><body>
<h1>Sistema de alerta temprana — SAT-FUMC</h1>
<p class="subtitle">Resumen agregado de la última ejecución. No incluye identificadores individuales.</p>
<div class="cards">{card_html}</div>
<div class="grid">{chart_html}</div>
<section class="table"><h2>Riesgo por programa</h2>{table_html}</section>
<footer>Los niveles de riesgo son apoyo para priorización; no constituyen una decisión automatizada sobre el estudiante.</footer>
</body></html>"""

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output.with_suffix(output.suffix + ".tmp")
    temp_path.write_text(html, encoding="utf-8")
    temp_path.replace(output)
    return output
