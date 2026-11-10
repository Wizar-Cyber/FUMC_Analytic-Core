import numpy as np
import pytest

from src.ml.model_selection import classification_metrics, select_recall_threshold
from src.ml.feature_engineering import (
    join_mature_targets,
    temporal_group_holdout,
    temporal_group_train_validation_test_split,
)


def test_threshold_meets_recall_without_marking_all_positive_as_eligible():
    result = select_recall_threshold(
        [0, 0, 0, 1, 1],
        [0.05, 0.1, 0.55, 0.7, 0.9],
        minimum_recall=0.8,
    )

    assert result["eligible"] is True
    assert result["recall"] >= 0.8
    assert result["alert_rate"] < 1
    assert result["threshold"] == pytest.approx(0.7)


def test_threshold_does_not_accept_all_positive_predictions():
    result = select_recall_threshold(
        [0, 0, 1, 1], [0.5, 0.5, 0.5, 0.5], minimum_recall=0.8
    )

    assert result["alert_rate"] < 1.0
    assert result["eligible"] is False


def test_threshold_rejects_invalid_data_and_target():
    with pytest.raises(ValueError, match="ambas clases"):
        select_recall_threshold([1, 1], [0.2, 0.8])
    with pytest.raises(ValueError, match="probabilidades"):
        select_recall_threshold([0, 1], [0.2, 1.2])
    with pytest.raises(ValueError, match="minimum_recall"):
        select_recall_threshold([0, 1], [0.2, 0.8], minimum_recall=0)


def test_classification_metrics_use_fixed_threshold():
    result = classification_metrics([0, 0, 1, 1], [0.1, 0.6, 0.7, 0.9], 0.6)

    assert result == {"recall": 1.0, "precision": 2 / 3, "f1": 0.8}


def test_training_join_excludes_immature_targets_without_turning_them_into_zero():
    import pandas as pd

    predictors = pd.DataFrame(
        {
            "id_estudiante_anon": ["s1", "s1", "s2"],
            "periodo_id": ["2024-1", "2024-2", "2024-1"],
            "feature": [1, 2, 3],
        }
    )
    targets = pd.DataFrame(
        {
            "id_estudiante_anon": ["s1", "s1", "s2"],
            "periodo_id": ["2024-1", "2024-2", "2024-1"],
            "target_desercion": [1, np.nan, 0],
            "target_observado": [True, False, True],
        }
    )

    joined = join_mature_targets(predictors, targets)

    assert joined["periodo_id"].tolist() == ["2024-1", "2024-1"]
    assert joined["target_desercion"].tolist() == [1, 0]


def test_temporal_group_holdout_keeps_students_disjoint():
    import pandas as pd

    periods = ["2023-1", "2023-2", "2024-1", "2024-2"]
    frame = pd.DataFrame(
        [
            {"id_estudiante_anon": f"s{student}", "periodo_id": period}
            for student in range(20)
            for period in periods
        ]
    )

    train_mask, test_mask, selected = temporal_group_holdout(
        frame, number_of_test_periods=2, test_fraction=0.25, random_state=13
    )
    train_students = set(frame.loc[train_mask, "id_estudiante_anon"])
    test_students = set(frame.loc[test_mask, "id_estudiante_anon"])

    assert selected == ["2024-1", "2024-2"]
    assert train_students.isdisjoint(test_students)
    assert set(frame.loc[test_mask, "periodo_id"]) == set(selected)
    assert set(frame.loc[train_mask, "periodo_id"]).isdisjoint(selected)


def test_three_way_split_keeps_students_disjoint_across_fit_validation_test():
    import pandas as pd

    periods = [f"{year}-{semester}" for year in range(2020, 2025) for semester in (1, 2)]
    frame = pd.DataFrame(
        [
            {"id_estudiante_anon": f"s{student}", "periodo_id": period}
            for student in range(50)
            for period in periods
        ]
    )

    fit, validation, train, test, validation_periods, test_periods = (
        temporal_group_train_validation_test_split(
            frame,
            number_of_test_periods=2,
            number_of_validation_periods=1,
            random_state=7,
        )
    )
    fit_ids = set(frame.loc[fit, "id_estudiante_anon"])
    validation_ids = set(frame.loc[validation, "id_estudiante_anon"])
    test_ids = set(frame.loc[test, "id_estudiante_anon"])

    assert fit_ids.isdisjoint(validation_ids)
    assert (fit_ids | validation_ids).isdisjoint(test_ids)
    assert set(frame.loc[validation, "periodo_id"]) == set(validation_periods)
    assert set(frame.loc[test, "periodo_id"]) == set(test_periods)
    assert test_ids.isdisjoint(set(frame.loc[train, "id_estudiante_anon"]))