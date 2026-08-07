"""
Pre-match feature builder and ML inference for upcoming fixtures.

Uses historical completed fixtures only (anti-leakage). v2 requires Elo/rank
state built from fixture history; ranking lookup is cached per predictor run.
"""
from __future__ import annotations

import logging
import pickle
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Callable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.dataset_builder import (
    LegacyMatchRow,
    MISSING_RANK_VALUE,
    PlayerHistoryItem,
    _days_since_last_match,
    _h2h_key,
    _matches_last_14_days,
    _normalise_surface,
    _surface_h2h_key,
    _win_rate_last_n,
    build_historical_ranking_lookup,
    clean_dataset_dataframe,
    clean_dataset_dataframe_v2,
    load_legacy_match_rows,
)
from backend.src.app.ml.datasets.elo_builder import EloTracker
from backend.src.app.ml.datasets.odds_builder import FixtureOddsRecord, match_winner_rows_from_record
from backend.src.app.ml.datasets.ranking_history import HistoricalRankingLookup
from backend.src.app.ml.model_versioning import (
    ATP_DATA_DIR,
    MATCH_MAPPING_PATH,
    MODEL_VERSIONS,
    ModelVersion,
    PROCESSED_DATA_DIR,
    select_training_dataset_path,
)
from backend.src.entity import MatchPrediction, NextFixture

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "logistic_regression"
ATP_DEFAULTS: dict[str, Any] = {
    "atp_match_found": 0,
    "player_1_atp_rank": MISSING_RANK_VALUE,
    "player_2_atp_rank": MISSING_RANK_VALUE,
    "atp_rank_diff": 0,
    "player_1_atp_rank_points": 0,
    "player_2_atp_rank_points": 0,
    "atp_rank_points_diff": 0,
    "player_1_age": 0.0,
    "player_2_age": 0.0,
    "age_diff": 0.0,
    "player_1_height": 0.0,
    "player_2_height": 0.0,
    "height_diff": 0.0,
    "player_1_hand": "unknown",
    "player_2_hand": "unknown",
    "atp_surface": "unknown",
    "atp_tourney_level": "unknown",
    "atp_round": "unknown",
    "atp_best_of": 3,
}
ODDS_FEATURE_COLUMNS = (
    "avg_player_1_odds",
    "avg_player_2_odds",
    "avg_market_prob_player_1",
    "avg_market_prob_player_2",
    "avg_bookmaker_margin",
    "odds_bookmaker_count",
)


def _ensure_logistic_regression_compat(obj: Any) -> bool:
    """Patch missing attrs on legacy pickled LogisticRegression objects."""
    if obj.__class__.__name__ != "LogisticRegression":
        return False

    patched = False
    defaults = {
        # Required by newer sklearn predict/predict_proba code paths.
        "multi_class": "auto",
    }
    for attr_name, default_value in defaults.items():
        if not hasattr(obj, attr_name):
            setattr(obj, attr_name, default_value)
            patched = True
    return patched


def _patch_artifact_for_runtime_compat(artifact: dict[str, Any]) -> None:
    """Best-effort compatibility patch for loaded model artifacts."""
    pipeline = artifact.get("pipeline")
    if pipeline is None:
        return

    # Try direct estimator first.
    if _ensure_logistic_regression_compat(pipeline):
        return

    # sklearn Pipeline stores fitted steps in named_steps.
    named_steps = getattr(pipeline, "named_steps", None)
    if not named_steps:
        return
    for step in named_steps.values():
        _ensure_logistic_regression_compat(step)


@dataclass
class PreMatchFeatureBuilder:
    """Rolling player/H2H/Elo/rank state from completed historical matches."""

    player_history: dict[int, list[PlayerHistoryItem]] = field(default_factory=dict)
    h2h: dict[tuple[int, int], dict[int, int]] = field(default_factory=dict)
    surface_h2h: dict[tuple[int, int, str], dict[int, int]] = field(default_factory=dict)
    elo_tracker: EloTracker = field(default_factory=EloTracker)
    ranking_lookup: HistoricalRankingLookup | None = None

    @classmethod
    def from_db(cls, db: Session, model_version: ModelVersion = "v2") -> PreMatchFeatureBuilder:
        builder = cls()
        matches = load_legacy_match_rows(db)
        builder._ingest_history(matches)
        if model_version in {"v2", "v3", "v4"}:
            try:
                base_path = select_training_dataset_path(PROCESSED_DATA_DIR, version=model_version)
            except FileNotFoundError:
                try:
                    base_path = (
                        select_training_dataset_path(PROCESSED_DATA_DIR, version="v2")
                        if model_version in {"v3", "v4"}
                        else None
                    )
                except FileNotFoundError:
                    base_path = None
            builder.ranking_lookup = build_historical_ranking_lookup(
                ATP_DATA_DIR,
                MATCH_MAPPING_PATH,
                base_dataset_path=base_path,
            )
        return builder

    def _ingest_history(self, matches: list[LegacyMatchRow]) -> None:
        for match in matches:
            player_1_won = match.target_player_1_win == 1
            player_2_won = not player_1_won
            self.player_history.setdefault(match.player_1_id, []).append(
                PlayerHistoryItem(
                    match_date=match.match_date,
                    surface=match.surface,
                    won=player_1_won,
                )
            )
            self.player_history.setdefault(match.player_2_id, []).append(
                PlayerHistoryItem(
                    match_date=match.match_date,
                    surface=match.surface,
                    won=player_2_won,
                )
            )

            pair_key = _h2h_key(match.player_1_id, match.player_2_id)
            self.h2h.setdefault(pair_key, {})
            winner_id = match.player_1_id if player_1_won else match.player_2_id
            self.h2h[pair_key][winner_id] = self.h2h[pair_key].get(winner_id, 0) + 1

            surface_key = _surface_h2h_key(
                match.player_1_id,
                match.player_2_id,
                match.surface,
            )
            self.surface_h2h.setdefault(surface_key, {})
            self.surface_h2h[surface_key][winner_id] = (
                self.surface_h2h[surface_key].get(winner_id, 0) + 1
            )

            self.elo_tracker.record_match(
                match.player_1_id,
                match.player_2_id,
                match.surface,
                player_1_won,
            )

    def build_feature_row(
        self,
        *,
        event_key: int,
        match_date: date,
        surface: str | None,
        player_1_id: int,
        player_2_id: int,
        model_version: ModelVersion,
        odds: Any = None,
    ) -> tuple[dict[str, Any], list[str], bool]:
        normalised_surface = _normalise_surface(surface)
        player_1_history = self.player_history.get(player_1_id, [])
        player_2_history = self.player_history.get(player_2_id, [])
        h2h_wins = self.h2h.get(_h2h_key(player_1_id, player_2_id), {})
        surface_wins = self.surface_h2h.get(
            _surface_h2h_key(player_1_id, player_2_id, normalised_surface),
            {},
        )

        row: dict[str, Any] = {
            "match_id": event_key,
            "match_date": match_date,
            "surface": normalised_surface,
            "player_1_id": player_1_id,
            "player_2_id": player_2_id,
            "player_1_last_5_win_rate": _win_rate_last_n(player_1_history, 5),
            "player_2_last_5_win_rate": _win_rate_last_n(player_2_history, 5),
            "player_1_last_10_win_rate": _win_rate_last_n(player_1_history, 10),
            "player_2_last_10_win_rate": _win_rate_last_n(player_2_history, 10),
            "player_1_surface_last_10_win_rate": _win_rate_last_n(
                player_1_history,
                10,
                surface=normalised_surface,
            ),
            "player_2_surface_last_10_win_rate": _win_rate_last_n(
                player_2_history,
                10,
                surface=normalised_surface,
            ),
            "player_1_matches_last_14_days": _matches_last_14_days(
                player_1_history,
                match_date,
            ),
            "player_2_matches_last_14_days": _matches_last_14_days(
                player_2_history,
                match_date,
            ),
            "player_1_days_since_last_match": _days_since_last_match(
                player_1_history,
                match_date,
            ),
            "player_2_days_since_last_match": _days_since_last_match(
                player_2_history,
                match_date,
            ),
            "h2h_player_1_wins": h2h_wins.get(player_1_id, 0),
            "h2h_player_2_wins": h2h_wins.get(player_2_id, 0),
            "h2h_surface_player_1_wins": surface_wins.get(player_1_id, 0),
            "h2h_surface_player_2_wins": surface_wins.get(player_2_id, 0),
            "target_player_1_win": 0,
        }

        warnings: list[str] = []
        features_available = bool(player_1_history or player_2_history)

        if model_version in {"v2", "v3", "v4"}:
            rank_features = (self.ranking_lookup or HistoricalRankingLookup(pd.DataFrame(), {})).pre_match_features(
                player_1_id,
                player_2_id,
                match_date,
            )
            elo_features = self.elo_tracker.pre_match_features(
                player_1_id,
                player_2_id,
                normalised_surface,
            )
            row.update(
                {
                    "player_1_rank": rank_features.player_1_rank,
                    "player_2_rank": rank_features.player_2_rank,
                    "rank_diff": rank_features.rank_diff,
                    "player_1_rank_points": rank_features.player_1_rank_points,
                    "player_2_rank_points": rank_features.player_2_rank_points,
                    "rank_points_diff": rank_features.rank_points_diff,
                    "player_1_elo": elo_features.player_1_elo,
                    "player_2_elo": elo_features.player_2_elo,
                    "elo_diff": elo_features.elo_diff,
                    "player_1_surface_elo": elo_features.player_1_surface_elo,
                    "player_2_surface_elo": elo_features.player_2_surface_elo,
                    "surface_elo_diff": elo_features.surface_elo_diff,
                }
            )
            if rank_features.player_1_rank == MISSING_RANK_VALUE:
                warnings.append("ranking_fallback_used")
        else:
            row.update(
                {
                    "player_1_rank": None,
                    "player_2_rank": None,
                    "rank_diff": None,
                    "player_1_elo": None,
                    "player_2_elo": None,
                    "elo_diff": None,
                    "player_1_surface_elo": None,
                    "player_2_surface_elo": None,
                    "surface_elo_diff": None,
                }
            )

        row.update(ATP_DEFAULTS)
        row["atp_surface"] = normalised_surface

        if model_version in {"v3", "v4"}:
            odds_features = odds_feature_row(
                event_key=event_key,
                match_date=match_date,
                player_1_id=player_1_id,
                player_2_id=player_2_id,
                odds=odds,
            )
            if odds_features is None:
                warnings.append("missing_odds")
                features_available = False
            else:
                row.update(odds_features)

        if not player_1_history:
            warnings.append("player_1_no_history")
        if not player_2_history:
            warnings.append("player_2_no_history")

        return row, warnings, features_available


def _clean_features(row: dict[str, Any], model_version: ModelVersion) -> pd.DataFrame:
    dataframe = pd.DataFrame([row])
    if model_version in {"v3", "v4"}:
        cleaned = clean_dataset_dataframe_v2(dataframe)
        for column in ODDS_FEATURE_COLUMNS:
            if column in dataframe.columns and not cleaned.empty:
                cleaned[column] = pd.to_numeric(dataframe[column], errors="coerce").values
        return cleaned
    if model_version == "v2":
        return clean_dataset_dataframe_v2(dataframe)
    return clean_dataset_dataframe(dataframe)


def odds_feature_row(
    *,
    event_key: int,
    match_date: date,
    player_1_id: int,
    player_2_id: int,
    odds: Any,
) -> dict[str, Any] | None:
    rows = match_winner_rows_from_record(
        FixtureOddsRecord(
            match_id=event_key,
            match_date=match_date,
            player_1_id=player_1_id,
            player_2_id=player_2_id,
            player_1_name=None,
            player_2_name=None,
            odds=odds,
        )
    )
    if not rows:
        return None
    bookmakers = {row["bookmaker"] for row in rows}
    return {
        "avg_player_1_odds": sum(row["player_1_odds"] for row in rows) / len(rows),
        "avg_player_2_odds": sum(row["player_2_odds"] for row in rows) / len(rows),
        "avg_market_prob_player_1": sum(row["market_prob_player_1"] for row in rows) / len(rows),
        "avg_market_prob_player_2": sum(row["market_prob_player_2"] for row in rows) / len(rows),
        "avg_bookmaker_margin": sum(row["bookmaker_margin"] for row in rows) / len(rows),
        "odds_bookmaker_count": len(bookmakers),
    }


def _alias_numpy_pickle_modules() -> bool:
    """Alias legacy/new NumPy internal module paths for pickle compatibility."""
    try:
        import numpy.core as np_core
        import numpy.core.numeric as np_numeric
    except ModuleNotFoundError:
        return False

    sys.modules.setdefault("numpy._core", np_core)
    sys.modules.setdefault("numpy._core.numeric", np_numeric)
    return True


@lru_cache(maxsize=4)
def _load_model_artifact(model_version: ModelVersion, model_name: str) -> dict[str, Any]:
    model_path = MODEL_VERSIONS[model_version].models_dir / f"{model_name}.pkl"
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    with model_path.open("rb") as handle:
        try:
            artifact = pickle.load(handle)
            _patch_artifact_for_runtime_compat(artifact)
            return artifact
        except ModuleNotFoundError as exc:
            if not (exc.name or "").startswith("numpy._core"):
                raise
            if not _alias_numpy_pickle_modules():
                raise
            logger.warning(
                "Recovered model loading by aliasing NumPy internals (%s).",
                exc.name,
            )
            handle.seek(0)
            artifact = pickle.load(handle)
            _patch_artifact_for_runtime_compat(artifact)
            return artifact


def predict_fixture(
    fixture: NextFixture,
    *,
    feature_builder: PreMatchFeatureBuilder,
    model_version: ModelVersion,
    model_name: str = DEFAULT_MODEL_NAME,
) -> dict[str, Any]:
    if not fixture.first_player_key or not fixture.second_player_key or not fixture.event_date:
        return {
            "event_key": fixture.event_key,
            "model_version": model_version,
            "model_name": model_name,
            "prob_player_1_win": None,
            "predicted_winner": None,
            "confidence": None,
            "features_available": False,
            "warnings": ["missing_player_keys_or_date"],
        }

    raw_row, warnings, features_available = feature_builder.build_feature_row(
        event_key=fixture.event_key,
        match_date=fixture.event_date,
        surface=fixture.surface,
        player_1_id=fixture.first_player_key,
        player_2_id=fixture.second_player_key,
        model_version=model_version,
        odds=fixture.odds,
    )
    if model_version in {"v3", "v4"} and "missing_odds" in warnings:
        return {
            "event_key": fixture.event_key,
            "model_version": model_version,
            "model_name": model_name,
            "prob_player_1_win": None,
            "predicted_winner": None,
            "confidence": None,
            "features_available": False,
            "warnings": warnings,
        }
    cleaned = _clean_features(raw_row, model_version)
    artifact = _load_model_artifact(model_version, model_name)
    feature_columns = artifact["feature_columns"]
    pipeline = artifact["pipeline"]

    missing_columns = [column for column in feature_columns if column not in cleaned.columns]
    if model_version in {"v3", "v4"}:
        missing_odds_columns = [column for column in ODDS_FEATURE_COLUMNS if column in feature_columns and column not in cleaned.columns]
        if missing_odds_columns:
            return {
                "event_key": fixture.event_key,
                "model_version": model_version,
                "model_name": model_name,
                "prob_player_1_win": None,
                "predicted_winner": None,
                "confidence": None,
                "features_available": False,
                "warnings": [*warnings, f"missing_odds_features:{','.join(missing_odds_columns)}"],
            }
    for column in missing_columns:
        cleaned[column] = 0
    if missing_columns:
        warnings.append(f"missing_feature_columns:{','.join(missing_columns)}")

    probabilities = pipeline.predict_proba(cleaned[feature_columns])[0]
    prob_player_1_win = float(probabilities[1])
    predicted_winner = "First Player" if prob_player_1_win >= 0.5 else "Second Player"
    confidence = max(prob_player_1_win, 1.0 - prob_player_1_win)

    return {
        "event_key": fixture.event_key,
        "model_version": model_version,
        "model_name": model_name,
        "prob_player_1_win": prob_player_1_win,
        "predicted_winner": predicted_winner,
        "confidence": confidence,
        "features_available": features_available,
        "warnings": warnings,
    }


class PredictUpcomingCancelled(Exception):
    """Raised when fixture prediction is cancelled cooperatively."""


def predict_upcoming_fixtures(
    db: Session,
    fixtures: list[NextFixture],
    model_version: ModelVersion = "v2",
    model_name: str = DEFAULT_MODEL_NAME,
    persist: bool = True,
    progress_callback: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    if not fixtures:
        return []

    feature_builder = PreMatchFeatureBuilder.from_db(db, model_version=model_version)
    predictions: list[dict[str, Any]] = []
    predicted_at = datetime.now()

    for fixture_index, fixture in enumerate(fixtures):
        if should_cancel and should_cancel():
            if persist:
                db.commit()
            raise PredictUpcomingCancelled()

        result = predict_fixture(
            fixture,
            feature_builder=feature_builder,
            model_version=model_version,
            model_name=model_name,
        )
        predictions.append(result)

        if progress_callback is not None:
            progress_callback(fixture_index + 1, len(fixtures))

        if persist and result["prob_player_1_win"] is not None:
            row = db.scalar(
                select(MatchPrediction).where(
                    MatchPrediction.event_key == fixture.event_key,
                    MatchPrediction.model_version == model_version,
                    MatchPrediction.model_name == model_name,
                )
            )
            if row and not row.actual_winner:
                row.predicted_at = predicted_at
                row.prob_player_1_win = result["prob_player_1_win"]
                row.predicted_winner = result["predicted_winner"]
            elif row is None:
                row = MatchPrediction(
                    event_key=fixture.event_key,
                    model_version=model_version,
                    model_name=model_name,
                    predicted_at=predicted_at,
                    prob_player_1_win=result["prob_player_1_win"],
                    predicted_winner=result["predicted_winner"],
                )
                db.add(row)

    if persist:
        db.commit()


    return predictions


def clear_model_cache() -> None:
    _load_model_artifact.cache_clear()
