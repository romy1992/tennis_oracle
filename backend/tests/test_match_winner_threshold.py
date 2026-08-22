from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from backend.src.app.ml.training.calibration import OosPredictionBatch
from backend.src.app.ml.training.match_winner_threshold import (
    ThresholdTuningConfig,
    evaluate_threshold,
    temporal_threshold_retuning,
)
from backend.src.app.ml.training.walk_forward import (
    MODEL_NAMES,
    V4_ENSEMBLE_MODEL_NAME,
    model_names_for_version,
    prepare_temporal_dataframe,
)


def _batch(
    fold_index: int,
    probabilities: list[float],
    y_true: list[int],
    player_1_odds: list[float],
    player_2_odds: list[float],
) -> OosPredictionBatch:
    test_start = date(2024, 1, 1) + timedelta(days=fold_index * 30)
    return OosPredictionBatch(
        fold_index=fold_index,
        test_start=test_start,
        test_end=test_start + timedelta(days=29),
        y_true=np.asarray(y_true, dtype=int),
        prob_raw=np.asarray(probabilities, dtype=float),
        match_dates=np.asarray(
            [test_start + timedelta(days=index) for index in range(len(y_true))]
        ),
        player_1_odds=np.asarray(player_1_odds, dtype=float),
        player_2_odds=np.asarray(player_2_odds, dtype=float),
    )


def test_threshold_metric_uses_the_actually_predicted_side() -> None:
    batch = _batch(
        0,
        probabilities=[0.60, 0.40, 0.70],
        y_true=[1, 0, 1],
        player_1_odds=[2.0, 9.0, 1.4],
        player_2_odds=[9.0, 2.0, 9.0],
    )

    metrics = evaluate_threshold([batch], 10.0)

    assert metrics["bets_count"] == 2
    assert metrics["hit_rate"] == 1.0
    assert metrics["total_profit"] == 2.0
    assert metrics["roi_percent"] == 100.0


def test_temporal_retuning_selects_from_prior_oos_only() -> None:
    prior = _batch(
        0,
        probabilities=[0.60, 0.60, 0.60, 0.60],
        y_true=[1, 1, 0, 0],
        player_1_odds=[2.0, 2.0, 1.7, 1.7],
        player_2_odds=[2.0, 2.0, 2.0, 2.0],
    )
    evaluation = _batch(
        1,
        probabilities=[0.60, 0.60, 0.60, 0.60],
        y_true=[1, 1, 0, 0],
        player_1_odds=[2.0, 2.0, 1.7, 1.7],
        player_2_odds=[2.0, 2.0, 2.0, 2.0],
    )
    config = ThresholdTuningConfig(
        thresholds_percent=(0.0, 10.0),
        baseline_threshold_percent=0.0,
        min_prior_bets=2,
    )

    result = temporal_threshold_retuning([prior, evaluation], config)

    assert result["evaluation_folds"] == 1
    assert result["per_fold"][0]["selected_threshold_percent"] == 10.0
    assert result["tuned_aggregate"]["total_profit"] == 2.0
    assert result["baseline_aggregate_same_folds"]["total_profit"] == 0.0


def test_v4_standard_model_set_includes_the_live_ensemble_only_for_v4() -> None:
    assert model_names_for_version("v4") == (*MODEL_NAMES, V4_ENSEMBLE_MODEL_NAME)
    assert model_names_for_version("v3") == MODEL_NAMES
    assert model_names_for_version("first_set_winner_v2") == MODEL_NAMES


def test_prepare_temporal_dataframe_applies_odds_filter_to_v4() -> None:
    dataframe = pd.DataFrame(
        [
            {
                "match_date": "2024-01-01",
                "target_player_1_win": 1,
                "avg_player_1_odds": 2.0,
                "avg_player_2_odds": 2.0,
                "avg_market_prob_player_1": 0.5,
                "avg_market_prob_player_2": 0.5,
                "avg_bookmaker_margin": 0.04,
                "odds_bookmaker_count": 3,
            },
            {
                "match_date": "2024-01-02",
                "target_player_1_win": 0,
                "avg_player_1_odds": np.nan,
                "avg_player_2_odds": 2.0,
                "avg_market_prob_player_1": 0.5,
                "avg_market_prob_player_2": 0.5,
                "avg_bookmaker_margin": 0.04,
                "odds_bookmaker_count": 3,
            },
        ]
    )

    prepared = prepare_temporal_dataframe(dataframe, model_version="v4")

    assert len(prepared) == 1
    assert prepared.iloc[0]["target_player_1_win"] == 1
