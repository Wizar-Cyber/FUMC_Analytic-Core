"""Ejecuta etapas de experimentos de recalibración sobre los 7 tamaños sintéticos.

Uso:
  python scripts/recalibration_experiments.py --data-root <dir con n5000..n100000> \
      --stage <nombre> --configs <json con lista de configuraciones> [--seeds 42] \
      [--sizes 5000 10000] [--test-periods 2024-1 2024-2] [--save-scores]
Salida: outputs/recalibration/results_<stage>.csv (una fila por config x tamaño x semilla x política)
"""
from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import xgboost as xgb
from imblearn.over_sampling import RandomOverSampler
from imblearn.under_sampling import RandomUnderSampler
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from recalibration_lib import (
    RECONSTRUCTED, TRAJECTORY, ROOT, SIZES, TARGET, decision_metrics, load_dataset, make_split,
    recall_at_alert_rate, score_metrics, threshold_for_alert_rate, threshold_max_fbeta,
    threshold_min_recall,
)

warnings.filterwarnings("ignore")
OUT = ROOT / "outputs" / "recalibration"
OUT.mkdir(parents=True, exist_ok=True)

PROJECT_LGBM = dict(n_estimators=350, max_depth=7, num_leaves=31, learning_rate=0.04,
                    subsample=0.85, colsample_bytree=0.85)
PROJECT_XGB = dict(n_estimators=350, max_depth=6, learning_rate=0.04, subsample=0.85,
                   colsample_bytree=0.85)


# --------------------------------------------------------------------------- modelos
def feature_lists(cfg, numeric, categorical):
    """'base' = contrato; 'plus' = + transformaciones; 'traj' = plus + rezagos/acumulados."""
    mode = cfg.get("features", "plus")
    nums = list(numeric) + (RECONSTRUCTED if mode in ("plus", "traj") else []) + (TRAJECTORY if mode == "traj" else [])
    return nums, list(categorical)


def sample_weights(y: np.ndarray, mode):
    if mode in (None, "none"):
        return None
    ratio = (y == 0).sum() / max((y == 1).sum(), 1)
    pos_w = ratio if mode == "balanced" else float(np.sqrt(ratio))
    return np.where(y == 1, pos_w, 1.0)


def build_model(cfg, nums, cats):
    kind, params = cfg["model"], dict(cfg.get("params", {}))
    seed = cfg.get("model_seed", 42)
    nj = cfg.get("n_jobs", 12)
    if kind == "lgbm":
        return lgb.LGBMClassifier(random_state=seed, n_jobs=nj, verbose=-1,
                                  subsample_freq=params.pop("subsample_freq", 1), **params)
    if kind == "xgb":
        return xgb.XGBClassifier(random_state=seed, n_jobs=nj, verbosity=0, tree_method="hist",
                                 enable_categorical=True, eval_metric="logloss", **params)
    if kind == "logit":
        pre = ColumnTransformer([
            ("n", Pipeline([("i", SimpleImputer(strategy="median", add_indicator=True)),
                            ("s", StandardScaler())]), nums),
            ("c", OneHotEncoder(handle_unknown="ignore"), cats),
        ])
        return Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=2000, **params))])
    raise ValueError(kind)


def fit_predict_raw(cfg, nums, cats, X_tr, y_tr, X_ev):
    """Entrena con peso/muestreo y devuelve probabilidades crudas en X_ev."""
    cols = nums + cats
    Xt, yt = X_tr[cols], np.asarray(y_tr)
    sampling = cfg.get("sampling")
    if sampling in ("under", "over"):
        sampler_cls = RandomUnderSampler if sampling == "under" else RandomOverSampler
        sampler = sampler_cls(sampling_strategy=cfg.get("sampling_ratio", 0.5), random_state=42)
        idx_res, _ = sampler.fit_resample(np.arange(len(Xt)).reshape(-1, 1), yt)
        idx_res = idx_res.ravel()
        Xt, yt = Xt.iloc[idx_res], yt[idx_res]
    sw = sample_weights(yt, cfg.get("class_weight"))
    model = build_model(cfg, nums, cats)
    if cfg["model"] == "logit":
        model.fit(Xt, yt, clf__sample_weight=sw)
    else:
        model.fit(Xt, yt, sample_weight=sw)
    return model.predict_proba(X_ev[cols])[:, 1]


def fit_predict(cfg, nums, cats, X_tr, y_tr, groups_tr, X_ev):
    """Con calibración opcional por validación cruzada agrupada por estudiante."""
    raw_ev = fit_predict_raw(cfg, nums, cats, X_tr, y_tr, X_ev)
    calibration = cfg.get("calibration")
    if calibration in (None, "none"):
        return raw_ev, raw_ev
    folds = GroupKFold(n_splits=cfg.get("cal_folds", 3))
    oof = np.zeros(len(X_tr))
    for tr_idx, te_idx in folds.split(X_tr, y_tr, groups_tr):
        oof[te_idx] = fit_predict_raw(cfg, nums, cats, X_tr.iloc[tr_idx], np.asarray(y_tr)[tr_idx],
                                      X_tr.iloc[te_idx])
    if calibration == "isotonic":
        cal = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(oof, y_tr)
        return cal.predict(raw_ev), raw_ev
    if calibration == "sigmoid":
        eps = 1e-6
        logit = lambda p: np.log(np.clip(p, eps, 1 - eps) / (1 - np.clip(p, eps, 1 - eps)))  # noqa: E731
        cal = LogisticRegression(C=1e6, max_iter=1000).fit(logit(oof).reshape(-1, 1), y_tr)
        return cal.predict_proba(logit(raw_ev).reshape(-1, 1))[:, 1], raw_ev
    raise ValueError(calibration)


# --------------------------------------------------------------------------- experimento
POLICIES = ("recall80_val", "cap40_val", "cap40_topk", "cap50_topk", "f2_val")


def evaluate(cfg, df, nums_all, cats, seed, test_periods=None, save_scores=None, size=None):
    nums, cats = feature_lists(cfg, nums_all, cats)
    split = make_split(df, seed=seed, test_periods=test_periods)
    X = df[nums + cats]
    y = df[TARGET].values
    groups = df["id_estudiante_anon"].values

    fit_m, val_m, train_m, test_m = (split[k] for k in ("fit", "val", "train", "test"))
    p_val, p_val_raw = fit_predict(cfg, nums, cats, X[fit_m], y[fit_m], groups[fit_m], X[val_m])
    p_te, p_te_raw = fit_predict(cfg, nums, cats, X[train_m], y[train_m], groups[train_m], X[test_m])
    y_val, y_te = y[val_m], y[test_m]

    thresholds = {
        "recall80_val": threshold_min_recall(y_val, p_val, 0.80),
        "cap40_val": threshold_for_alert_rate(p_val, 0.40),
        "f2_val": threshold_max_fbeta(y_val, p_val, 2.0),
    }
    base = {
        "n_rows_total": len(df), "n_val": int(val_m.sum()), "n_test": int(test_m.sum()),
        "n_test_students": int(df.loc[test_m, "id_estudiante_anon"].nunique()),
        "val_prevalence": float(y_val.mean()),
        **{f"val_{k}": v for k, v in score_metrics(y_val, p_val).items() if k in ("auc_roc", "auc_pr")},
        **{f"val_recall_top{int(r*100)}": recall_at_alert_rate(y_val, p_val, r)["recall"] for r in (0.4, 0.5)},
        **score_metrics(y_te, p_te),
        "auc_roc_raw": score_metrics(y_te, p_te_raw)["auc_roc"],
        "brier_raw": score_metrics(y_te, p_te_raw)["brier"],
        "ece_raw": score_metrics(y_te, p_te_raw)["ece"],
        "oracle_auc_test": score_metrics(y_te, df.loc[test_m, "oracle_hazard"].values)["auc_roc"],
    }
    rows = []
    for policy in POLICIES:
        if policy.endswith("_topk"):
            rate = float(policy[3:5]) / 100
            dm = recall_at_alert_rate(y_te, p_te, rate)
            thr = float("nan")
        else:
            thr = thresholds[policy]
            dm = decision_metrics(y_te, p_te >= thr)
        rows.append({**base, "policy": policy, "threshold": thr, **dm})
    if save_scores is not None:
        pd.DataFrame({"y": y_te, "p": p_te, "oracle": df.loc[test_m, "oracle_hazard"].values,
                      "period": df.loc[test_m, "periodo_id"].astype(str).values,
                      "student": groups[test_m]}).to_parquet(save_scores, index=False)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--configs", required=True, help="archivo JSON con lista de configs")
    ap.add_argument("--seeds", type=int, nargs="+", default=[42])
    ap.add_argument("--sizes", type=int, nargs="+", default=SIZES)
    ap.add_argument("--test-periods", nargs="*", default=None)
    ap.add_argument("--save-scores", action="store_true")
    args = ap.parse_args()

    configs = json.loads(Path(args.configs).read_text(encoding="utf-8"))
    out_csv = OUT / f"results_{args.stage}.csv"
    all_rows = []
    for size in args.sizes:
        t0 = time.time()
        df, nums_all, cats = load_dataset(Path(args.data_root) / f"n{size}")
        print(f"[{args.stage}] n={size} filas={len(df):,} carga={time.time()-t0:.0f}s", flush=True)
        for cfg in configs:
            for seed in args.seeds:
                t1 = time.time()
                sp = None
                if args.save_scores:
                    sd = OUT / "scores" / args.stage
                    sd.mkdir(parents=True, exist_ok=True)
                    sp = sd / f"{cfg['name']}_n{size}_s{seed}.parquet"
                rows = evaluate(cfg, df, nums_all, cats, seed, args.test_periods, sp, size)
                for r in rows:
                    all_rows.append({"stage": args.stage, "config": cfg["name"], "size": size,
                                     "seed": seed, "test_periods": ",".join(args.test_periods or ["2025-1", "2025-2"]),
                                     **r})
                print(f"   {cfg['name']:<32} seed={seed} {time.time()-t1:5.1f}s "
                      f"AUC={rows[0]['auc_roc']:.3f} rec@cap40topk={[r for r in rows if r['policy']=='cap40_topk'][0]['recall']:.3f}",
                      flush=True)
        pd.DataFrame(all_rows).to_csv(out_csv, index=False)
    print("OK ->", out_csv)


if __name__ == "__main__":
    main()
