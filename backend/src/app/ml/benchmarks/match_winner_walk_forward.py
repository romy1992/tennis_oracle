"""Offline walk-forward benchmark for the match-winner market.

Reproducible, read-only: uses only the committed v3 dataset
(``backend/data/processed/tennis_winner_dataset_with_odds_v3.csv.gz``).
No network, no database, no production artifact or registry is modified.

What it does
- Recomputes, strictly chronologically and with same-day batching, every
  quantity that depends on match order (Elo variants, prior match counts,
  surface changes) from the full history in the dataset.
- Evaluates contenders on expanding-window folds built on the rows that have
  pre-match odds (train = every row before the fold start).
- Measures the train/serve skew of the production feature list: the same
  per-fold model is scored with the true columns and with the values the
  serving path actually injects.

Anti-leakage
- ``POST_MATCH_COLUMNS`` are never used as features.
- Hyper-parameters of the dynamic-K Elo are selected on matches that precede
  the first test fold.

Usage (repository root)::

    python -m backend.src.app.ml.benchmarks.match_winner_walk_forward
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import platform
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR  # noqa: E402
from backend.src.app.ml.training.train_baseline import build_preprocessor  # noqa: E402

logger = logging.getLogger(__name__)

SEED = 42
TARGET = "target_player_1_win"
DEFAULT_DATASET_PATH = PROCESSED_DATA_DIR / "tennis_winner_dataset_with_odds_v3.csv.gz"
DEFAULT_REPORT_PATH = REPORTS_DIR / "benchmarks" / "match_winner_walk_forward_benchmark.json"
DEFAULT_PRODUCTION_ARTIFACT_PATH = REPO_ROOT / "backend" / "data" / "models" / "v4" / "voting_ensemble.pkl"

# Known only after the match: never features.
POST_MATCH_COLUMNS = frozenset(
    {
        "atp_score",
        "atp_minutes",
        "player_1_profit_if_bet",
        "player_2_profit_if_bet",
        "market_edge_baseline_player_1",
    }
)

FORM_FEATURES = [
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "player_1_surface_last_10_win_rate",
    "player_2_surface_last_10_win_rate",
    "player_1_matches_last_14_days",
    "player_2_matches_last_14_days",
    "player_1_days_since_last_match",
    "player_2_days_since_last_match",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "h2h_surface_player_1_wins",
    "h2h_surface_player_2_wins",
]
RANK_FEATURES = ["rank_diff", "rank_points_diff"]
DATASET_ELO_FEATURES = ["elo_diff", "surface_elo_diff"]
ENRICHMENT_NUMERIC = [
    "player_1_age",
    "player_2_age",
    "age_diff",
    "player_1_height",
    "player_2_height",
    "height_diff",
    "atp_best_of",
    "atp_match_found",
]
ENRICHMENT_CATEGORICAL = [
    "player_1_hand",
    "player_2_hand",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
]
ENRICHMENT_FEATURES = [*ENRICHMENT_NUMERIC, *ENRICHMENT_CATEGORICAL]
ODDS_FEATURES = [
    "avg_player_1_odds",
    "avg_player_2_odds",
    "avg_market_prob_player_1",
    "avg_market_prob_player_2",
    "avg_bookmaker_margin",
    "odds_bookmaker_count",
]
# Same 38 columns stored in backend/data/models/v4/voting_ensemble.pkl["feature_columns"].
PRODUCTION_V4_FEATURES = [
    "surface",
    *RANK_FEATURES,
    *DATASET_ELO_FEATURES,
    *FORM_FEATURES,
    "player_1_age",
    "player_2_age",
    "age_diff",
    "player_1_height",
    "player_2_height",
    "height_diff",
    "player_1_hand",
    "player_2_hand",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
    "atp_best_of",
    "atp_match_found",
    *ODDS_FEATURES,
]
CATEGORICAL_COLUMNS = ["surface", *ENRICHMENT_CATEGORICAL]
BENCH_ELO_FEATURES = ["bm_elo_diff", "bm_surface_elo_diff", "bm_dyn_elo_diff", "bm_dyn_surface_elo_diff"]

# Marker written where the serving path puts an integer 0 in a categorical
# column: unknown to the one-hot encoder, so it encodes to an all-zero vector
# exactly like the integer 0 does in ``predictor.predict_fixture``.
SERVING_ZERO_CATEGORY = "0"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def _clip(probabilities: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1.0 - 1e-6)


def log_loss_rows(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = _clip(p)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def brier_rows(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    return (np.asarray(p, dtype=float) - y) ** 2


def expected_calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """ECE on the probability of player 1, equal-width bins."""
    p = np.asarray(p, dtype=float)
    if len(p) == 0:
        return float("nan")
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.any():
            ece += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    return float(ece)


def calibration_bins(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, Any]]:
    p = np.asarray(p, dtype=float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    out = []
    for b in range(bins):
        mask = idx == b
        if mask.any():
            out.append(
                {
                    "bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}",
                    "n": int(mask.sum()),
                    "mean_predicted": round(float(p[mask].mean()), 4),
                    "observed_rate": round(float(y[mask].mean()), 4),
                }
            )
    return out


def summarize(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    n = int(len(y))
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "log_loss": round(float(log_loss_rows(y, p).mean()), 5),
        "brier": round(float(brier_rows(y, p).mean()), 5),
        "accuracy": round(float(((p >= 0.5).astype(float) == y).mean()), 4),
        "ece": round(expected_calibration_error(y, p), 4),
    }


def paired_bootstrap_delta(
    loss_a: np.ndarray,
    loss_b: np.ndarray,
    *,
    n_resamples: int = 1000,
    seed: int = SEED,
) -> dict[str, float]:
    """Mean and 95% CI of mean(loss_a - loss_b), resampling matches with replacement."""
    diff = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    rng = np.random.default_rng(seed)
    n = len(diff)
    means = np.empty(n_resamples)
    for i in range(n_resamples):
        means[i] = diff[rng.integers(0, n, n)].mean()
    return {
        "mean_delta": round(float(diff.mean()), 5),
        "ci95_low": round(float(np.quantile(means, 0.025)), 5),
        "ci95_high": round(float(np.quantile(means, 0.975)), 5),
    }


# ---------------------------------------------------------------------------
# Chronological state (Elo variants, prior counts) with same-day batching
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EloConfig:
    """Rating-update rule.

    ``k_const`` set   -> constant K (repository rule: 1500 / K=32).
    ``k_const`` None  -> dynamic K = k0 / (n_eff + offset) ** shape, where
                         ``n_eff`` is the player's prior match count; with
                         ``decay_tau_days`` the count is discounted after an
                         inactivity gap longer than ``decay_grace_days`` so that
                         the rating becomes more reactive (time decay of the
                         confidence in an old rating).
    """

    name: str
    k_const: float | None = 32.0
    k0: float = 250.0
    offset: float = 5.0
    shape: float = 0.4
    decay_tau_days: float | None = None
    decay_grace_days: float = 30.0


class _RatingBook:
    def __init__(self, config: EloConfig, initial: float = 1500.0) -> None:
        self.config = config
        self.initial = initial
        self.rating: dict[Any, float] = {}
        self.n_eff: dict[Any, float] = {}
        self.last_ordinal: dict[Any, int] = {}

    def get(self, key: Any) -> float:
        return self.rating.get(key, self.initial)

    def k_factor(self, key: Any, ordinal: int) -> float:
        cfg = self.config
        if cfg.k_const is not None:
            return cfg.k_const
        n_eff = self.n_eff.get(key, 0.0)
        if cfg.decay_tau_days:
            last = self.last_ordinal.get(key)
            if last is not None:
                gap = ordinal - last - cfg.decay_grace_days
                if gap > 0:
                    n_eff *= math.exp(-gap / cfg.decay_tau_days)
        return cfg.k0 / (n_eff + cfg.offset) ** cfg.shape

    def apply(self, key: Any, delta: float, ordinal: int) -> None:
        cfg = self.config
        if cfg.k_const is None:
            n_eff = self.n_eff.get(key, 0.0)
            if cfg.decay_tau_days:
                last = self.last_ordinal.get(key)
                if last is not None:
                    gap = ordinal - last - cfg.decay_grace_days
                    if gap > 0:
                        n_eff *= math.exp(-gap / cfg.decay_tau_days)
            self.n_eff[key] = n_eff + 1.0
        self.rating[key] = self.get(key) + delta
        self.last_ordinal[key] = ordinal


def elo_expected(diff: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + 10.0 ** (-np.asarray(diff, dtype=float) / 400.0))


def compute_chronological_state(
    dataframe: pd.DataFrame,
    configs: Iterable[EloConfig],
) -> pd.DataFrame:
    """Pre-match rating differences and history counts for every row.

    ``dataframe`` must be sorted by (match_date, match_id). All rows of a
    calendar date are read before any result of that date is applied (same
    rule as ``dataset_builder.legacy_match_rows_to_dataframe_v2``), so no
    same-day result can leak into a same-day feature.
    """
    configs = list(configs)
    overall = {cfg.name: _RatingBook(cfg) for cfg in configs}
    surface_books = {cfg.name: _RatingBook(cfg) for cfg in configs}
    prior_matches: dict[int, int] = {}
    prior_surface_matches: dict[tuple[int, str], int] = {}
    last_surface: dict[int, str] = {}

    n_rows = len(dataframe)
    out_overall = {cfg.name: np.zeros(n_rows) for cfg in configs}
    out_surface = {cfg.name: np.zeros(n_rows) for cfg in configs}
    n1 = np.zeros(n_rows, dtype=np.int64)
    n2 = np.zeros(n_rows, dtype=np.int64)
    ns1 = np.zeros(n_rows, dtype=np.int64)
    ns2 = np.zeros(n_rows, dtype=np.int64)
    surface_change = np.zeros(n_rows, dtype=np.int8)

    ordinals = pd.to_datetime(dataframe["match_date"]).map(pd.Timestamp.toordinal).to_numpy()
    p1 = dataframe["player_1_id"].to_numpy()
    p2 = dataframe["player_2_id"].to_numpy()
    surfaces = dataframe["surface"].astype(str).to_numpy()
    targets = dataframe[TARGET].to_numpy()

    start = 0
    while start < n_rows:
        end = start
        ordinal = int(ordinals[start])
        while end < n_rows and ordinals[end] == ordinal:
            end += 1

        for i in range(start, end):
            a, b, s = int(p1[i]), int(p2[i]), surfaces[i]
            n1[i] = prior_matches.get(a, 0)
            n2[i] = prior_matches.get(b, 0)
            ns1[i] = prior_surface_matches.get((a, s), 0)
            ns2[i] = prior_surface_matches.get((b, s), 0)
            changed = (a in last_surface and last_surface[a] != s) or (
                b in last_surface and last_surface[b] != s
            )
            surface_change[i] = 1 if changed else 0
            for name in overall:
                out_overall[name][i] = overall[name].get(a) - overall[name].get(b)
                out_surface[name][i] = surface_books[name].get((a, s)) - surface_books[name].get((b, s))

        # Updates are computed from the pre-date ratings and applied afterwards.
        pending: list[tuple[_RatingBook, Any, float]] = []
        for i in range(start, end):
            a, b, s = int(p1[i]), int(p2[i]), surfaces[i]
            score_a = 1.0 if targets[i] == 1 else 0.0
            for name in overall:
                book = overall[name]
                expected_a = float(elo_expected(out_overall[name][i]))
                pending.append((book, a, book.k_factor(a, ordinal) * (score_a - expected_a)))
                pending.append((book, b, book.k_factor(b, ordinal) * (expected_a - score_a)))
                sbook = surface_books[name]
                expected_sa = float(elo_expected(out_surface[name][i]))
                pending.append((sbook, (a, s), sbook.k_factor((a, s), ordinal) * (score_a - expected_sa)))
                pending.append((sbook, (b, s), sbook.k_factor((b, s), ordinal) * (expected_sa - score_a)))
        for book, key, delta in pending:
            book.apply(key, delta, ordinal)
        for i in range(start, end):
            a, b, s = int(p1[i]), int(p2[i]), surfaces[i]
            prior_matches[a] = prior_matches.get(a, 0) + 1
            prior_matches[b] = prior_matches.get(b, 0) + 1
            prior_surface_matches[(a, s)] = prior_surface_matches.get((a, s), 0) + 1
            prior_surface_matches[(b, s)] = prior_surface_matches.get((b, s), 0) + 1
            last_surface[a] = s
            last_surface[b] = s
        start = end

    state = pd.DataFrame(index=dataframe.index)
    for cfg in configs:
        state[f"elo__{cfg.name}__overall"] = out_overall[cfg.name]
        state[f"elo__{cfg.name}__surface"] = out_surface[cfg.name]
    state["bm_prior_matches_p1"] = n1
    state["bm_prior_matches_p2"] = n2
    state["bm_prior_surface_matches_p1"] = ns1
    state["bm_prior_surface_matches_p2"] = ns2
    state["bm_surface_change"] = surface_change
    return state


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> pd.DataFrame:
    dataframe = pd.read_csv(path, low_memory=False, dtype={c: "object" for c in ENRICHMENT_CATEGORICAL})
    dataframe["match_date"] = pd.to_datetime(dataframe["match_date"], errors="coerce")
    dataframe = dataframe.dropna(subset=["match_date", TARGET, "player_1_id", "player_2_id"])
    dataframe = dataframe.sort_values(["match_date", "match_id"], kind="mergesort").reset_index(drop=True)
    dataframe["surface"] = dataframe["surface"].fillna("unknown").astype(object)
    return dataframe


def valid_odds_mask(dataframe: pd.DataFrame) -> pd.Series:
    """Same validity rule as ``train_baseline.filter_rows_with_valid_odds``."""
    odds = dataframe[ODDS_FEATURES].apply(pd.to_numeric, errors="coerce")
    mask = odds.notna().all(axis=1)
    mask &= odds["avg_player_1_odds"] > 1.0
    mask &= odds["avg_player_2_odds"] > 1.0
    mask &= odds["avg_market_prob_player_1"].between(0.0, 1.0)
    mask &= odds["avg_market_prob_player_2"].between(0.0, 1.0)
    mask &= odds["avg_bookmaker_margin"] >= 0.0
    mask &= odds["odds_bookmaker_count"] > 0
    return mask


def infer_tour(dataframe: pd.DataFrame) -> pd.Series:
    """Heuristic circuit label (the dataset has no tour column).

    A player is "known men's circuit" when at least one of his matches was
    matched to the Sackmann ATP files (``player_*_atp_id`` present).
    - ``men_matched``: both players known.
    - ``men_partial``: exactly one player known.
    - ``not_matched``: neither player ever matched (women's circuit and
      unmatched lower-level events; cannot be separated with this dataset).
    """
    known = set(dataframe.loc[dataframe["player_1_atp_id"].notna(), "player_1_id"]) | set(
        dataframe.loc[dataframe["player_2_atp_id"].notna(), "player_2_id"]
    )
    count = dataframe["player_1_id"].isin(known).astype(int) + dataframe["player_2_id"].isin(known).astype(int)
    return count.map({2: "men_matched", 1: "men_partial", 0: "not_matched"}).astype(object)


def build_folds(odds_dates: pd.Series, *, min_train_rows: int, min_test_rows: int) -> list[dict[str, Any]]:
    """Expanding-window quarterly folds on the rows with odds."""
    quarters = odds_dates.dt.to_period("Q")
    counts = quarters.value_counts().sort_index()
    folds: list[dict[str, Any]] = []
    cumulative = 0
    for quarter, n in counts.items():
        if cumulative >= min_train_rows and n >= min_test_rows:
            folds.append(
                {
                    "name": str(quarter),
                    "test_start": quarter.start_time.normalize(),
                    "test_end": quarter.end_time.normalize(),
                }
            )
        cumulative += int(n)
    return folds


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _logistic_regression(**overrides: Any):
    from sklearn.linear_model import LogisticRegression

    params: dict[str, Any] = {"C": 1.0, "max_iter": 3000}
    params.update(overrides)
    return LogisticRegression(**params)


def _hist_gradient_boosting():
    from sklearn.ensemble import HistGradientBoostingClassifier

    return HistGradientBoostingClassifier(learning_rate=0.05, max_depth=10, random_state=SEED)


def _xgboost():
    from xgboost import XGBClassifier

    return XGBClassifier(
        n_estimators=100,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=SEED,
        n_jobs=4,
        eval_metric="logloss",
    )


def _v4_like_voting():
    """Same estimators/hyper-parameters as the committed v4 voting ensemble."""
    from sklearn.ensemble import VotingClassifier

    return VotingClassifier(
        estimators=[
            ("logistic_regression", _logistic_regression(C=0.01, class_weight="balanced")),
            ("xgboost", _xgboost()),
            ("hist_gradient_boosting", _hist_gradient_boosting()),
        ],
        voting="soft",
        n_jobs=1,
    )


def _fit_pipeline(train: pd.DataFrame, features: list[str], estimator: Any):
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(train, features)),
            ("model", estimator),
        ]
    )
    pipeline.fit(train[features], train[TARGET].astype(int))
    return pipeline


def _predict(pipeline: Any, frame: pd.DataFrame, features: list[str]) -> np.ndarray:
    return pipeline.predict_proba(frame[features])[:, 1]


def apply_serving_enrichment_defaults(frame: pd.DataFrame) -> pd.DataFrame:
    """Reproduce what ``predictor.predict_fixture`` feeds for the enrichment columns.

    ``_clean_features`` keeps only the v2 dataset columns, so the 13 enrichment
    columns are missing and are then filled with the integer 0.
    """
    out = frame.copy()
    for column in ENRICHMENT_NUMERIC:
        out[column] = 0.0
    for column in ENRICHMENT_CATEGORICAL:
        out[column] = SERVING_ZERO_CATEGORY
    return out


def apply_serving_rank_fallback(frame: pd.DataFrame) -> pd.DataFrame:
    """Rank features when no ranking file is available at serving (sentinel 9999 on both sides)."""
    out = frame.copy()
    out["rank_diff"] = 0
    out["rank_points_diff"] = 0
    return out


def apply_missing_enrichment(frame: pd.DataFrame) -> pd.DataFrame:
    """Enrichment columns declared missing (NaN): the fitted imputers handle them."""
    out = frame.copy()
    for column in ENRICHMENT_NUMERIC:
        out[column] = np.nan
    out["atp_match_found"] = 0.0
    for column in ENRICHMENT_CATEGORICAL:
        out[column] = np.nan
    return out


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

ELO_GRID = [
    EloConfig(name="k32"),
    EloConfig(name="dyn_k150", k_const=None, k0=150.0),
    EloConfig(name="dyn_k250", k_const=None, k0=250.0),
    EloConfig(name="dyn_k350", k_const=None, k0=350.0),
    EloConfig(name="dyn_k150_tau365", k_const=None, k0=150.0, decay_tau_days=365.0),
    EloConfig(name="dyn_k250_tau365", k_const=None, k0=250.0, decay_tau_days=365.0),
    EloConfig(name="dyn_k350_tau365", k_const=None, k0=350.0, decay_tau_days=365.0),
    EloConfig(name="dyn_k150_tau180", k_const=None, k0=150.0, decay_tau_days=180.0),
    EloConfig(name="dyn_k250_tau180", k_const=None, k0=250.0, decay_tau_days=180.0),
    EloConfig(name="dyn_k350_tau180", k_const=None, k0=350.0, decay_tau_days=180.0),
]

HISTORY_BINS = [(0, 0, "0"), (1, 4, "1-4"), (5, 19, "5-19"), (20, 49, "20-49"), (50, 10**9, "50+")]


def _history_bin(values: pd.Series) -> pd.Series:
    out = pd.Series("50+", index=values.index, dtype=object)
    for low, high, label in HISTORY_BINS:
        out[(values >= low) & (values <= high)] = label
    return out


def _segment_definitions(test: pd.DataFrame) -> dict[str, pd.Series]:
    market = test["avg_market_prob_player_1"]
    min_prior = test[["bm_prior_matches_p1", "bm_prior_matches_p2"]].min(axis=1)
    rank_missing = (test["player_1_rank"] >= 9999).astype(int) + (test["player_2_rank"] >= 9999).astype(int)
    books = test["odds_bookmaker_count"]
    return {
        "surface": test["surface"].astype(object),
        "period": test["fold"].astype(object),
        "tournament_level": test["atp_tourney_level"].fillna("unknown").astype(object),
        "tour_inferred": test["bm_tour_inferred"],
        "market_balance": pd.Series(
            np.where(market.between(0.40, 0.60), "balanced_0.40-0.60", "unbalanced"), index=test.index, dtype=object
        ),
        "min_prior_matches": _history_bin(min_prior),
        "rank_missing_players": rank_missing.map({0: "none", 1: "one", 2: "both"}).astype(object),
        "bookmaker_count": pd.Series(
            np.where(books <= 3, "1-3", np.where(books <= 8, "4-8", "9+")), index=test.index, dtype=object
        ),
        "surface_change": test["bm_surface_change"].map({0: "same_surface_or_first", 1: "surface_changed"}).astype(object),
    }


def run_benchmark(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    *,
    min_train_rows: int = 10_000,
    min_test_rows: int = 2_000,
    bootstrap_resamples: int = 1000,
    max_rows: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    def note(message: str) -> None:
        logger.info(message)
        if progress:
            progress(message)

    started = time.time()
    dataframe = load_dataset(dataset_path)
    if max_rows is not None:
        dataframe = dataframe.tail(max_rows).reset_index(drop=True)
    note(f"dataset rows={len(dataframe)}")

    state = compute_chronological_state(dataframe, ELO_GRID)
    dataframe = pd.concat([dataframe, state], axis=1)
    dataframe["bm_tour_inferred"] = infer_tour(dataframe)
    dataframe["has_odds"] = valid_odds_mask(dataframe)
    y_all = dataframe[TARGET].to_numpy(dtype=float)

    odds_rows = dataframe[dataframe["has_odds"]]
    folds = build_folds(odds_rows["match_date"], min_train_rows=min_train_rows, min_test_rows=min_test_rows)
    if not folds:
        raise ValueError("No walk-forward fold could be built (not enough rows with odds).")
    first_test_start = folds[0]["test_start"]

    # --- Elo hyper-parameter selection strictly before the first test fold ---
    selection_window = (dataframe["match_date"] < first_test_start) & (
        dataframe["match_date"] >= first_test_start - pd.Timedelta(days=730)
    )
    elo_selection: list[dict[str, Any]] = []
    for cfg in ELO_GRID:
        blend = 0.5 * dataframe[f"elo__{cfg.name}__overall"] + 0.5 * dataframe[f"elo__{cfg.name}__surface"]
        p = np.asarray(elo_expected(blend[selection_window].to_numpy()))
        elo_selection.append(
            {
                "config": cfg.name,
                "n": int(selection_window.sum()),
                "blend_log_loss": round(float(log_loss_rows(y_all[selection_window.to_numpy()], p).mean()), 5),
            }
        )
    dynamic_candidates = [row for row in elo_selection if row["config"] != "k32"]
    selected_dynamic = min(dynamic_candidates, key=lambda row: row["blend_log_loss"])["config"]
    note(f"selected dynamic Elo config={selected_dynamic}")

    dataframe["bm_elo_diff"] = dataframe["elo__k32__overall"]
    dataframe["bm_surface_elo_diff"] = dataframe["elo__k32__surface"]
    dataframe["bm_dyn_elo_diff"] = dataframe[f"elo__{selected_dynamic}__overall"]
    dataframe["bm_dyn_surface_elo_diff"] = dataframe[f"elo__{selected_dynamic}__surface"]
    for side in ("1", "2"):
        rank = pd.to_numeric(dataframe[f"player_{side}_rank"], errors="coerce")
        dataframe[f"bm_rank_missing_p{side}"] = (rank.isna() | (rank >= 9999)).astype(int)
        dataframe[f"bm_log_rank_p{side}"] = np.log(rank.where(rank < 9999)).fillna(0.0)
    dataframe["bm_log_rank_diff"] = dataframe["bm_log_rank_p1"] - dataframe["bm_log_rank_p2"]
    market = dataframe["avg_market_prob_player_1"].clip(1e-4, 1 - 1e-4)
    dataframe["bm_market_logit"] = np.log(market / (1 - market))

    # Audit: the dataset Elo columns must match a same-day-batched recomputation.
    dataset_elo_audit = {
        "abs_diff_overall_mean": round(float((dataframe["elo_diff"] - dataframe["bm_elo_diff"]).abs().mean()), 4),
        "abs_diff_overall_p99": round(float((dataframe["elo_diff"] - dataframe["bm_elo_diff"]).abs().quantile(0.99)), 4),
        "corr_overall": round(float(np.corrcoef(dataframe["elo_diff"], dataframe["bm_elo_diff"])[0, 1]), 5),
        "corr_surface": round(float(np.corrcoef(dataframe["surface_elo_diff"], dataframe["bm_surface_elo_diff"])[0, 1]), 5),
    }

    rank_features = ["bm_log_rank_diff", "bm_rank_missing_p1", "bm_rank_missing_p2"]
    no_odds_features = ["surface", *BENCH_ELO_FEATURES, *FORM_FEATURES, *rank_features]
    with_odds_features = [*no_odds_features, "bm_market_logit", "avg_bookmaker_margin", "odds_bookmaker_count"]
    production_no_enrichment = [c for c in PRODUCTION_V4_FEATURES if c not in ENRICHMENT_FEATURES]
    production_serving_available = [c for c in production_no_enrichment if c not in RANK_FEATURES]

    predictions: dict[str, list[np.ndarray]] = {}
    test_frames: list[pd.DataFrame] = []
    fold_info: list[dict[str, Any]] = []

    def add(name: str, values: np.ndarray) -> None:
        predictions.setdefault(name, []).append(np.asarray(values, dtype=float))

    for fold in folds:
        fold_started = time.time()
        test_mask = (
            dataframe["has_odds"]
            & (dataframe["match_date"] >= fold["test_start"])
            & (dataframe["match_date"] <= fold["test_end"])
        )
        history_mask = dataframe["match_date"] < fold["test_start"]
        train_odds = dataframe[history_mask & dataframe["has_odds"]]
        # No-odds fallback models may also learn from rows without odds; the
        # pre-2021 history is too sparse to be representative.
        train_history = dataframe[history_mask & (dataframe["match_date"] >= pd.Timestamp("2021-01-01"))]
        test = dataframe[test_mask].copy()
        test["fold"] = fold["name"]
        fold_info.append(
            {
                "fold": fold["name"],
                "test_start": fold["test_start"].date().isoformat(),
                "test_end": fold["test_end"].date().isoformat(),
                "train_rows_with_odds": int(len(train_odds)),
                "train_rows_history_2021plus": int(len(train_history)),
                "train_end": train_odds["match_date"].max().date().isoformat(),
                "test_rows": int(len(test)),
            }
        )

        # --- no-training contenders ---
        add("market_no_vig", test["avg_market_prob_player_1"].to_numpy())
        add("elo_overall_k32", elo_expected(test["bm_elo_diff"].to_numpy()))
        add("elo_surface_k32", elo_expected(test["bm_surface_elo_diff"].to_numpy()))
        add("elo_blend_k32", elo_expected(0.5 * test["bm_elo_diff"].to_numpy() + 0.5 * test["bm_surface_elo_diff"].to_numpy()))
        add("elo_overall_dynamic", elo_expected(test["bm_dyn_elo_diff"].to_numpy()))
        add(
            "elo_blend_dynamic",
            elo_expected(0.5 * test["bm_dyn_elo_diff"].to_numpy() + 0.5 * test["bm_dyn_surface_elo_diff"].to_numpy()),
        )
        add("dataset_elo_overall", elo_expected(test["elo_diff"].to_numpy()))

        # --- trained, no odds ---
        elo_logit = _fit_pipeline(train_history, ["bm_dyn_elo_diff", "bm_dyn_surface_elo_diff"], _logistic_regression())
        add("elo_dynamic_logit", _predict(elo_logit, test, ["bm_dyn_elo_diff", "bm_dyn_surface_elo_diff"]))
        rank_logit = _fit_pipeline(train_history, rank_features, _logistic_regression())
        add("rank_logit", _predict(rank_logit, test, rank_features))
        lr_no_odds = _fit_pipeline(train_odds, no_odds_features, _logistic_regression())
        add("lr_no_odds", _predict(lr_no_odds, test, no_odds_features))
        hgb_no_odds = _fit_pipeline(train_odds, no_odds_features, _hist_gradient_boosting())
        add("hgb_no_odds", _predict(hgb_no_odds, test, no_odds_features))
        hgb_no_odds_history = _fit_pipeline(train_history, no_odds_features, _hist_gradient_boosting())
        add("hgb_no_odds_full_history", _predict(hgb_no_odds_history, test, no_odds_features))
        lr_no_odds_history = _fit_pipeline(train_history, no_odds_features, _logistic_regression())
        add("lr_no_odds_full_history", _predict(lr_no_odds_history, test, no_odds_features))

        # --- trained, with odds ---
        market_logit = _fit_pipeline(train_odds, ["bm_market_logit"], _logistic_regression())
        add("market_logit_recalibrated", _predict(market_logit, test, ["bm_market_logit"]))
        lr_odds = _fit_pipeline(train_odds, with_odds_features, _logistic_regression())
        add("lr_with_odds", _predict(lr_odds, test, with_odds_features))
        hgb_odds = _fit_pipeline(train_odds, with_odds_features, _hist_gradient_boosting())
        add("hgb_with_odds", _predict(hgb_odds, test, with_odds_features))
        xgb_odds = _fit_pipeline(train_odds, with_odds_features, _xgboost())
        add("xgb_with_odds", _predict(xgb_odds, test, with_odds_features))

        # One model per inferred circuit (only where both sides have enough rows).
        per_tour = np.full(len(test), np.nan)
        pooled = predictions["hgb_with_odds"][-1]
        for label in ("men_matched", "not_matched"):
            train_part = train_odds[train_odds["bm_tour_inferred"] == label]
            test_part = (test["bm_tour_inferred"] == label).to_numpy()
            if len(train_part) >= 3000 and test_part.any():
                model = _fit_pipeline(train_part, with_odds_features, _hist_gradient_boosting())
                per_tour[test_part] = _predict(model, test[test_part], with_odds_features)
        per_tour = np.where(np.isnan(per_tour), pooled, per_tour)
        add("hgb_with_odds_per_inferred_tour", per_tour)

        # --- production feature list: train/serve skew ---
        v4_full = _fit_pipeline(train_odds, PRODUCTION_V4_FEATURES, _v4_like_voting())
        p_true = _predict(v4_full, test, PRODUCTION_V4_FEATURES)
        add("v4_like__true_features", p_true)
        add("v4_like__serving_enrichment_zeros", _predict(v4_full, apply_serving_enrichment_defaults(test), PRODUCTION_V4_FEATURES))
        add(
            "v4_like__serving_enrichment_zeros_and_rank_fallback",
            _predict(v4_full, apply_serving_rank_fallback(apply_serving_enrichment_defaults(test)), PRODUCTION_V4_FEATURES),
        )
        add("v4_like__enrichment_as_missing", _predict(v4_full, apply_missing_enrichment(test), PRODUCTION_V4_FEATURES))
        add(
            "v4_like__enrichment_as_missing_and_rank_fallback",
            _predict(v4_full, apply_serving_rank_fallback(apply_missing_enrichment(test)), PRODUCTION_V4_FEATURES),
        )
        v4_no_enrichment = _fit_pipeline(train_odds, production_no_enrichment, _v4_like_voting())
        add("v4_like__trained_without_enrichment", _predict(v4_no_enrichment, test, production_no_enrichment))
        add(
            "v4_like__trained_without_enrichment__rank_fallback",
            _predict(v4_no_enrichment, apply_serving_rank_fallback(test), production_no_enrichment),
        )
        v4_serving = _fit_pipeline(train_odds, production_serving_available, _v4_like_voting())
        add("v4_like__trained_on_serving_available", _predict(v4_serving, test, production_serving_available))
        add("shrink50__v4_like_true__market", 0.5 * p_true + 0.5 * test["avg_market_prob_player_1"].to_numpy())

        test_frames.append(test)
        note(f"fold {fold['name']} done rows={len(test)} in {time.time() - fold_started:.1f}s")

    test_all = pd.concat(test_frames, axis=0)
    y = test_all[TARGET].to_numpy(dtype=float)
    stacked = {name: np.concatenate(parts) for name, parts in predictions.items()}
    fold_labels = test_all["fold"].to_numpy()
    segments = _segment_definitions(test_all)

    market_ll = log_loss_rows(y, stacked["market_no_vig"])
    market_brier = brier_rows(y, stacked["market_no_vig"])
    recalibrated_ll = log_loss_rows(y, stacked["market_logit_recalibrated"])
    contenders: dict[str, Any] = {}
    for name, p in stacked.items():
        entry: dict[str, Any] = {"overall": summarize(y, p)}
        entry["per_fold"] = {
            fold["name"]: summarize(y[fold_labels == fold["name"]], p[fold_labels == fold["name"]]) for fold in folds
        }
        ll = log_loss_rows(y, p)
        if name != "market_no_vig":
            entry["vs_market"] = {
                "log_loss": paired_bootstrap_delta(ll, market_ll, n_resamples=bootstrap_resamples),
                "brier": paired_bootstrap_delta(brier_rows(y, p), market_brier, n_resamples=bootstrap_resamples),
                "folds_better_log_loss": int(
                    sum(
                        entry["per_fold"][fold["name"]]["log_loss"]
                        < summarize(y[fold_labels == fold["name"]], stacked["market_no_vig"][fold_labels == fold["name"]])["log_loss"]
                        for fold in folds
                    )
                ),
                "folds_total": len(folds),
            }
        if name != "market_logit_recalibrated":
            entry["vs_market_recalibrated"] = {
                "log_loss": paired_bootstrap_delta(ll, recalibrated_ll, n_resamples=bootstrap_resamples),
                "folds_better_log_loss": int(
                    sum(
                        float(ll[fold_labels == fold["name"]].mean())
                        < float(recalibrated_ll[fold_labels == fold["name"]].mean())
                        for fold in folds
                    )
                ),
                "folds_total": len(folds),
            }
        entry["segments"] = {
            segment_name: {
                str(value): summarize(y[(labels == value).to_numpy()], p[(labels == value).to_numpy()])
                for value in sorted(labels.unique(), key=str)
            }
            for segment_name, labels in segments.items()
        }
        entry["calibration_bins"] = calibration_bins(y, p)
        contenders[name] = entry

    def skew_delta(candidate: str, reference: str) -> dict[str, Any]:
        ll_c = log_loss_rows(y, stacked[candidate])
        ll_r = log_loss_rows(y, stacked[reference])
        per_fold = {
            fold["name"]: round(float((ll_c - ll_r)[fold_labels == fold["name"]].mean()), 5) for fold in folds
        }
        return {
            "candidate": candidate,
            "reference": reference,
            "log_loss": paired_bootstrap_delta(ll_c, ll_r, n_resamples=bootstrap_resamples),
            "brier": paired_bootstrap_delta(
                brier_rows(y, stacked[candidate]), brier_rows(y, stacked[reference]), n_resamples=bootstrap_resamples
            ),
            "log_loss_delta_per_fold": per_fold,
            "folds_candidate_worse": int(sum(v > 0 for v in per_fold.values())),
            "mean_abs_probability_shift": round(float(np.abs(stacked[candidate] - stacked[reference]).mean()), 5),
            "p95_abs_probability_shift": round(
                float(np.quantile(np.abs(stacked[candidate] - stacked[reference]), 0.95)), 5
            ),
            "pick_flip_rate": round(float(((stacked[candidate] >= 0.5) != (stacked[reference] >= 0.5)).mean()), 5),
        }

    reference = "v4_like__true_features"
    train_serve_skew = {
        "note": (
            "Positive deltas mean the candidate is worse than the reference. "
            "All variants are scored out-of-sample on the same test rows."
        ),
        "comparisons": [
            skew_delta("v4_like__serving_enrichment_zeros", reference),
            skew_delta("v4_like__serving_enrichment_zeros_and_rank_fallback", reference),
            skew_delta("v4_like__enrichment_as_missing", reference),
            skew_delta("v4_like__enrichment_as_missing_and_rank_fallback", reference),
            skew_delta("v4_like__trained_without_enrichment", reference),
            skew_delta("v4_like__trained_without_enrichment__rank_fallback", reference),
            skew_delta("v4_like__trained_on_serving_available", reference),
            skew_delta(
                "v4_like__trained_on_serving_available", "v4_like__serving_enrichment_zeros_and_rank_fallback"
            ),
            skew_delta(
                "v4_like__enrichment_as_missing_and_rank_fallback",
                "v4_like__serving_enrichment_zeros_and_rank_fallback",
            ),
            skew_delta("hgb_with_odds_per_inferred_tour", "hgb_with_odds"),
        ],
    }

    import sklearn
    import xgboost

    report = {
        "benchmark": "match_winner_walk_forward",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "command": "python -m backend.src.app.ml.benchmarks.match_winner_walk_forward",
        "dataset": {
            "path": str(dataset_path.relative_to(REPO_ROOT)) if dataset_path.is_relative_to(REPO_ROOT) else str(dataset_path),
            "sha256": file_sha256(dataset_path),
            "rows": int(len(dataframe)),
            "rows_with_valid_odds": int(dataframe["has_odds"].sum()),
            "date_min": dataframe["match_date"].min().date().isoformat(),
            "date_max": dataframe["match_date"].max().date().isoformat(),
            "odds_date_min": odds_rows["match_date"].min().date().isoformat(),
            "odds_date_max": odds_rows["match_date"].max().date().isoformat(),
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "xgboost": xgboost.__version__,
        },
        "protocol": {
            "folds": "expanding window, one test fold per calendar quarter with enough rows with odds",
            "min_train_rows": min_train_rows,
            "min_test_rows": min_test_rows,
            "same_day_batching": True,
            "post_match_columns_excluded": sorted(POST_MATCH_COLUMNS),
            "bootstrap_resamples": bootstrap_resamples,
            "tour_inference": infer_tour.__doc__,
            "feature_sets": {
                "no_odds": no_odds_features,
                "with_odds": with_odds_features,
                "production_v4": PRODUCTION_V4_FEATURES,
                "production_without_enrichment": production_no_enrichment,
                "production_serving_available": production_serving_available,
            },
        },
        "folds": fold_info,
        "test_rows_total": int(len(test_all)),
        "elo_selection": {
            "window": "730 days before the first test fold",
            "grid": elo_selection,
            "selected_dynamic_config": selected_dynamic,
        },
        "dataset_elo_audit": dataset_elo_audit,
        "contenders": contenders,
        "train_serve_skew": train_serve_skew,
        "elapsed_seconds": round(time.time() - started, 1),
    }
    return report


def production_artifact_sensitivity(
    dataset_path: Path = DEFAULT_DATASET_PATH,
    artifact_path: Path = DEFAULT_PRODUCTION_ARTIFACT_PATH,
    *,
    since: str = "2025-01-01",
    bootstrap_resamples: int = 1000,
) -> dict[str, Any] | None:
    """Sensitivity of the committed production artifact to the serving-time fill.

    IN-SAMPLE: the artifact was trained on this very dataset, so its absolute
    scores here are optimistic and must not be read as accuracy. What is
    informative is the *difference* between input variants scored by the same
    fitted model on the same rows. ``since`` defaults to the period where the
    dataset has no ATP enrichment at all, i.e. rows that look like serving.
    """
    import pickle

    if not artifact_path.exists():
        return None
    with artifact_path.open("rb") as handle:
        artifact = pickle.load(handle)
    features = list(artifact["feature_columns"])
    pipeline = artifact["pipeline"]

    dataframe = load_dataset(dataset_path)
    rows = dataframe[valid_odds_mask(dataframe) & (dataframe["match_date"] >= pd.Timestamp(since))].copy()
    if rows.empty:
        return None
    y = rows[TARGET].to_numpy(dtype=float)
    variants = {
        "dataset_values": rows,
        "serving_enrichment_zeros": apply_serving_enrichment_defaults(rows),
        "serving_enrichment_zeros_and_rank_fallback": apply_serving_rank_fallback(apply_serving_enrichment_defaults(rows)),
        "enrichment_as_missing": apply_missing_enrichment(rows),
        "enrichment_as_missing_and_rank_fallback": apply_serving_rank_fallback(apply_missing_enrichment(rows)),
    }
    scored = {name: pipeline.predict_proba(frame[features])[:, 1] for name, frame in variants.items()}
    scored["market_no_vig"] = rows["avg_market_prob_player_1"].to_numpy()
    reference = scored["dataset_values"]

    def delta(candidate: str, other: str) -> dict[str, Any]:
        return {
            "candidate": candidate,
            "reference": other,
            "log_loss": paired_bootstrap_delta(
                log_loss_rows(y, scored[candidate]), log_loss_rows(y, scored[other]), n_resamples=bootstrap_resamples
            ),
            "mean_abs_probability_shift": round(float(np.abs(scored[candidate] - scored[other]).mean()), 5),
            "p95_abs_probability_shift": round(float(np.quantile(np.abs(scored[candidate] - scored[other]), 0.95)), 5),
            "pick_flip_rate": round(float(((scored[candidate] >= 0.5) != (scored[other] >= 0.5)).mean()), 5),
        }

    return {
        "warning": "IN-SAMPLE: the artifact was trained on this dataset; only differences between variants are meaningful.",
        "artifact": str(artifact_path.relative_to(REPO_ROOT)) if artifact_path.is_relative_to(REPO_ROOT) else str(artifact_path),
        "artifact_sha256": file_sha256(artifact_path),
        "rows": int(len(rows)),
        "since": since,
        "enrichment_matched_share_in_rows": round(float(rows["atp_match_found"].mean()), 4),
        "scores": {name: summarize(y, p) for name, p in scored.items()},
        "comparisons": [
            delta("serving_enrichment_zeros", "dataset_values"),
            delta("serving_enrichment_zeros_and_rank_fallback", "dataset_values"),
            delta("enrichment_as_missing", "dataset_values"),
            delta("enrichment_as_missing_and_rank_fallback", "dataset_values"),
            delta("serving_enrichment_zeros_and_rank_fallback", "market_no_vig"),
            delta("enrichment_as_missing_and_rank_fallback", "market_no_vig"),
        ],
        "mean_probability": {name: round(float(np.mean(p)), 4) for name, p in scored.items()},
        "reference_note": f"mean target = {round(float(y.mean()), 4)}",
    }


def ranking_table(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, entry in report["contenders"].items():
        row = {"contender": name, **entry["overall"]}
        if "vs_market" in entry:
            row["delta_log_loss_vs_market"] = entry["vs_market"]["log_loss"]["mean_delta"]
            row["ci95"] = [entry["vs_market"]["log_loss"]["ci95_low"], entry["vs_market"]["log_loss"]["ci95_high"]]
            row["folds_better"] = f"{entry['vs_market']['folds_better_log_loss']}/{entry['vs_market']['folds_total']}"
        if "vs_market_recalibrated" in entry:
            row["delta_log_loss_vs_recalibrated_market"] = entry["vs_market_recalibrated"]["log_loss"]["mean_delta"]
        rows.append(row)
    return sorted(rows, key=lambda row: row["log_loss"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--bootstrap-resamples", type=int, default=1000)
    parser.add_argument("--max-rows", type=int, default=None, help="Debug only: keep the last N rows.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    import warnings

    warnings.filterwarnings("ignore", category=UserWarning)

    report = run_benchmark(args.dataset, bootstrap_resamples=args.bootstrap_resamples, max_rows=args.max_rows)
    if args.max_rows is None:
        report["production_artifact_sensitivity"] = production_artifact_sensitivity(
            args.dataset, bootstrap_resamples=args.bootstrap_resamples
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False)
    for row in ranking_table(report):
        print(row)
    sensitivity = report.get("production_artifact_sensitivity")
    if sensitivity:
        print("production artifact sensitivity (in-sample):")
        for comparison in sensitivity["comparisons"]:
            print(comparison)
    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
