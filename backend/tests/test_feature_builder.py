import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.src.app.ml.features.feature_builder import calculate_h2h, calculate_win_rate_last_n
from backend.src.app.models import MLMatch, MLPlayer
from backend.src.entity.base import Base


class FeatureBuilderTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)

    def test_win_rate_uses_only_previous_matches(self):
        with self.Session() as session:
            session.add_all([
                MLPlayer(id=1, name="Player One"),
                MLPlayer(id=2, name="Player Two"),
                MLPlayer(id=3, name="Player Three"),
                MLMatch(
                    id=1,
                    match_date=date(2024, 1, 1),
                    player_1_id=1,
                    player_2_id=2,
                    winner_id=1,
                    loser_id=2,
                ),
                MLMatch(
                    id=2,
                    match_date=date(2024, 1, 10),
                    player_1_id=1,
                    player_2_id=3,
                    winner_id=3,
                    loser_id=1,
                ),
            ])
            session.commit()

            win_rate = calculate_win_rate_last_n(
                session,
                player_id=1,
                before_date=date(2024, 1, 5),
                n=10,
            )

        self.assertEqual(win_rate, 1.0)

    def test_h2h_uses_only_previous_matches(self):
        with self.Session() as session:
            session.add_all([
                MLPlayer(id=1, name="Player One"),
                MLPlayer(id=2, name="Player Two"),
                MLMatch(
                    id=1,
                    match_date=date(2024, 1, 1),
                    player_1_id=1,
                    player_2_id=2,
                    winner_id=1,
                    loser_id=2,
                ),
                MLMatch(
                    id=2,
                    match_date=date(2024, 1, 10),
                    player_1_id=1,
                    player_2_id=2,
                    winner_id=2,
                    loser_id=1,
                ),
            ])
            session.commit()

            h2h = calculate_h2h(
                session,
                player_1_id=1,
                player_2_id=2,
                before_date=date(2024, 1, 5),
            )

        self.assertEqual(h2h, (1, 0))


if __name__ == "__main__":
    unittest.main()
