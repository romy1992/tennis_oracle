"""Unit tests for the offline walk-forward benchmark primitives (no dataset needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.src.app.ml.benchmarks import match_winner_walk_forward as bench
from backend.src.app.ml.datasets.elo_builder import EloTracker


def _frame(rows: list[tuple[str, int, int, int, str]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["match_date", "player_1_id", "player_2_id", bench.TARGET, "surface"])
    frame["match_date"] = pd.to_datetime(frame["match_date"])
    frame["match_id"] = range(1, len(frame) + 1)
    return frame


class TestChronologicalState:
    def test_first_match_starts_from_equal_ratings(self):
        state = bench.compute_chronological_state(
            _frame([("2026-01-01", 1, 2, 1, "Hard")]), [bench.EloConfig(name="k32")]
        )
        assert state["elo__k32__overall"].iloc[0] == 0.0
        assert state["bm_prior_matches_p1"].iloc[0] == 0

    def test_same_day_results_do_not_leak_into_same_day_features(self):
        frame = _frame(
            [
                ("2026-01-01", 1, 2, 1, "Hard"),
                ("2026-01-01", 1, 3, 1, "Hard"),  # same day: must not see the first result
                ("2026-01-02", 1, 3, 1, "Hard"),
            ]
        )
        state = bench.compute_chronological_state(frame, [bench.EloConfig(name="k32")])
        assert state["elo__k32__overall"].iloc[1] == 0.0
        assert state["bm_prior_matches_p1"].iloc[1] == 0
        assert state["elo__k32__overall"].iloc[2] > 0.0
        assert state["bm_prior_matches_p1"].iloc[2] == 2

    def test_constant_k_matches_repository_elo_tracker_on_distinct_days(self):
        rows = [
            ("2026-01-01", 1, 2, 1, "Hard"),
            ("2026-01-02", 2, 3, 0, "Clay"),
            ("2026-01-03", 1, 3, 1, "Hard"),
            ("2026-01-04", 1, 2, 0, "Hard"),
        ]
        frame = _frame(rows)
        state = bench.compute_chronological_state(frame, [bench.EloConfig(name="k32")])
        tracker = EloTracker()
        for index, (_date, p1, p2, target, surface) in enumerate(rows):
            features = tracker.pre_match_features(p1, p2, surface)
            assert state["elo__k32__overall"].iloc[index] == pytest.approx(features.elo_diff)
            assert state["elo__k32__surface"].iloc[index] == pytest.approx(features.surface_elo_diff)
            tracker.record_match(p1, p2, surface, target == 1)

    def test_dynamic_k_shrinks_with_experience_and_recovers_after_inactivity(self):
        config = bench.EloConfig(name="dyn", k_const=None, k0=250.0, decay_tau_days=365.0)
        book = bench._RatingBook(config)
        k_new = book.k_factor(1, 100)
        for day in range(30):
            book.apply(1, 0.0, 100 + day)
        k_active = book.k_factor(1, 131)
        k_after_layoff = book.k_factor(1, 131 + 730)
        assert k_new > k_after_layoff > k_active

    def test_surface_change_flag(self):
        frame = _frame(
            [
                ("2026-01-01", 1, 2, 1, "Hard"),
                ("2026-01-05", 1, 2, 1, "Clay"),
                ("2026-01-09", 1, 2, 1, "Clay"),
            ]
        )
        state = bench.compute_chronological_state(frame, [bench.EloConfig(name="k32")])
        assert state["bm_surface_change"].tolist() == [0, 1, 0]


class TestMetrics:
    def test_log_loss_and_brier_of_a_coin_flip(self):
        y = np.array([1.0, 0.0, 1.0, 0.0])
        p = np.full(4, 0.5)
        summary = bench.summarize(y, p)
        assert summary["log_loss"] == pytest.approx(0.69315, abs=1e-5)
        assert summary["brier"] == pytest.approx(0.25)
        assert summary["ece"] == pytest.approx(0.0)

    def test_ece_detects_overconfidence(self):
        y = np.array([1.0, 0.0, 1.0, 0.0])
        p = np.full(4, 0.9)
        assert bench.expected_calibration_error(y, p) == pytest.approx(0.4)

    def test_paired_bootstrap_is_deterministic_and_signed(self):
        worse = np.full(200, 0.7)
        better = np.full(200, 0.6)
        first = bench.paired_bootstrap_delta(worse, better, n_resamples=50)
        second = bench.paired_bootstrap_delta(worse, better, n_resamples=50)
        assert first == second
        assert first["mean_delta"] == pytest.approx(0.1)
        assert first["ci95_low"] > 0


class TestServingVariants:
    def _rows(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "player_1_age": [24.0],
                "player_2_age": [30.0],
                "age_diff": [-6.0],
                "player_1_height": [185.0],
                "player_2_height": [190.0],
                "height_diff": [-5.0],
                "atp_best_of": [3.0],
                "atp_match_found": [1.0],
                "player_1_hand": ["R"],
                "player_2_hand": ["L"],
                "atp_surface": ["Hard"],
                "atp_tourney_level": ["A"],
                "atp_round": ["R32"],
                "rank_diff": [12],
                "rank_points_diff": [-300],
            }
        )

    def test_serving_defaults_reproduce_the_zero_fill(self):
        out = bench.apply_serving_enrichment_defaults(self._rows())
        assert (out[bench.ENRICHMENT_NUMERIC].iloc[0] == 0).all()
        assert (out[bench.ENRICHMENT_CATEGORICAL].iloc[0] == bench.SERVING_ZERO_CATEGORY).all()

    def test_missing_variant_uses_nan_and_unmatched_flag(self):
        out = bench.apply_missing_enrichment(self._rows())
        assert out["player_1_age"].isna().all()
        assert out["player_1_hand"].isna().all()
        assert out["atp_match_found"].iloc[0] == 0

    def test_rank_fallback_zeroes_rank_differences(self):
        out = bench.apply_serving_rank_fallback(self._rows())
        assert out["rank_diff"].iloc[0] == 0 and out["rank_points_diff"].iloc[0] == 0

    def test_post_match_columns_are_never_features(self):
        used = set(bench.PRODUCTION_V4_FEATURES) | set(bench.FORM_FEATURES) | set(bench.ODDS_FEATURES)
        assert not (used & bench.POST_MATCH_COLUMNS)


def test_build_folds_requires_training_history():
    dates = pd.Series(
        pd.to_datetime(["2025-01-10"] * 5 + ["2025-04-10"] * 5 + ["2025-07-10"] * 5)
    )
    folds = bench.build_folds(dates, min_train_rows=5, min_test_rows=5)
    assert [fold["name"] for fold in folds] == ["2025Q2", "2025Q3"]
