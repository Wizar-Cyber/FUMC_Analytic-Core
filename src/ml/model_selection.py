"""Leakage-safe threshold selection and promotion metrics for binary classifiers."""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import f1_score, precision_score, recall_score


def select_recall_threshold(
    y_true: Any,
    probabilities: Any,
    *,
    minimum_recall: float = 0.80,
    max_alert_rate: float | None = None,
) -> dict[str, float | bool]:
    """Choose the highest-precision threshold meeting recall on validation data.

    If no threshold reaches the requested recall, return the threshold with the
    best observed recall and mark it ineligible. Callers must use a temporal
    validation split and must not select a threshold on the final test set.
    """
    truth = np.asarray(y_true)
    scores = np.asarray(probabilities, dtype=float)
    if truth.ndim != 1 or scores.ndim != 1 or truth.size != scores.size:
        raise ValueError("y_true y probabilities deben ser vectores de igual longitud.")
    if truth.size == 0:
        raise ValueError("No se puede seleccionar un umbral con datos vacíos.")
    if not np.isin(truth, [0, 1]).all() or np.unique(truth).size != 2:
        raise ValueError("La validación debe incluir ambas clases binarias.")
    if not np.isfinite(scores).all() or ((scores < 0) | (scores > 1)).any():
        raise ValueError("Las probabilidades deben ser finitas y estar entre 0 y 1.")
    if not np.isfinite(minimum_recall) or not 0 < minimum_recall <= 1:
        raise ValueError("minimum_recall debe estar en el intervalo (0, 1].")
    if max_alert_rate is not None and (
        not np.isfinite(max_alert_rate) or not 0 < max_alert_rate < 1
    ):
        raise ValueError("max_alert_rate debe estar en el intervalo (0, 1).")

    # Include endpoints so that even a small validation set can reach all-positive
    # and all-negative operating points. Unique score values make the search finite.
    thresholds = np.unique(np.concatenate(([0.0], scores, [1.0])))
    candidates: list[dict[str, float | bool]] = []
    for threshold in thresholds:
        prediction = scores >= threshold
        recall = float(recall_score(truth, prediction, zero_division=0))
        precision = float(precision_score(truth, prediction, zero_division=0))
        f1 = float(f1_score(truth, prediction, zero_division=0))
        candidates.append(
            {
                "threshold": float(threshold),
                "recall": recall,
                "precision": precision,
                "f1": f1,
                "alert_rate": float(np.mean(prediction)),
                # Predicting every student as positive trivially attains recall
                # 1.0 but is not a useful operating threshold.
                "eligible": (
                    recall >= minimum_recall
                    and not bool(prediction.all())
                    and (max_alert_rate is None or float(np.mean(prediction)) <= max_alert_rate)
                ),
            }
        )

    eligible = [candidate for candidate in candidates if candidate["eligible"]]
    if eligible:
        return max(
            eligible,
            key=lambda item: (
                float(item["precision"]),
                float(item["f1"]),
                float(item["threshold"]),
            ),
        )

    non_degenerate = [
        candidate
        for candidate in candidates
        if candidate["alert_rate"] < 1.0
        and (max_alert_rate is None or candidate["alert_rate"] <= max_alert_rate)
    ]
    return max(
        non_degenerate or candidates,
        key=lambda item: (
            float(item["recall"]),
            float(item["precision"]),
            float(item["f1"]),
            float(item["threshold"]),
        ),
    )


def classification_metrics(
    y_true: Any,
    probabilities: Any,
    threshold: float,
) -> dict[str, float]:
    """Calculate thresholded binary metrics for a fixed, preselected threshold."""
    truth = np.asarray(y_true)
    scores = np.asarray(probabilities, dtype=float)
    if truth.ndim != 1 or scores.ndim != 1 or truth.size != scores.size or not truth.size:
        raise ValueError("y_true y probabilities deben ser vectores no vacíos de igual longitud.")
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold debe estar entre 0 y 1.")
    prediction = scores >= threshold
    return {
        "recall": float(recall_score(truth, prediction, zero_division=0)),
        "precision": float(precision_score(truth, prediction, zero_division=0)),
        "f1": float(f1_score(truth, prediction, zero_division=0)),
    }