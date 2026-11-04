from datetime import date

import pytest
from sqlalchemy.orm import Session

from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.published_predictions import publish_prediction
from backend.src.jobs.generate_extra_market_predictions import (
    _already_published,
    _publish_result,
)


class _FixtureStub:
    def __init__(self, event_key: int) -> None:
        self.event_key = event_key
        self.event_first_player = "Player A"
        self.event_second_player = "Player B"
        self.tournament_name = "Test Open"
        self.event_date = date(2026, 12, 1)
        self.event_time = None


def _publish(db: Session, *, event_key: int, selection: str, model_version: str) -> None:
    publish_prediction(
        db,
        PublishedPredictionCreate(
            event_key=event_key,
            selection=selection,
            model_version=model_version,
            model_name="random_forest",
            probability=0.6,
            publication_source="system",
            event_date=date(2026, 12, 1),
        ),
    )


class TestAlreadyPublished:
    def test_returns_false_when_no_publication_exists(self, db_session: Session) -> None:
        assert not _already_published(
            db_session,
            event_key=1,
            selection="First Player",
            model_version="first_set_winner_v1",
            model_name="random_forest",
            publication_source="system",
        )

    def test_returns_true_after_publishing(self, db_session: Session) -> None:
        _publish(db_session, event_key=1, selection="First Player", model_version="first_set_winner_v1")

        assert _already_published(
            db_session,
            event_key=1,
            selection="First Player",
            model_version="first_set_winner_v1",
            model_name="random_forest",
            publication_source="system",
        )

    def test_different_market_selection_is_independent(self, db_session: Session) -> None:
        """Stesso event_key, mercato diverso (model_version diverso): nessuna collisione."""
        _publish(db_session, event_key=1, selection="First Player", model_version="first_set_winner_v1")

        assert not _already_published(
            db_session,
            event_key=1,
            selection="Over 20.5",
            model_version="over_under_games_v1",
            model_name="random_forest",
            publication_source="system",
        )


class TestPublishResult:
    def test_no_probability_is_skipped(self, db_session: Session) -> None:
        result = {"event_key": 1, "selection": None, "probability": None}
        status = _publish_result(
            db_session, _FixtureStub(1), result, publication_source="system", dry_run=False,
        )
        assert status == "skipped_no_probability"

    @pytest.mark.parametrize("probability", [0.0, 1.0, -0.1, 1.1, float("nan")])
    def test_invalid_probability_is_skipped_without_persisting(
        self,
        db_session: Session,
        probability: float,
    ) -> None:
        result = {
            "event_key": 4,
            "selection": "First Player",
            "probability": probability,
            "model_version": "first_set_winner_v1",
            "model_name": "random_forest",
        }

        status = _publish_result(
            db_session,
            _FixtureStub(4),
            result,
            publication_source="system",
            dry_run=False,
        )

        assert status == "skipped_invalid_probability"
        assert not _already_published(
            db_session,
            event_key=4,
            selection="First Player",
            model_version="first_set_winner_v1",
            model_name="random_forest",
            publication_source="system",
        )

    def test_dry_run_does_not_persist(self, db_session: Session) -> None:
        result = {
            "event_key": 2, "selection": "First Player", "probability": 0.6,
            "model_version": "first_set_winner_v1", "model_name": "random_forest",
        }
        status = _publish_result(
            db_session, _FixtureStub(2), result, publication_source="system", dry_run=True,
        )
        assert status == "published"
        assert not _already_published(
            db_session, event_key=2, selection="First Player",
            model_version="first_set_winner_v1", model_name="random_forest", publication_source="system",
        )

    def test_publishes_and_then_skips_duplicate(self, db_session: Session) -> None:
        result = {
            "event_key": 3, "selection": "Over 20.5", "probability": 0.55,
            "model_version": "over_under_games_v1", "model_name": "random_forest",
        }
        first_status = _publish_result(
            db_session, _FixtureStub(3), result, publication_source="system", dry_run=False,
        )
        second_status = _publish_result(
            db_session, _FixtureStub(3), result, publication_source="system", dry_run=False,
        )

        assert first_status == "published"
        assert second_status == "skipped_already_published"


class TestMarketBlendOnPublication:
    def _result(self, event_key: int, **extra) -> dict:
        return {
            "event_key": event_key, "market": "over_under_games", "selection": "Over 20.5",
            "probability": 0.80, "model_version": "over_under_games_v1",
            "model_name": "random_forest", "market_odds": 1.50, **extra,
        }

    def _stored(self, db: Session, event_key: int):
        from backend.src.entity.published_prediction import PublishedPrediction

        return db.query(PublishedPrediction).filter_by(event_key=event_key).one()

    def test_decision_uses_probability_blended_with_market(self, db_session: Session) -> None:
        # p_adj = 0.5*0.80 + 0.5*0.60 = 0.70 -> void 1.4286; odds 1.50 >= 1.4286*1.02
        result = self._result(10, market_fair_probability=0.60)
        status = _publish_result(
            db_session, _FixtureStub(10), result, publication_source="system", dry_run=False,
        )
        stored = self._stored(db_session, 10)

        assert status == "published"
        assert stored.probability == pytest.approx(0.80)  # grezza, non ridotta
        assert stored.void_odds == pytest.approx(1 / 0.70, abs=1e-4)
        assert stored.value_decision == "PLAY"

    def test_raw_probability_alone_would_have_been_play_but_blend_removes_it(
        self, db_session: Session
    ) -> None:
        # Con p grezza 0.80 la soglia PLAY e' 1.275: odds 1.35 sarebbe PLAY.
        # Con p_adj = 0.5*0.80 + 0.5*0.70 = 0.75 la soglia sale a 1.36: non e' PLAY.
        result = self._result(11, market_odds=1.35, market_fair_probability=0.70)
        _publish_result(
            db_session, _FixtureStub(11), result, publication_source="system", dry_run=False,
        )
        stored = self._stored(db_session, 11)

        assert stored.value_decision != "PLAY"
        assert stored.official_play is False

    def test_missing_market_probability_is_no_bet(self, db_session: Session) -> None:
        result = self._result(12)  # nessuna market_fair_probability
        _publish_result(
            db_session, _FixtureStub(12), result, publication_source="system", dry_run=False,
        )
        stored = self._stored(db_session, 12)

        assert stored.value_decision == "NO BET"
        assert stored.official_play is False


if __name__ == "__main__":
    pytest.main([__file__])


