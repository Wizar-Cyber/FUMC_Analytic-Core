"""Consolida resultados de recalibración: matriz, estadística, curvas y tablas Markdown.

Salidas en outputs/recalibration/: matriz_consolidada.csv, tablas.md, estadistica.json, figs/*.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import precision_recall_curve, roc_curve

BASE = Path(__file__).resolve().parents[1] / "outputs" / "recalibration"
OUT = BASE
FIG = OUT / "figs"
SIZES = [5000, 10000, 15000, 25000, 50000, 75000, 100000]
BLUES = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#1c5cab", "#104281"]
INK, MUTED, GRID, ORANGE = "#0b0b0b", "#52514e", "#e1e0d9", "#eb6834"
FINAL = "FINAL_logit_C0.1"

plt.rcParams.update({
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "font.size": 9, "legend.frameon": False,
})


def md(df: pd.DataFrame, floatfmt: int = 3) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---:" if i else "---" for i in range(len(cols))) + "|"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            cells.append(f"{v:,.{floatfmt}f}" if isinstance(v, (float, np.floating)) else (f"{v:,}" if isinstance(v, (int, np.integer)) else str(v)))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


STAGES = None
SCORES_STAGE = "final_project"


def load_results() -> pd.DataFrame:
    paths = sorted(BASE.glob("results_*.csv"))
    if STAGES:
        paths = [BASE / f"results_{name}.csv" for name in STAGES]
    frames = [pd.read_csv(p) for p in paths]
    return pd.concat(frames, ignore_index=True)


def ci95(x: pd.Series) -> float:
    x = x.dropna()
    return float(stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else float("nan")


def min_alert_for_recall(y: np.ndarray, p: np.ndarray, target: float = 0.80):
    order = np.argsort(-p, kind="mergesort")
    ys = y[order]
    cum = np.cumsum(ys) / ys.sum()
    k = int(np.searchsorted(cum, target) + 1)
    k = min(k, len(ys))
    return k / len(ys), ys[:k].sum() / k


def recall_at(y, p, rate):
    k = max(1, int(round(rate * len(p))))
    order = np.argsort(-p, kind="mergesort")
    return y[order[:k]].sum() / y.sum(), y[order[:k]].mean()


def auc_fast(y, p):
    from sklearn.metrics import roc_auc_score
    return roc_auc_score(y, p)


def bootstrap_by_student(sc: pd.DataFrame, n_boot: int = 400, seed: int = 0):
    rng = np.random.default_rng(seed)
    groups = {s: i for i, s in enumerate(sc.student.unique())}
    sid = sc.student.map(groups).values
    idx_by = [np.where(sid == g)[0] for g in range(len(groups))]
    y, p, o = sc.y.values, sc.p.values, sc.oracle.values
    out = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(idx_by), len(idx_by))
        ii = np.concatenate([idx_by[g] for g in pick])
        yb, pb, ob = y[ii], p[ii], o[ii]
        r40, p40 = recall_at(yb, pb, 0.40)
        r50, p50 = recall_at(yb, pb, 0.50)
        a80, pr80 = min_alert_for_recall(yb, pb, 0.80)
        out.append({"auc": auc_fast(yb, pb), "auc_oracle": auc_fast(yb, ob), "recall40": r40, "prec40": p40,
                    "recall50": r50, "alert_for_r80": a80, "prec_at_r80": pr80})
    return pd.DataFrame(out)


def main():
    global OUT, FIG, STAGES, SCORES_STAGE
    ap = argparse.ArgumentParser()
    ap.add_argument("--stages", nargs="*", default=None, help="etapas (results_<x>.csv) a incluir")
    ap.add_argument("--subdir", default=None, help="subcarpeta de salida dentro de outputs/recalibration")
    ap.add_argument("--scores-stage", default="final_project")
    args = ap.parse_args()
    STAGES, SCORES_STAGE = args.stages, args.scores_stage
    if args.subdir:
        OUT = BASE / args.subdir
    FIG = OUT / "figs"
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(exist_ok=True)
    res = load_results()
    key = ["stage", "config", "size", "seed", "test_periods", "policy"]
    cols = key + ["n_val", "n_test", "n_test_students", "prevalence", "val_prevalence", "auc_roc", "auc_pr", "brier", "ece",
                  "oracle_auc_test", "recall", "precision", "f1", "specificity", "fpr", "alert_rate", "threshold",
                  "tp", "fp", "fn", "tn", "val_auc_roc", "val_auc_pr"]
    res[cols].to_csv(OUT / "matriz_consolidada.csv", index=False)
    text = []
    stats_out = {}

    # ---------------- A. Evolución por etapa (media y desviación ENTRE tamaños, semilla 42)
    seed42 = res[(res.seed == 42) & (res.test_periods == "2025-1,2025-2")]
    agg = (seed42.groupby(["stage", "config", "policy"])
           .agg(tamanos=("size", "nunique"), auc=("auc_roc", "mean"), auc_sd=("auc_roc", "std"), aucpr=("auc_pr", "mean"),
                brier=("brier", "mean"), ece=("ece", "mean"), recall=("recall", "mean"), recall_sd=("recall", "std"),
                precision=("precision", "mean"), f1=("f1", "mean"), alertas=("alert_rate", "mean"), alertas_sd=("alert_rate", "std"))
           .reset_index())
    agg = agg[agg.tamanos >= 6]
    agg.to_csv(OUT / "resumen_etapas.csv", index=False)
    for pol in ("recall80_val", "cap40_topk"):
        t = agg[(agg.policy == pol) & (~agg.stage.isin(["s2_hp"]))].drop(columns=["policy", "tamanos"])
        text.append(f"### Evolución por ajuste — política `{pol}` (semilla 42; media y sd entre tamaños)\n\n{md(t)}\n")

    # ---------------- B. Matriz por tamaño (semilla 42): baseline vs final
    def per_size(config, pols):
        d = seed42[(seed42.config == config) & (seed42.policy.isin(pols))].sort_values(["policy", "size"])
        return d[["policy", "size", "n_test", "prevalence", "auc_roc", "oracle_auc_test", "auc_pr", "recall", "precision", "f1",
                  "specificity", "fpr", "alert_rate"]]
    base_cfg = "S0_lgbm_project"
    text.append("### Matriz por tamaño — baseline del proyecto (LightGBM, regla recall≥0,80 en validación)\n\n"
                + md(per_size(base_cfg, ["recall80_val"]).drop(columns="policy")) + "\n")
    for pol in ("recall80_val", "cap40_topk", "cap50_topk"):
        text.append(f"### Matriz por tamaño — configuración final, política `{pol}` (semilla 42)\n\n"
                    + md(per_size(FINAL, [pol]).drop(columns="policy")) + "\n")

    # ---------------- C. Estabilidad multi-semilla (final)
    fin = res[res.config == FINAL]
    stab_rows, stats_out["stability"] = [], {}
    for proto, label in (("2025-1,2025-2", "proyecto (test 2025-1/2)"), ("2024-1,2024-2", "ventana estacionaria (test 2024-1/2)")):
        d = fin[fin.test_periods == proto]
        for pol in ("cap40_topk", "recall80_val"):
            dd = d[d.policy == pol]
            for size, g in dd.groupby("size"):
                stab_rows.append({"protocolo": label, "politica": pol, "tamano": size, "semillas": g.seed.nunique(),
                                  "AUC": g.auc_roc.mean(), "AUC_ic95": ci95(g.auc_roc), "AUC_sd": g.auc_roc.std(),
                                  "recall": g.recall.mean(), "recall_ic95": ci95(g.recall), "recall_sd": g.recall.std(),
                                  "precision": g.precision.mean(), "precision_sd": g.precision.std(),
                                  "F1": g.f1.mean(), "alertas": g.alert_rate.mean(), "alertas_sd": g.alert_rate.std()})
    stab = pd.DataFrame(stab_rows)
    stab.to_csv(OUT / "estabilidad_multisemilla.csv", index=False)
    for (proto, pol), g in stab.groupby(["protocolo", "politica"]):
        text.append(f"### Estabilidad entre semillas — {proto}, política `{pol}`\n\n"
                    + md(g.drop(columns=["protocolo", "politica"])) + "\n")

    # heterogeneidad entre tamaños (ANOVA / Kruskal) y tendencia con n
    for proto in ("2025-1,2025-2", "2024-1,2024-2"):
        d = fin[(fin.test_periods == proto) & (fin.policy == "cap40_topk")]
        if d.empty:
            continue
        groups = [g.recall.values for _, g in d.groupby("size")]
        groupsA = [g.auc_roc.values for _, g in d.groupby("size")]
        f_r, p_r = stats.f_oneway(*groups)
        f_a, p_a = stats.f_oneway(*groupsA)
        rho, p_rho = stats.spearmanr(d["size"], d["recall"])
        sd_by = d.groupby("size").recall.std()
        stats_out["stability"][proto] = {
            "anova_recall_cap40_F": f_r, "anova_recall_p": p_r, "anova_auc_F": f_a, "anova_auc_p": p_a,
            "spearman_size_vs_recall": rho, "spearman_p": p_rho,
            "recall_sd_5k": float(sd_by.get(5000, np.nan)), "recall_sd_100k": float(sd_by.get(100000, np.nan)),
            "recall_mean_all": float(d.recall.mean()), "recall_ic95_all": ci95(d.recall),
            "auc_mean_all": float(d.auc_roc.mean()),
            "ttest_recall_vs_0.80_p": float(stats.ttest_1samp(d.recall, 0.80).pvalue),
            "runs": int(len(d)),
        }
        dp = fin[(fin.test_periods == proto) & (fin.policy == "recall80_val")]
        stats_out["stability"][proto]["recall80_val_alert_mean"] = float(dp.alert_rate.mean())
        stats_out["stability"][proto]["recall80_val_alert_min"] = float(dp.alert_rate.min())
        stats_out["stability"][proto]["recall80_val_recall_mean"] = float(dp.recall.mean())
        stats_out["stability"][proto]["recall80_val_runs_alert_le_50"] = int((dp.alert_rate <= 0.5).sum())
        stats_out["stability"][proto]["recall80_val_runs_recall_ge_075"] = int((dp.recall >= 0.75).sum())
        stats_out["stability"][proto]["recall80_val_runs_both"] = int(((dp.alert_rate <= 0.5) & (dp.recall >= 0.75)).sum())

    # criterio de promovibilidad por corrida
    crit = []
    for proto in ("2025-1,2025-2", "2024-1,2024-2"):
        for pol in ("recall80_val", "cap40_topk", "cap50_topk"):
            d = fin[(fin.test_periods == proto) & (fin.policy == pol)]
            if d.empty:
                continue
            ok = (d.recall >= 0.75) & (d.alert_rate <= 0.50) & (d.precision >= 0.30)
            crit.append({"protocolo": proto, "politica": pol, "corridas": len(d), "recall>=0.75": int((d.recall >= 0.75).sum()),
                         "alertas<=50%": int((d.alert_rate <= 0.5).sum()), "precision>=0.30": int((d.precision >= 0.30).sum()),
                         "cumple_los_3": int(ok.sum())})
    crit = pd.DataFrame(crit)
    text.append("### Criterio de promovibilidad por corrida (recall≥0,75, alertas≤50 %, precisión≥0,30)\n\n" + md(crit) + "\n")
    stats_out["criteria"] = crit.to_dict("records")

    # modelo vs oráculo por tamaño (semillas)
    d = fin[(fin.test_periods == "2025-1,2025-2") & (fin.policy == "cap40_topk")]
    gap = d.groupby("size").apply(lambda g: pd.Series({"AUC_modelo": g.auc_roc.mean(), "AUC_oraculo": g.oracle_auc_test.mean(),
                                                         "brecha_media": (g.oracle_auc_test - g.auc_roc).mean(),
                                                         "brecha_ic95": ci95(g.oracle_auc_test - g.auc_roc)})).reset_index()
    text.append("### Modelo vs. oráculo (techo teórico del generador), protocolo del proyecto, 10 semillas\n\n" + md(gap) + "\n")
    stats_out["oracle_gap"] = gap.to_dict("records")

    # ---------------- D. Bootstrap por estudiante (semilla 42) + curvas
    sc_dir = BASE / "scores" / SCORES_STAGE
    boots, curves, brow = {}, {}, []
    for size in SIZES:
        f = sc_dir / f"{FINAL}_n{size}_s42.parquet"
        if not f.exists():
            continue
        sc = pd.read_parquet(f)
        curves[size] = sc
        b = bootstrap_by_student(sc)
        boots[size] = b
        q = lambda c: (b[c].quantile(.025), b[c].quantile(.975))  # noqa: E731
        brow.append({"tamano": size, "estudiantes_test": sc.student.nunique(), "AUC": auc_fast(sc.y, sc.p),
                     "AUC_lo": q("auc")[0], "AUC_hi": q("auc")[1],
                     "recall@40%": recall_at(sc.y.values, sc.p.values, .4)[0], "r40_lo": q("recall40")[0], "r40_hi": q("recall40")[1],
                     "precision@40%": recall_at(sc.y.values, sc.p.values, .4)[1],
                     "alertas_para_recall80": min_alert_for_recall(sc.y.values, sc.p.values)[0],
                     "a80_lo": q("alert_for_r80")[0], "a80_hi": q("alert_for_r80")[1],
                     "precision_con_recall80": min_alert_for_recall(sc.y.values, sc.p.values)[1]})
    bt = pd.DataFrame(brow)
    bt.to_csv(OUT / "bootstrap_estudiantes.csv", index=False)
    text.append("### Intervalos bootstrap por estudiante (400 remuestras, semilla 42, config final)\n\n" + md(bt) + "\n")
    stats_out["bootstrap"] = bt.to_dict("records")

    if curves:
        pooled = pd.concat(curves.values(), ignore_index=True)
        # PR / ROC
        fig, ax = plt.subplots(1, 2, figsize=(11, 4.4))
        for (size, sc), c in zip(curves.items(), BLUES):
            pr, rc, _ = precision_recall_curve(sc.y, sc.p)
            fpr, tpr, _ = roc_curve(sc.y, sc.p)
            ax[0].plot(rc, pr, color=c, lw=1.6, label=f"{size:,}".replace(",", "."))
            ax[1].plot(fpr, tpr, color=c, lw=1.6, label=f"{size:,}".replace(",", "."))
        pr, rc, _ = precision_recall_curve(pooled.y, pooled.oracle)
        fpr, tpr, _ = roc_curve(pooled.y, pooled.oracle)
        ax[0].plot(rc, pr, color=MUTED, ls="--", lw=1.6, label="Oráculo (techo)")
        ax[1].plot(fpr, tpr, color=MUTED, ls="--", lw=1.6, label="Oráculo (techo)")
        ax[0].axhline(pooled.y.mean(), color=ORANGE, lw=1, ls=":")
        ax[0].text(0.02, pooled.y.mean() + 0.01, "prevalencia (azar)", color=MUTED, fontsize=8)
        ax[0].axvline(0.80, color=GRID, lw=1.2)
        ax[1].plot([0, 1], [0, 1], color=ORANGE, lw=1, ls=":")
        ax[0].set(xlabel="Recall", ylabel="Precisión", title="Curvas Precision–Recall por tamaño (test)")
        ax[1].set(xlabel="Tasa de falsos positivos", ylabel="Recall (TPR)", title="Curvas ROC por tamaño (test)")
        ax[0].legend(title="Estudiantes", fontsize=8, ncol=2)
        fig.tight_layout()
        fig.savefig(FIG / "curvas_pr_roc.png", dpi=150)
        plt.close(fig)

        # recall vs carga operativa
        fig, ax = plt.subplots(figsize=(7.2, 4.6))
        rates = np.linspace(0.02, 1.0, 50)
        ax.axvspan(0.40, 0.50, color="#cde2fb", alpha=0.6, lw=0)
        ax.text(0.405, 0.03, "capacidad\n40–50 %", fontsize=8, color=MUTED)
        for (size, sc), c in zip(curves.items(), BLUES):
            ax.plot(rates, [recall_at(sc.y.values, sc.p.values, r)[0] for r in rates], color=c, lw=1.6, label=f"{size:,}".replace(",", "."))
        ax.plot(rates, [recall_at(pooled.y.values, pooled.oracle.values, r)[0] for r in rates], color=MUTED, ls="--", lw=1.8, label="Oráculo (techo)")
        ax.axhline(0.80, color=ORANGE, lw=1.2)
        ax.text(0.01, 0.815, "recall objetivo 0,80", color=MUTED, fontsize=8)
        ax.set(xlabel="Estudiantes alertados (% del total)", ylabel="Recall", xlim=(0, 1), ylim=(0, 1.02),
               title="Carga operativa: recall alcanzable según % de alertas")
        ax.legend(title="Estudiantes", fontsize=8, ncol=2, loc="lower right")
        fig.tight_layout()
        fig.savefig(FIG / "recall_vs_alertas.png", dpi=150)
        plt.close(fig)

    # evolución por tamaño con IC95 entre semillas
    d = fin[(fin.test_periods == "2025-1,2025-2")]
    fig, axs = plt.subplots(2, 3, figsize=(11, 6))
    panels = [("auc_roc", "cap40_topk", "AUC-ROC"), ("auc_pr", "cap40_topk", "AUC-PR"), ("recall", "cap40_topk", "Recall (40 % alertas)"),
              ("precision", "cap40_topk", "Precisión (40 % alertas)"), ("f1", "cap40_topk", "F1 (40 % alertas)"),
              ("alert_rate", "recall80_val", "% alertas, regla recall≥0,80")]
    for ax, (m, pol, title) in zip(axs.ravel(), panels):
        g = d[d.policy == pol].groupby("size")[m]
        mean, err = g.mean(), g.apply(ci95)
        ax.errorbar(mean.index, mean.values, yerr=err.values, color=BLUES[4], marker="o", ms=5, lw=1.6, capsize=3)
        if m == "auc_roc":
            o = d[d.policy == pol].groupby("size").oracle_auc_test.mean()
            ax.plot(o.index, o.values, color=MUTED, ls="--", marker="s", ms=4, lw=1.2, label="Oráculo")
            ax.legend(fontsize=8)
        if m == "recall":
            ax.axhline(0.80, color=ORANGE, lw=1)
        ax.set_xscale("log")
        ax.set_xticks(SIZES)
        ax.set_xticklabels([f"{s//1000}k" for s in SIZES], fontsize=8)
        ax.minorticks_off()
        ax.set(title=title, xlabel="Estudiantes simulados")
    fig.suptitle("Evolución por tamaño de muestra — media e IC95 % entre 10 semillas", y=0.995)
    fig.tight_layout()
    fig.savefig(FIG / "metricas_por_tamano.png", dpi=150)
    plt.close(fig)

    # dispersión entre semillas por protocolo
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for a, proto, title in ((ax[0], "2025-1,2025-2", "Protocolo del proyecto (test 2025)"), (ax[1], "2024-1,2024-2", "Ventana estacionaria (test 2024)")):
        dd = fin[(fin.test_periods == proto) & (fin.policy == "cap40_topk")]
        data = [dd[dd["size"] == s].recall.values for s in SIZES]
        bp = a.boxplot(data, positions=range(len(SIZES)), widths=0.55, patch_artist=True, showfliers=True,
                       medianprops=dict(color=INK), flierprops=dict(markersize=3, markeredgecolor=MUTED))
        for patch in bp["boxes"]:
            patch.set(facecolor="#9ec5f4", edgecolor="#256abf")
        a.axhline(0.80, color=ORANGE, lw=1)
        a.set_xticks(range(len(SIZES)))
        a.set_xticklabels([f"{s//1000}k" for s in SIZES])
        a.set(title=title, xlabel="Estudiantes simulados", ylim=(0.35, 0.9))
    ax[0].set_ylabel("Recall con 40 % de alertas")
    fig.tight_layout()
    fig.savefig(FIG / "estabilidad_semillas.png", dpi=150)
    plt.close(fig)

    (OUT / "tablas.md").write_text("\n".join(text), encoding="utf-8")
    (OUT / "estadistica.json").write_text(json.dumps(stats_out, indent=2, default=float), encoding="utf-8")
    print("OK")


if __name__ == "__main__":
    main()
