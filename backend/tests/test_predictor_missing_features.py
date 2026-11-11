"""Serving-time fill of unavailable feature columns and data-sufficiency block."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.src.app.core.config import get_settings, set_settings_override
from backend.src.app.ml.datasets.dataset_builder import LegacyMatchRow
from backend.src.app.ml.prediction import predictor as module
from backend.src.app.ml.prediction.data_sufficiency import (
    FEW_BOOKMAKERS,
    LOW_HISTORY_MATCHES,
    STATUS_INSUFFICIENT,
    STATUS_LIMITED,
    STATUS_SUFFICIENT,
    assess_data_sufficiency,
)
from backend.src.app.ml.prediction.predictor import (
    MISSING_FEATURE_POLICY_IMPUTE,
    MISSING_FEATURE_POLICY_ZERO,
    PreMatchFeatureBuilder,
    fill_missing_feature_columns,
    predict_fixture,
)
from backend.src.entity.next_fixture import NextFixture

ENRICHMENT_COLUMNS = [
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
]


def _odds(bookmakers: int = 5) -> dict:
    return {
        "Home/Away": {
            "Home": {f"Book {i}": "1.80" for i in range(bookmakers)},
            "Away": {f"Book {i}": "2.05" for i in range(bookmakers)},
        }
    }


def _fixture(**overrides) -> NextFixture:
    values = dict(
        event_key=900,
        event_date=date(2026, 6, 30),
        first_player_key=10,
        second_player_key=20,
        surface="Hard",
        odds=_odds(),
    )
    values.update(overrides)
    return NextFixture(**values)


def _builder(matches_per_player: int) -> PreMatchFeatureBuilder:
    builder = PreMatchFeatureBuilder()
    rows = []
    for index in range(matches_per_player):
        rows.append(
            LegacyMatchRow(
                match_id=index + 1,
                match_date=date(2026, 5, 1 + index),
                surface="Hard",
                player_1_id=10,
                player_2_id=20,
                target_player_1_win=index % 2,
            )
        )
    builder._ingest_history(rows)
    return builder


@pytest.fixture()
def policy():
    original = get_settings()

    def _set(value: str) -> None:
        set_settings_override(original.model_copy(update={"match_winner_missing_feature_policy": value}))

    yield _set
    set_settings_override(original)


class TestFillMissingFeatureColumns:
    def test_zero_policy_keeps_legacy_values(self):
        frame = fill_missing_feature_columns(pd.DataFrame({"a": [1.0]}), ENRICHMENT_COLUMNS)
        assert (frame[ENRICHMENT_COLUMNS].iloc[0] == 0).all()

    def test_impute_policy_declares_columns_missing(self):
        frame = fill_missing_feature_columns(
            pd.DataFrame({"a": [1.0]}), ENRICHMENT_COLUMNS, policy=MISSING_FEATURE_POLICY_IMPUTE
        )
        assert np.isnan(frame["player_1_age"].iloc[0])
        assert np.isnan(frame["atp_best_of"].iloc[0])
        assert frame["player_1_hand"].iloc[0] is None
        assert frame["atp_tourney_level"].iloc[0] is None
        assert frame["atp_match_found"].iloc[0] == 0

    def test_unknown_policy_value_falls_back_to_legacy(self, policy):
        policy("something-else")
        assert module.missing_feature_policy() == MISSING_FEATURE_POLICY_ZERO


class TestProductionArtifactServing:
    """Runs the committed v4 artifact: guards the default and the opt-in path."""

    def _predict(self):
        return predict_fixture(
            _fixture(),
            feature_builder=_builder(8),
            model_version="v4",
            model_name="voting_ensemble",
        )

    def test_default_policy_is_legacy_zero_fill(self, policy):
        assert module.missing_feature_policy() == MISSING_FEATURE_POLICY_ZERO
        result = self._predict()
        assert "missing_feature_policy:zero" in result["warnings"]
        assert 0.0 < result["prob_player_1_win"] < 1.0

    def test_impute_policy_uses_training_time_imputers(self, policy):
        legacy = self._predict()
        policy(MISSING_FEATURE_POLICY_IMPUTE)
        imputed = self._predict()

        assert "missing_feature_policy:impute" in imputed["warnings"]
        assert 0.0 < imputed["prob_player_1_win"] < 1.0
        # Same model, same real inputs: only the fill of unavailable columns differs.
        assert imputed["prob_player_1_win"] != pytest.approx(legacy["prob_player_1_win"], abs=1e-9)

        artifact = module._load_model_artifact("v4", "voting_ensemble")
        builder = _builder(8)
        fixture = _fixture()
        row, _warnings, _available = builder.build_feature_row(
            event_key=fixture.event_key,
            match_date=fixture.event_date,
            surface=fixture.surface,
            player_1_id=fixture.first_player_key,
            player_2_id=fixture.second_player_key,
            model_version="v4",
            odds=fixture.odds,
        )
        cleaned = module._clean_features(row, "v4")
        for column in ["player_1_age", "player_2_age", "age_diff", "player_1_height", "player_2_height", "height_diff", "atp_best_of"]:
            cleaned[column] = np.nan
        for column in ["player_1_hand", "player_2_hand", "atp_surface", "atp_tourney_level", "atp_round"]:
            cleaned[column] = pd.Series([None], dtype=object)
        cleaned["atp_match_found"] = 0
        expected = float(artifact["pipeline"].predict_proba(cleaned[artifact["feature_columns"]])[0][1])
        assert imputed["prob_player_1_win"] == pytest.approx(expected, abs=1e-12)

    def test_result_reports_unavailable_columns_without_downgrading_status(self, policy):
        result = self._predict()
        quality = result["data_quality"]
        assert set(ENRICHMENT_COLUMNS) == set(quality["details"]["unavailable_feature_columns"])
        assert "enrichment_features_unavailable" in quality["systemic_gaps"]
        assert quality["status"] == STATUS_SUFFICIENT
        assert quality["details"]["player_1_prior_matches"] == 8
        assert quality["details"]["bookmaker_count"] == 5


class TestDataSufficiencyInPredictions:
    def test_no_history_is_limited_not_hidden(self):
        result = predict_fixture(
            _fixture(), feature_builder=PreMatchFeatureBuilder(), model_version="v4", model_name="voting_ensemble"
        )
        assert result["prob_player_1_win"] is not None
        assert result["data_quality"]["status"] == STATUS_LIMITED
        assert {"player_1_no_history", "player_2_no_history"} <= set(result["data_quality"]["reasons"])

    def test_missing_odds_is_insufficient_and_abstains(self):
        result = predict_fixture(
            _fixture(odds=None), feature_builder=_builder(8), model_version="v4", model_name="voting_ensemble"
        )
        assert result["prob_player_1_win"] is None
        assert result["data_quality"]["status"] == STATUS_INSUFFICIENT
        assert "missing_odds" in result["data_quality"]["reasons"]

    def test_missing_keys_is_insufficient(self):
        result = predict_fixture(
            _fixture(first_player_key=None), feature_builder=_builder(8), model_version="v4", model_name="voting_ensemble"
        )
        assert result["data_quality"]["status"] == STATUS_INSUFFICIENT


class TestAssessDataSufficiency:
    def test_sufficient_when_everything_is_known(self):
        quality = assess_data_sufficiency(
            player_1_prior_matches=40,
            player_2_prior_matches=25,
            surface_known=True,
            ranking_available=True,
            odds_available=True,
            bookmaker_count=11,
        )
        assert quality == {
            "status": STATUS_SUFFICIENT,
            "reasons": [],
            "systemic_gaps": [],
            "details": quality["details"],
        }

    def test_low_history_surface_and_few_bookmakers_are_limited(self):
        quality = assess_data_sufficiency(
            player_1_prior_matches=LOW_HISTORY_MATCHES - 1,
            player_2_prior_matches=LOW_HISTORY_MATCHES,
            surface_known=False,
            bookmaker_count=FEW_BOOKMAKERS,
        )
        assert quality["status"] == STATUS_LIMITED
        assert quality["reasons"] == ["player_1_low_history", "surface_unknown", "few_bookmakers"]

    def test_not_evaluated_inputs_are_neither_problems_nor_confirmations(self):
        quality = assess_data_sufficiency(bookmaker_count=10)
        assert quality["status"] == STATUS_SUFFICIENT
        assert quality["details"]["player_1_prior_matches"] is None
        assert quality["details"]["surface_known"] is None

    def test_ranking_gap_is_systemic_not_a_downgrade(self):
        quality = assess_data_sufficiency(
            player_1_prior_matches=30, player_2_prior_matches=30, ranking_available=False, bookmaker_count=9
        )
        assert quality["status"] == STATUS_SUFFICIENT
        assert quality["systemic_gaps"] == ["ranking_unavailable"]
