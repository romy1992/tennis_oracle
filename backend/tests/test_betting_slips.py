import unittest
from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from sqlalchemy import select

from backend.src.app.main import app
from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.published_predictions import publish_prediction
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client
from backend.tests.auth_helpers import (
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)
from backend.src.app.services.betting_slips import (
    CandidatePick,
    _persist_slips,
    _resolve_pick_status,
    _resolve_slip_status,
    build_candidate_pool,
    compute_betting_slip_model_stats,
    compute_betting_slip_stats,
    generate_experimental_ladders,
    generate_experimental_slips,
    generate_ladders,
    generate_slips,
    get_betting_slip_calendar,
    get_daily_betting_slips,
)
from backend.src.entity import BettingSlip, BettingSlipDay, BettingSlipPick, Fixture, MatchPrediction, NextFixture


def _sample_odds() -> dict:
    return {
        "100": {
            "Home/Away": {
                "Home": {"Book A": "1.50", "Book B": "1.55"},
                "Away": {"Book A": "2.60", "Book B": "2.50"},
            }
        }
    }


def _sample_mixed_market_odds() -> dict:
    return {
        "Home/Away": {
            "Home": {"Book A": "1.50", "Book B": "1.55"},
            "Away": {"Book A": "2.60", "Book B": "2.50"},
        },
        "Over/Under by Games in Match": {
            "Over/Under by Games in Match Over": {
                "20.5": {"Book A": "1.90", "Book B": "1.94"},
            },
            "Over/Under by Games in Match Under": {
                "20.5": {"Book A": "1.90", "Book B": "1.86"},
            },
        },
    }


class BettingSlipsServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.today = date.today()

    def tearDown(self):
        self.engine.dispose()

    def _seed_candidates(self, session, count: int = 6, start_key: int = 100):
        rows = []
        for index in range(count):
            event_key = start_key + index
            rows.append(
                NextFixture(
                    event_key=event_key,
                    event_date=self.today,
                    event_time=time(14, index),
                    event_first_player=f"Player A{index}",
                    event_second_player=f"Player B{index}",
                    tournament_name=f"Tournament {index % 3}",
                    surface=["Hard", "Clay", "Grass"][index % 3],
                    odds=_sample_odds(),
                    is_completed=False,
                )
            )
            rows.append(
                MatchPrediction(
                    event_key=event_key,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.72 + index * 0.01,
                    predicted_winner="First Player",
                )
            )
        session.add_all(rows)
        session.commit()

    def _seed_stats_slip(
        self,
        session,
        *,
        event_key: int,
        slip_date: date,
        model_version: str,
        model_name: str,
        actual_winner: str | None,
        predicted_winner: str = "First Player",
        combined_odds: float = 2.0,
        strategy_family: str = "generic",
        strategy_version: str = "legacy_v1",
        is_experimental: bool = False,
    ):
        slip = BettingSlip(
            slip_date=slip_date,
            slip_key=f"safe-{event_key}",
            label="Sicura",
            description="Stats test",
            model_version=model_version,
            model_name=model_name,
            strategy_family=strategy_family,
            strategy_version=strategy_version,
            is_experimental=is_experimental,
            pick_count=1,
            combined_odds=combined_odds,
            generated_at=datetime(2026, 6, 28, 9, 0, 0),
        )
        session.add(slip)
        session.flush()
        session.add(
            BettingSlipPick(
                betting_slip_id=slip.id,
                event_key=event_key,
                event_date=slip_date,
                event_time=time(14, 0),
                tournament_name="Stats Open",
                surface="Hard",
                player_1_name="Player A",
                player_2_name="Player B",
                predicted_winner=predicted_winner,
                predicted_winner_label="Player A",
                odds=combined_odds,
                sort_order=0,
            )
        )
        if actual_winner is not None:
            session.add(
                Fixture(
                    id_fixture=event_key,
                    event_key=event_key,
                    event_date=slip_date,
                    event_first_player="Player A",
                    event_second_player="Player B",
                    event_winner=actual_winner,
                )
            )
        session.commit()

    def _strategy_candidate(
        self,
        event_key: int,
        *,
        market: str,
        decision: str = "PLAY",
        odds: float = 1.6,
        score: float = 1.0,
    ) -> CandidatePick:
        return CandidatePick(
            event_key=event_key,
            event_date=self.today,
            event_time=time(12 + event_key % 8, 0),
            tournament_name=f"Strategy Open {event_key % 2}",
            surface="Hard",
            player_1_name=f"Player A{event_key}",
            player_2_name=f"Player B{event_key}",
            predicted_winner="First Player",
            predicted_winner_label=f"Player A{event_key}",
            model_prob=0.7,
            market_prob=0.55,
            edge=0.15,
            odds=odds,
            void_odds=1.43,
            edge_absolute=odds - 1.43,
            edge_percent=(odds - 1.43) / 1.43 * 100,
            expected_roi=0.7 * odds - 1.0,
            suggested_min_edge_percent=2.0,
            min_edge_percent=2.0,
            value_decision=decision,
            value_label=decision,
            confidence=0.7,
            pick_score=score,
            market=market,
        )

    def test_build_candidate_pool_excludes_missing_odds(self):
        with self.Session() as session:
            self._seed_candidates(session, count=1)
            session.add(
                NextFixture(
                    event_key=999,
                    event_date=self.today,
                    event_first_player="No Odds",
                    event_second_player="Also None",
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=999,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.8,
                    predicted_winner="First Player",
                )
            )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].event_key, 100)
            self.assertEqual(candidates[0].value_decision, "PLAY")
            self.assertIsNotNone(candidates[0].void_odds)

    def test_build_candidate_pool_excludes_explicit_none_odds(self):
        """Regression: odds=None explicitly stored (e.g. provider returned no market for
        this fixture) must behave like "no odds", not like a populated JSON blob.

        SQLAlchemy's plain JSON type serializes Python None as the JSON literal ``null``
        (not SQL NULL) unless declared with none_as_null=True, so a naive
        ``odds.is_not(None)`` filter previously let these fixtures slip into the candidate
        pool with unusable odds data.
        """
        with self.Session() as session:
            self._seed_candidates(session, count=1)
            session.add(
                NextFixture(
                    event_key=999,
                    event_date=self.today,
                    event_first_player="No Odds",
                    event_second_player="Also None",
                    odds=None,
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=999,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.8,
                    predicted_winner="First Player",
                )
            )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertEqual([c.event_key for c in candidates], [100])

    def test_build_candidate_pool_excludes_cancelled_postponed_and_unknown(self):
        """Once status is known at update time, bad fixtures must not enter slips."""
        with self.Session() as session:
            self._seed_candidates(session, count=1)
            for event_key, status in (
                (901, "Cancelled"),
                (902, "Postponed"),
                (903, "Finished"),  # finished without winner → unknown
                (904, "Set 1"),  # live → started
            ):
                session.add(
                    NextFixture(
                        event_key=event_key,
                        event_date=self.today,
                        event_time=time(15, 0),
                        event_first_player=f"Bad A{event_key}",
                        event_second_player=f"Bad B{event_key}",
                        tournament_name="Bad Status Open",
                        surface="Hard",
                        odds=_sample_odds(),
                        event_status=status,
                        is_completed=False,
                    )
                )
                session.add(
                    MatchPrediction(
                        event_key=event_key,
                        model_version="v2",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                        prob_player_1_win=0.85,
                        predicted_winner="First Player",
                    )
                )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertEqual([c.event_key for c in candidates], [100])

    def test_v3_candidate_pool_excludes_missing_odds(self):
        with self.Session() as session:
            self._seed_candidates(session, count=1)
            session.add(
                NextFixture(
                    event_key=999,
                    event_date=self.today,
                    event_first_player="No Odds",
                    event_second_player="Also None",
                    is_completed=False,
                )
            )
            session.add_all(
                [
                    MatchPrediction(
                        event_key=100,
                        model_version="v3",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                        prob_player_1_win=0.74,
                        predicted_winner="First Player",
                    ),
                    MatchPrediction(
                        event_key=999,
                        model_version="v3",
                        model_name="random_forest",
                        predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                        prob_player_1_win=0.8,
                        predicted_winner="First Player",
                    ),
                ]
            )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v3",
                model_name="random_forest",
            )

            self.assertEqual([candidate.event_key for candidate in candidates], [100])
            self.assertIsNotNone(candidates[0].odds)

    def test_build_candidate_pool_includes_heavy_favorite_as_no_bet(self):
        heavy_favorite_odds = {
            "100": {
                "Home/Away": {
                    "Home": {"Book A": "1.04", "Book B": "1.05"},
                    "Away": {"Book A": "12.00", "Book B": "11.00"},
                }
            }
        }
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=100,
                    event_date=self.today,
                    event_time=time(14, 0),
                    event_first_player="Sinner J.",
                    event_second_player="Qualifier",
                    tournament_name="Wimbledon",
                    surface="Grass",
                    odds=heavy_favorite_odds,
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=100,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                    prob_player_1_win=0.92,
                    predicted_winner="First Player",
                )
            )
            session.commit()

            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].value_decision, "NO BET")
            self.assertIsNotNone(candidates[0].suggested_min_edge_percent)
            self.assertIsNotNone(candidates[0].min_edge_percent)

    def test_generate_slips_avoids_duplicate_event_market_pairs(self):
        with self.Session() as session:
            self._seed_candidates(session, count=8)
            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            slips, _warnings = generate_slips(candidates)
            for slip in slips:
                identities = [(pick.event_key, pick.market) for pick in slip.picks]
                self.assertEqual(len(identities), len(set(identities)))

    def test_daily_slip_can_mix_markets_for_the_same_event(self):
        target_date = date.today() + timedelta(days=1)
        event_key = 980
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=event_key,
                    event_date=target_date,
                    event_time=time(14, 0),
                    event_first_player="Player A",
                    event_second_player="Player B",
                    tournament_name="Mixed Markets Open",
                    surface="Hard",
                    odds=_sample_mixed_market_odds(),
                    is_completed=False,
                )
            )
            session.add(
                MatchPrediction(
                    event_key=event_key,
                    model_version="v2",
                    model_name="random_forest",
                    predicted_at=datetime.combine(target_date, time(8, 0)),
                    prob_player_1_win=0.72,
                    predicted_winner="First Player",
                )
            )
            session.commit()
            publish_prediction(
                session,
                PublishedPredictionCreate(
                    event_key=event_key,
                    selection="Over 20.5",
                    model_version="over_under_games_v1",
                    model_name="random_forest",
                    probability=0.62,
                    odds=1.92,
                    void_odds=1.70,
                    edge=0.08,
                    publication_source="system",
                    event_date=target_date,
                ),
            )

            daily = get_daily_betting_slips(
                session,
                slip_date=target_date,
                model_version="v2",
                model_name="random_forest",
                slip_count=1,
                picks_per_slip=2,
            )

            self.assertEqual(daily.match_winner_model_version, "v2")
            self.assertEqual(daily.match_winner_model_name, "random_forest")
            self.assertEqual(
                {
                    model.market: (model.model_version, model.model_name)
                    for model in daily.market_models
                },
                {
                    "match_winner": ("v2", "random_forest"),
                    "first_set_winner": (
                        "first_set_winner_v2",
                        "logistic_regression",
                    ),
                    "over_under_games": (
                        "over_under_games_v1",
                        "random_forest",
                    ),
                },
            )
            self.assertEqual(len(daily.slips), 1)
            picks = daily.slips[0].picks
            self.assertEqual(len(picks), 2)
            self.assertEqual({pick.event_key for pick in picks}, {event_key})
            self.assertEqual(
                {(pick.event_key, pick.market) for pick in picks},
                {(event_key, "match_winner"), (event_key, "over_under_games")},
            )
            persisted = list(
                session.scalars(select(BettingSlipPick)).all()
            )
            self.assertEqual(len(persisted), 2)

    def test_generate_slips_builds_three_difficulty_tiers(self):
        with self.Session() as session:
            self._seed_candidates(session, count=12)
            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            slips, _warnings = generate_slips(candidates, slip_count=10)
            self.assertGreaterEqual(len(slips), 1)
            keys = [slip.slip_key for slip in slips]
            self.assertIn("play_double_score", keys)
            double = next(slip for slip in slips if slip.slip_key == "play_double_score")
            self.assertEqual(len(double.picks), 2)
            self.assertTrue(any(key.startswith("play_") for key in keys))
            self.assertTrue(any(key.startswith("soft_") for key in keys) or any(key.startswith("mixed_") for key in keys))

    def test_generate_slips_builds_play_double_first(self):
        with self.Session() as session:
            self._seed_candidates(session, count=12)
            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            slips, _warnings = generate_slips(candidates)
            self.assertGreaterEqual(len(slips), 1)
            self.assertEqual(slips[0].slip_key, "play_double_score")
            self.assertEqual(len(slips[0].picks), 2)

    def test_generate_ladders_orders_steps_by_kickoff_and_compounds(self):
        with self.Session() as session:
            self._seed_candidates(session, count=10)
            candidates = build_candidate_pool(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            ladders, _warnings = generate_ladders(candidates)
            self.assertGreaterEqual(len(ladders), 1)
            first = ladders[0]
            self.assertTrue(first.slip_key.startswith("ladder_"))
            self.assertGreaterEqual(len(first.picks), 2)
            times = [pick.event_time for pick in first.picks]
            self.assertEqual(times, sorted(times, key=lambda value: (value is None, value)))
            event_keys = [pick.event_key for pick in first.picks]
            self.assertEqual(len(event_keys), len(set(event_keys)))

            daily = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                stake=10.0,
                regenerate=True,
            )
            ladder_reads = [slip for slip in daily.slips if slip.slip_kind == "ladder"]
            self.assertGreaterEqual(len(ladder_reads), 1)
            ladder = ladder_reads[0]
            self.assertEqual(ladder.picks[0].ladder_step_index, 1)
            self.assertEqual(ladder.picks[0].ladder_step_stake, 10.0)
            if ladder.picks[0].odds is not None:
                self.assertAlmostEqual(
                    ladder.picks[0].ladder_step_return_if_won or 0.0,
                    10.0 * ladder.picks[0].odds,
                    places=2,
                )
            if len(ladder.picks) > 1 and ladder.picks[0].odds is not None:
                self.assertAlmostEqual(
                    ladder.picks[1].ladder_step_stake or 0.0,
                    10.0 * ladder.picks[0].odds,
                    places=2,
                )

            stats = compute_betting_slip_model_stats(
                session,
                from_date=self.today,
                to_date=self.today,
                stake=10.0,
            )
            kinds = {row.slip_kind for row in stats.by_kind}
            self.assertIn("ladder", kinds)
            self.assertTrue(any(row.slip_key.startswith("ladder_") for row in stats.by_profile))

    def test_experimental_strategy_profiles_are_independent_and_conservative(self):
        candidates = [
            self._strategy_candidate(1, market="first_set_winner", odds=1.55, score=1.0),
            self._strategy_candidate(2, market="first_set_winner", odds=1.60, score=0.9),
            self._strategy_candidate(3, market="first_set_winner", odds=1.55, score=0.8),
            self._strategy_candidate(1, market="match_winner", odds=1.70, score=1.2),
            self._strategy_candidate(4, market="match_winner", odds=1.75, score=1.1),
            self._strategy_candidate(5, market="over_under_games", odds=1.80, score=1.05),
            self._strategy_candidate(
                6,
                market="first_set_winner",
                decision="BORDERLINE",
                odds=1.50,
                score=2.0,
            ),
        ]

        slips, warnings = generate_experimental_slips(candidates)
        self.assertFalse(warnings)
        by_key = {slip.slip_key: slip for slip in slips}
        self.assertEqual(
            set(by_key),
            {
                "experiment_play_only_3",
                "experiment_strong_markets_3",
                "experiment_selective_2",
            },
        )
        for slip in slips:
            self.assertTrue(all(pick.value_decision == "PLAY" for pick in slip.picks))
            self.assertEqual(
                len({pick.event_key for pick in slip.picks}),
                len(slip.picks),
            )
        strong = by_key["experiment_strong_markets_3"]
        selective = by_key["experiment_selective_2"]
        self.assertTrue(all(pick.market == "first_set_winner" for pick in strong.picks))
        self.assertTrue(all(pick.market == "first_set_winner" for pick in selective.picks))
        self.assertLessEqual(selective.combined_odds, 3.2)
        self.assertTrue(
            {pick.event_key for pick in strong.picks}
            & {pick.event_key for pick in selective.picks}
        )

        ladders, ladder_warnings = generate_experimental_ladders(candidates)
        self.assertFalse(ladder_warnings)
        self.assertEqual(len(ladders), 3)
        self.assertTrue(all(slip.slip_key.startswith("ladder_experiment_") for slip in ladders))
        selective_ladder = next(
            slip for slip in ladders if slip.slip_key == "ladder_experiment_selective_3"
        )
        self.assertLessEqual(selective_ladder.combined_odds, 4.0)

        with self.Session() as session:
            _persist_slips(
                session,
                slip_date=self.today,
                model_version="v4",
                model_name="voting_ensemble",
                generated_slips=[*slips, *ladders],
            )
            persisted = list(session.scalars(select(BettingSlip)).all())
            families = {row.strategy_family for row in persisted}
            self.assertEqual(families, {"play_only", "strong_markets", "selective"})
            self.assertTrue(all(row.is_experimental for row in persisted))
            self.assertEqual(
                {(row.strategy_family, row.strategy_version) for row in persisted},
                {
                    ("play_only", "play_only_v1"),
                    ("strong_markets", "strong_markets_v1"),
                    ("selective", "selective_v1"),
                },
            )

    def test_persisted_slips_are_stable_on_second_load(self):
        with self.Session() as session:
            self._seed_candidates(session, count=8)
            first = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            second = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            first_keys = [
                (slip.slip_key, [pick.event_key for pick in slip.picks])
                for slip in first.slips
            ]
            second_keys = [
                (slip.slip_key, [pick.event_key for pick in slip.picks])
                for slip in second.slips
            ]
            self.assertEqual(first_keys, second_keys)

    def test_persisted_slips_include_value_fields(self):
        with self.Session() as session:
            self._seed_candidates(session, count=6)
            daily = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertGreater(len(daily.slips), 0)
            first_pick = daily.slips[0].picks[0]
            self.assertIsNotNone(first_pick.void_odds)
            self.assertEqual(first_pick.value_decision, "PLAY")
            self.assertIsNotNone(first_pick.edge_percent)

    def test_regenerate_preserves_past_slips_when_pool_empty(self):
        past_date = self.today - timedelta(days=2)
        with self.Session() as session:
            self._seed_stats_slip(
                session,
                event_key=700,
                slip_date=past_date,
                model_version="v2",
                model_name="random_forest",
                actual_winner=None,
            )
            daily = get_daily_betting_slips(
                session,
                slip_date=past_date,
                model_version="v2",
                model_name="random_forest",
                regenerate=True,
            )
            self.assertEqual(len(daily.slips), 1)
            self.assertTrue(
                any("storiche mantenute" in warning.lower() for warning in daily.warnings)
            )

    def test_regenerate_preserves_existing_slips_with_picks(self):
        with self.Session() as session:
            self._seed_candidates(session, count=6)
            first = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            self.assertGreater(len(first.slips), 0)
            first_pick_ids = set(session.scalars(select(BettingSlipPick.id)).all())
            self.assertTrue(first_pick_ids)

            second = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                regenerate=True,
            )
            self.assertGreater(len(second.slips), 0)
            second_pick_ids = set(session.scalars(select(BettingSlipPick.id)).all())
            self.assertEqual(second_pick_ids, first_pick_ids)

    def test_pool_adds_before_cutoff_and_freezes_after_cutoff(self):
        settings = make_test_settings(
            betting_slip_timezone="Europe/Rome",
            betting_slip_pool_close_time="10:00",
        )
        with self.Session() as session:
            self._seed_candidates(session, count=2)
            get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                settings=settings,
                now=datetime.combine(self.today, time(9, 0)),
            )
            initial_ids = set(session.scalars(select(BettingSlipPick.id)).all())
            self.assertTrue(initial_ids)

            self._seed_candidates(session, count=4, start_key=200)
            get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                settings=settings,
                now=datetime.combine(self.today, time(9, 30)),
            )
            enriched_ids = set(session.scalars(select(BettingSlipPick.id)).all())
            self.assertTrue(initial_ids.issubset(enriched_ids))
            self.assertGreater(len(enriched_ids), len(initial_ids))

            self._seed_candidates(session, count=2, start_key=300)
            closed = get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                settings=settings,
                now=datetime.combine(self.today, time(11, 0)),
            )
            frozen_ids = set(session.scalars(select(BettingSlipPick.id)).all())
            self.assertEqual(frozen_ids, enriched_ids)
            self.assertTrue(any("pool giornaliero chiuso" in warning.lower() for warning in closed.warnings))
            registry = session.scalar(
                select(BettingSlipDay).where(
                    BettingSlipDay.slip_date == self.today,
                    BettingSlipDay.model_version == "v2",
                    BettingSlipDay.model_name == "random_forest",
                )
            )
            self.assertIsNotNone(registry.pool_locked_at)

    def test_cancelled_pick_is_persisted_as_void_before_cutoff(self):
        settings = make_test_settings(
            betting_slip_timezone="Europe/Rome",
            betting_slip_pool_close_time="10:00",
        )
        with self.Session() as session:
            self._seed_candidates(session, count=2)
            get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                settings=settings,
                now=datetime.combine(self.today, time(9, 0)),
            )
            initial = list(
                session.scalars(select(BettingSlipPick).order_by(BettingSlipPick.id)).all()
            )
            self.assertTrue(initial)
            cancelled_event_key = initial[0].event_key
            initial_ids = {pick.id for pick in initial}

            fixture = session.scalar(
                select(NextFixture).where(
                    NextFixture.event_key == cancelled_event_key
                )
            )
            fixture.event_status = "Cancelled"
            fixture.event_live = "0"
            session.commit()

            get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                settings=settings,
                now=datetime.combine(self.today, time(9, 15)),
            )
            persisted = list(
                session.scalars(select(BettingSlipPick).order_by(BettingSlipPick.id)).all()
            )
            self.assertEqual({pick.id for pick in persisted}, initial_ids)
            cancelled_picks = [
                pick for pick in persisted if pick.event_key == cancelled_event_key
            ]
            self.assertTrue(cancelled_picks)
            self.assertTrue(all(pick.outcome == "void" for pick in cancelled_picks))
            self.assertTrue(all(pick.settled_at is not None for pick in cancelled_picks))

    def test_pick_and_slip_status_resolution(self):
        pick = BettingSlipPick(
            betting_slip_id=1,
            event_key=1,
            predicted_winner="First Player",
            sort_order=0,
        )
        self.assertEqual(_resolve_pick_status(pick, "First Player"), ("won", True))
        self.assertEqual(_resolve_pick_status(pick, "Second Player"), ("lost", False))
        self.assertEqual(_resolve_pick_status(pick, None), ("pending", None))
        self.assertEqual(
            _resolve_pick_status(pick, None, match_lifecycle_status="cancelled"),
            ("void", None),
        )
        self.assertEqual(_resolve_slip_status(["won", "pending"]), "pending")
        self.assertEqual(_resolve_slip_status(["won", "lost"]), "lost")
        self.assertEqual(_resolve_slip_status(["won", "won"]), "won")
        self.assertEqual(_resolve_slip_status(["won", "void", "won"]), "won")
        self.assertEqual(_resolve_slip_status(["void", "void"]), "void")

    def test_calendar_includes_history_and_upcoming_window(self):
        future_date = date.today() + timedelta(days=3)
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=500,
                    event_date=future_date,
                    event_first_player="A",
                    event_second_player="B",
                    is_completed=False,
                )
            )
            session.add(
                NextFixture(
                    event_key=501,
                    event_date=self.today - timedelta(days=2),
                    event_first_player="C",
                    event_second_player="D",
                    odds=_sample_odds(),
                    is_completed=False,
                )
            )
            session.commit()
            self._seed_candidates(session, count=6)
            get_daily_betting_slips(
                session,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
            )
            calendar = get_betting_slip_calendar(
                session,
                model_version="v2",
                model_name="random_forest",
            )
            dates = [day.date for day in calendar.days]
            self.assertIn(self.today, dates)
            self.assertIn(future_date, dates)
            self.assertGreaterEqual(calendar.window_to, future_date)
            slip_day = session.scalar(
                select(BettingSlipDay).where(BettingSlipDay.slip_date == self.today)
            )
            self.assertIsNotNone(slip_day)
            self.assertGreater(slip_day.slip_count, 0)

    def test_model_stats_groups_versions_models_and_excludes_pending_from_rates(self):
        with self.Session() as session:
            self._seed_stats_slip(
                session,
                event_key=900,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner="First Player",
                combined_odds=2.0,
            )
            self._seed_stats_slip(
                session,
                event_key=901,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner="Second Player",
                combined_odds=2.0,
            )
            self._seed_stats_slip(
                session,
                event_key=902,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner=None,
                combined_odds=2.0,
            )
            self._seed_stats_slip(
                session,
                event_key=903,
                slip_date=self.today,
                model_version="v2",
                model_name="logistic_regression",
                actual_winner="First Player",
                combined_odds=1.5,
            )
            self._seed_stats_slip(
                session,
                event_key=904,
                slip_date=self.today,
                model_version="v3",
                model_name="random_forest",
                actual_winner="Second Player",
                combined_odds=1.8,
            )

            response = compute_betting_slip_model_stats(
                session,
                from_date=self.today,
                to_date=self.today,
                stake=10.0,
            )

            rows = {(row.model_version, row.model_name): row for row in response.rows}
            self.assertEqual(set(rows), {
                ("v2", "logistic_regression"),
                ("v2", "random_forest"),
                ("v3", "random_forest"),
            })
            random_forest = rows[("v2", "random_forest")]
            self.assertEqual(random_forest.slips_total, 3)
            self.assertEqual(random_forest.slips_won, 1)
            self.assertEqual(random_forest.slips_lost, 1)
            self.assertEqual(random_forest.slips_pending, 1)
            self.assertEqual(random_forest.slip_win_rate_pct, 50.0)
            self.assertEqual(random_forest.picks_total, 3)
            self.assertEqual(random_forest.picks_won, 1)
            self.assertEqual(random_forest.picks_lost, 1)
            self.assertEqual(random_forest.picks_pending, 1)
            self.assertEqual(random_forest.pick_hit_rate_pct, 50.0)
            self.assertEqual(random_forest.theoretical_profit_units, 0.0)
            self.assertEqual(random_forest.theoretical_roi_pct, 0.0)

    def test_strategy_stats_group_profiles_and_normalize_daily_bankroll(self):
        with self.Session() as session:
            self._seed_stats_slip(
                session,
                event_key=920,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner="First Player",
                combined_odds=2.0,
            )
            self._seed_stats_slip(
                session,
                event_key=921,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner="Second Player",
                combined_odds=2.0,
            )
            self._seed_stats_slip(
                session,
                event_key=922,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner="First Player",
                combined_odds=1.5,
                strategy_family="play_only",
                strategy_version="play_only_v1",
                is_experimental=True,
            )
            self._seed_stats_slip(
                session,
                event_key=923,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner=None,
            )

            response = compute_betting_slip_stats(
                session,
                model_version="v2",
                model_name="random_forest",
                from_date=self.today,
                to_date=self.today,
                stake=10.0,
            )

            rows = {
                (row.strategy_family, row.slip_kind): row
                for row in response.summary.by_strategy
            }
            generic = rows[("generic", "parlay")]
            play_only = rows[("play_only", "parlay")]
            self.assertEqual(generic.slips_total, 3)
            self.assertEqual(generic.theoretical_roi_pct, 0.0)
            self.assertIsNone(generic.daily_portfolio_roi_pct)
            self.assertEqual(generic.comparable_days, 0)
            self.assertEqual(play_only.strategy_versions, ["play_only_v1"])
            self.assertTrue(play_only.is_experimental)
            self.assertEqual(play_only.theoretical_roi_pct, 50.0)
            self.assertEqual(play_only.daily_portfolio_roi_pct, 50.0)

    def test_model_stats_respects_date_filter(self):
        with self.Session() as session:
            self._seed_stats_slip(
                session,
                event_key=910,
                slip_date=self.today - timedelta(days=2),
                model_version="v2",
                model_name="logistic_regression",
                actual_winner="First Player",
            )
            self._seed_stats_slip(
                session,
                event_key=911,
                slip_date=self.today,
                model_version="v2",
                model_name="random_forest",
                actual_winner="First Player",
            )

            response = compute_betting_slip_model_stats(
                session,
                from_date=self.today,
                to_date=self.today,
            )

            self.assertEqual(len(response.rows), 1)
            self.assertEqual(response.rows[0].model_name, "random_forest")
            self.assertEqual(response.rows[0].first_date, self.today)
            self.assertEqual(response.rows[0].last_date, self.today)


class BettingSlipsRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.today = date(2026, 6, 28)

        self.settings = make_test_settings()
        override_settings(self.settings)
        self.client = make_api_client(app, self.Session, settings=self.settings)
        with self.Session() as session:
            admin = create_admin(session)
            self.auth_headers = auth_header_for_admin(admin, self.settings)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _seed_slip_with_pick(self, session):
        session.add(
            NextFixture(
                event_key=200,
                event_date=self.today,
                event_first_player="Sinner J.",
                event_second_player="Alcaraz C.",
                tournament_name="Wimbledon",
                surface="Grass",
                odds=_sample_odds(),
                is_completed=False,
            )
        )
        session.add(
            MatchPrediction(
                event_key=200,
                model_version="v2",
                model_name="random_forest",
                predicted_at=datetime(2026, 6, 28, 8, 0, 0),
                prob_player_1_win=0.74,
                predicted_winner="First Player",
            )
        )
        slip = BettingSlip(
            slip_date=self.today,
            slip_key="safe",
            label="Sicura",
            description="Test",
            model_version="v2",
            model_name="random_forest",
            pick_count=1,
            combined_odds=1.52,
            generated_at=datetime(2026, 6, 28, 9, 0, 0),
        )
        session.add(slip)
        session.flush()
        session.add(
            BettingSlipPick(
                betting_slip_id=slip.id,
                event_key=200,
                event_date=self.today,
                event_time=time(14, 30),
                tournament_name="Wimbledon",
                surface="Grass",
                player_1_name="Sinner J.",
                player_2_name="Alcaraz C.",
                predicted_winner="First Player",
                predicted_winner_label="Sinner J.",
                model_prob=0.74,
                market_prob=0.65,
                edge=0.09,
                odds=1.52,
                confidence=0.74,
                pick_score=0.5,
                sort_order=0,
            )
        )
        session.commit()

    def test_daily_route_returns_persisted_slip_with_pending_pick(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        response = self.client.get(
            "/api/betting-slips/daily",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["slips"]), 1)
        pick = payload["slips"][0]["picks"][0]
        self.assertEqual(pick["pick_status"], "pending")
        self.assertIsNone(pick["is_correct"])

    def test_daily_route_resolves_pick_from_fixture(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)
            session.add(
                Fixture(
                    id_fixture=1,
                    event_key=200,
                    event_date=self.today,
                    event_first_player="Sinner J.",
                    event_second_player="Alcaraz C.",
                    event_winner="First Player",
                    event_status="Finished",
                    event_final_result="2 - 0",
                    event_live="0",
                    scores=[
                        {"score_first": "6", "score_second": "4", "score_set": "1"},
                        {"score_first": "6", "score_second": "3", "score_set": "2"},
                    ],
                )
            )
            session.commit()

        response = self.client.get(
            "/api/betting-slips/daily",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
            },
        )
        self.assertEqual(response.status_code, 200)
        slip = response.json()["slips"][0]
        self.assertEqual(slip["slip_status"], "won")
        self.assertEqual(slip["picks"][0]["pick_status"], "won")
        self.assertTrue(slip["picks"][0]["is_correct"])
        self.assertEqual(slip["picks"][0]["live_score"]["final_result"], "2 - 0")
        self.assertEqual(len(slip["picks"][0]["live_score"]["sets"]), 2)

    @patch("backend.src.app.services.imports.refresh_matches")
    @patch("backend.src.app.services.imports.import_played_fixtures")
    def test_refresh_route_does_not_duplicate_slips(self, mock_import, mock_refresh):
        mock_import.return_value = {"import_status": {}}
        mock_refresh.return_value = {"next_fixtures_imported": False}
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        first = self.client.get(
            "/api/betting-slips/daily",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
            },
        )
        refresh = self.client.post(
            "/api/betting-slips/refresh",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(refresh.status_code, 200)
        self.assertEqual(len(refresh.json()["slips"]), len(first.json()["slips"]))

    def test_calendar_route_returns_upcoming_window(self):
        today = date.today()
        tomorrow = today + timedelta(days=1)
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=600,
                    event_date=tomorrow,
                    event_first_player="A",
                    event_second_player="B",
                    is_completed=False,
                )
            )
            session.commit()

        response = self.client.get(
            "/api/betting-slips/calendar",
            params={"model_version": "v2", "model_name": "random_forest"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        dates = [day["date"] for day in payload["days"]]
        self.assertIn(today.isoformat(), dates)
        self.assertIn(tomorrow.isoformat(), dates)

    def test_stats_by_model_route_returns_grouped_rows(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)
            session.add(
                Fixture(
                    id_fixture=200,
                    event_key=200,
                    event_date=self.today,
                    event_first_player="Sinner J.",
                    event_second_player="Alcaraz C.",
                    event_winner="First Player",
                )
            )
            session.commit()

        response = self.client.get(
            "/api/betting-slips/stats/by-model",
            params={"from": self.today.isoformat(), "to": self.today.isoformat(), "stake": 10},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["from_date"], self.today.isoformat())
        self.assertEqual(payload["to_date"], self.today.isoformat())
        self.assertEqual(len(payload["rows"]), 1)
        row = payload["rows"][0]
        self.assertEqual(row["model_version"], "v2")
        self.assertEqual(row["model_name"], "random_forest")
        self.assertEqual(row["slips_total"], 1)
        self.assertEqual(row["slips_won"], 1)
        self.assertEqual(row["slip_win_rate_pct"], 100.0)

    def test_daily_image_route_returns_png(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        response = self.client.get(
            "/api/betting-slips/daily/image.png",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
                "slip_key": "safe",
                "stake": 10,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertIn("attachment;", response.headers.get("content-disposition", ""))
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_daily_images_zip_route_returns_zip(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        response = self.client.get(
            "/api/betting-slips/daily/images.zip",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
                "stake": 10,
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertIn(".zip", response.headers.get("content-disposition", ""))
        self.assertTrue(response.content[:2] == b"PK")

    def test_daily_image_route_404_for_unknown_slip_key(self):
        with self.Session() as session:
            self._seed_slip_with_pick(session)

        response = self.client.get(
            "/api/betting-slips/daily/image.png",
            params={
                "date": self.today.isoformat(),
                "model_version": "v2",
                "model_name": "random_forest",
                "slip_key": "missing",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
