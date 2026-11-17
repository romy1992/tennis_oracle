"""Offline walk-forward benchmark: primitives, protocol (synthetic data) and committed report."""

from __future__ import annotations

import json

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


REQUIRED_CONTENDERS = {
    "market_no_vig",  # market, margin removed
    "elo_overall_k32",  # Elo
    "elo_surface_k32",  # Elo per surface
    "elo_overall_dynamic",  # Elo with experience-dependent K and inactivity decay
    "lr_no_odds",  # logistic regression without odds
    "lr_with_odds",  # logistic regression with odds
    "hgb_no_odds",  # gradient boosting without odds
    "hgb_with_odds",  # gradient boosting with odds
}
REQUIRED_SEGMENTS = {"surface", "period", "market_balance", "min_prior_matches"}
FORBIDDEN_FEATURES = {"atp_minutes", "atp_score"}


def _synthetic_dataset(rows: int = 1500, seed: int = 3) -> pd.DataFrame:
    """Small dataset with the v3 columns the benchmark reads.

    ``atp_score`` / ``atp_minutes`` reveal the result on purpose: a model
    allowed to read them would be perfect.
    """
    rng = np.random.default_rng(seed)
    players = np.arange(1, 41)
    skill = rng.normal(0.0, 1.0, size=players.size + 1)
    dates = pd.date_range("2025-01-01", "2025-09-28", periods=rows).normalize()
    p1 = rng.choice(players, size=rows)
    p2 = (p1 + rng.integers(1, players.size, size=rows) - 1) % players.size + 1
    true_p = 1.0 / (1.0 + np.exp(-(skill[p1] - skill[p2])))
    target = (rng.random(rows) < true_p).astype(int)
    market = np.clip(true_p + rng.normal(0.0, 0.05, rows), 0.05, 0.95)
    margin = 0.06
    frame = pd.DataFrame(
        {
            "match_id": np.arange(1, rows + 1),
            "match_date": dates.strftime("%Y-%m-%d"),
            "surface": rng.choice(["hard", "clay", "grass"], size=rows),
            "player_1_id": p1,
            "player_2_id": p2,
            bench.TARGET: target,
            "player_1_rank": rng.choice([10, 50, 200, 9999], size=rows),
            "player_2_rank": rng.choice([10, 50, 200, 9999], size=rows),
            "elo_diff": rng.normal(0.0, 50.0, rows),
            "surface_elo_diff": rng.normal(0.0, 50.0, rows),
            "avg_market_prob_player_1": market,
            "avg_market_prob_player_2": 1.0 - market,
            "avg_player_1_odds": 1.0 / (market * (1.0 + margin)),
            "avg_player_2_odds": 1.0 / ((1.0 - market) * (1.0 + margin)),
            "avg_bookmaker_margin": margin,
            "odds_bookmaker_count": rng.integers(1, 12, size=rows),
            # Post-match columns: they give the result away.
            "atp_score": np.where(target == 1, "6-0 6-0", "0-6 0-6"),
            "atp_minutes": np.where(target == 1, 60, 240),
            "player_1_atp_id": np.where(p1 <= 20, p1 + 100000.0, np.nan),
            "player_2_atp_id": np.where(p2 <= 20, p2 + 100000.0, np.nan),
        }
    )
    frame["rank_diff"] = frame["player_1_rank"] - frame["player_2_rank"]
    frame["rank_points_diff"] = rng.integers(-500, 500, size=rows)
    for column in bench.FORM_FEATURES:
        frame[column] = rng.random(rows)
    for column in bench.ENRICHMENT_NUMERIC:
        frame[column] = rng.normal(25.0, 3.0, rows)
    frame["atp_match_found"] = (rng.random(rows) < 0.5).astype(int)
    for column in bench.ENRICHMENT_CATEGORICAL:
        frame[column] = rng.choice(["A", "B"], size=rows)
    return frame


@pytest.fixture(scope="module")
def synthetic_run(tmp_path_factory):
    """One small end-to-end run; boosted models are shrunk, the protocol is the real one."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from xgboost import XGBClassifier

    path = tmp_path_factory.mktemp("bench") / "synthetic.csv.gz"
    _synthetic_dataset().to_csv(path, index=False)
    fitted: list[tuple[pd.Timestamp, list[str]]] = []
    predicted: list[list[str]] = []
    original_fit, original_predict = bench._fit_pipeline, bench._predict

    def spy_fit(train, features, estimator):
        fitted.append((pd.to_datetime(train["match_date"]).max(), list(features)))
        return original_fit(train, features, estimator)

    def spy_predict(pipeline, frame, features):
        predicted.append(list(features))
        return original_predict(pipeline, frame, features)

    patcher = pytest.MonkeyPatch()
    patcher.setattr(bench, "_fit_pipeline", spy_fit)
    patcher.setattr(bench, "_predict", spy_predict)
    patcher.setattr(
        bench, "_hist_gradient_boosting", lambda: HistGradientBoostingClassifier(max_iter=5, random_state=bench.SEED)
    )
    patcher.setattr(
        bench,
        "_xgboost",
        lambda: XGBClassifier(n_estimators=5, max_depth=2, random_state=bench.SEED, n_jobs=1, eval_metric="logloss"),
    )
    try:
        report = bench.run_benchmark(path, min_train_rows=400, min_test_rows=200, bootstrap_resamples=20)
    finally:
        patcher.undo()
    return report, fitted, predicted


class TestProtocolOnSyntheticData:
    def test_post_match_columns_never_reach_a_model(self, synthetic_run):
        report, fitted, predicted = synthetic_run
        assert FORBIDDEN_FEATURES <= bench.POST_MATCH_COLUMNS
        used = {feature for _train_end, features in fitted for feature in features}
        used |= {feature for features in predicted for feature in features}
        assert used, "the spy must have seen the fitted feature lists"
        assert not (used & bench.POST_MATCH_COLUMNS)
        for name, features in report["protocol"]["feature_sets"].items():
            assert not (set(features) & bench.POST_MATCH_COLUMNS), name
        # The synthetic post-match columns give the result away: nobody is perfect.
        assert all(entry["overall"]["accuracy"] < 0.95 for entry in report["contenders"].values())

    def test_every_model_is_fitted_only_on_rows_before_its_test_fold(self, synthetic_run):
        report, fitted, _predicted = synthetic_run
        assert len(report["folds"]) >= 2
        starts = sorted(pd.Timestamp(fold["test_start"]) for fold in report["folds"])
        for fold in report["folds"]:
            assert fold["train_end"] < fold["test_start"]
        # Fits happen fold by fold: each one must end before the start of the fold it serves.
        fits_per_fold = len(fitted) // len(starts)
        assert fits_per_fold * len(starts) == len(fitted)
        for index, (train_end, _features) in enumerate(fitted):
            assert train_end < starts[index // fits_per_fold]

    def test_report_has_required_contenders_metrics_and_segments(self, synthetic_run):
        report, _fitted, _predicted = synthetic_run
        assert REQUIRED_CONTENDERS <= set(report["contenders"])
        total = report["test_rows_total"]
        assert total == sum(fold["test_rows"] for fold in report["folds"])
        for name in REQUIRED_CONTENDERS:
            entry = report["contenders"][name]
            assert {"n", "log_loss", "brier", "ece", "accuracy"} <= set(entry["overall"])
            assert entry["overall"]["n"] == total
            assert REQUIRED_SEGMENTS <= set(entry["segments"])
            assert sum(block["n"] for block in entry["calibration_bins"]) == total
        assert set(report["contenders"]["market_no_vig"]["segments"]["market_balance"]) <= {
            "balanced_0.40-0.60",
            "unbalanced",
        }
        history_bins = {label for _low, _high, label in bench.HISTORY_BINS}
        assert set(report["contenders"]["market_no_vig"]["segments"]["min_prior_matches"]) <= history_bins

    def test_train_serve_comparison_scores_one_model_two_ways(self, synthetic_run):
        report, _fitted, _predicted = synthetic_run
        comparison = report["train_serve_skew"]["comparisons"][0]
        assert comparison["candidate"] == "v4_like__serving_enrichment_zeros"
        assert comparison["reference"] == "v4_like__true_features"
        for metric in ("log_loss", "brier", "accuracy"):
            block = comparison[metric]
            assert block["ci95_low"] <= block["mean_delta"] <= block["ci95_high"]
        accuracy = comparison["accuracy"]
        assert accuracy["mean_delta"] == pytest.approx(accuracy["candidate"] - accuracy["reference"], abs=2e-4)


class TestInferredTourUsesOnlyThePast:
    def test_label_does_not_depend_on_later_matches(self):
        frame = _frame(
            [
                ("2026-01-01", 1, 2, 1, "Hard"),  # nobody matched yet
                ("2026-01-02", 1, 3, 1, "Hard"),  # player 1 matched on this row: not known before it
                ("2026-01-02", 1, 2, 1, "Hard"),  # same day: still not known
                ("2026-01-03", 1, 3, 1, "Hard"),  # player 1 known from the day after
                ("2026-01-04", 1, 3, 1, "Hard"),
            ]
        )
        frame["player_1_atp_id"] = [np.nan, 501.0, np.nan, np.nan, np.nan]
        frame["player_2_atp_id"] = [np.nan, np.nan, np.nan, 503.0, np.nan]
        labels = bench.infer_tour(frame).tolist()
        assert labels == ["not_matched", "not_matched", "not_matched", "men_partial", "men_matched"]

        truncated = bench.infer_tour(frame.iloc[:3]).tolist()
        assert truncated == labels[:3]  # dropping the future changes nothing


class TestCommittedReport:
    """The committed JSON must describe a leak-free protocol."""

    @pytest.fixture(scope="class")
    def report(self):
        with bench.DEFAULT_REPORT_PATH.open(encoding="utf-8") as handle:
            return json.load(handle)

    def test_dataset_fingerprint_matches_the_committed_dataset(self, report):
        assert report["dataset"]["sha256"] == bench.file_sha256(bench.DEFAULT_DATASET_PATH)

    def test_no_post_match_feature_and_chronological_folds(self, report):
        for name, features in report["protocol"]["feature_sets"].items():
            assert not (set(features) & (bench.POST_MATCH_COLUMNS | FORBIDDEN_FEATURES)), name
        assert FORBIDDEN_FEATURES <= set(report["protocol"]["post_match_columns_excluded"])
        for fold in report["folds"]:
            assert fold["train_end"] < fold["test_start"] <= fold["test_end"]
        assert report["test_rows_total"] == sum(fold["test_rows"] for fold in report["folds"])

    def test_required_contenders_and_segments_are_reported(self, report):
        assert REQUIRED_CONTENDERS <= set(report["contenders"])
        assert "tau" in report["elo_selection"]["selected_dynamic_config"]  # the dynamic Elo has time decay
        for name in REQUIRED_CONTENDERS:
            entry = report["contenders"][name]
            assert entry["overall"]["n"] == report["test_rows_total"]
            assert REQUIRED_SEGMENTS <= set(entry["segments"])
