import unittest
from datetime import date

from backend.src.app.telegram.dates import parse_date_or_offset
from backend.src.app.telegram.messages import (
    format_betting_slips,
    format_betting_slip_text,
    format_fixture_group_text,
    format_fixtures,
    format_predictions_day,
    predicted_winner_name,
    split_message,
)


class TelegramDateParsingTest(unittest.TestCase):
    def test_parse_offset_from_today(self):
        self.assertEqual(
            parse_date_or_offset("3", today=date(2026, 7, 4)),
            date(2026, 7, 7),
        )

    def test_parse_iso_date(self):
        self.assertEqual(
            parse_date_or_offset("2026-07-10", today=date(2026, 7, 4)),
            date(2026, 7, 10),
        )

    def test_rejects_offset_outside_window(self):
        with self.assertRaises(ValueError):
            parse_date_or_offset("11", today=date(2026, 7, 4))

    def test_rejects_invalid_date(self):
        with self.assertRaises(ValueError):
            parse_date_or_offset("domani", today=date(2026, 7, 4))


class TelegramFormattingTest(unittest.TestCase):
    def test_predicted_winner_uses_player_name_for_first_player(self):
        item = {
            "event_first_player": "Sinner J.",
            "event_second_player": "Alcaraz C.",
            "prediction": {"predicted_winner": "First Player"},
        }

        self.assertEqual(predicted_winner_name(item), "Sinner J.")

    def test_predicted_winner_uses_player_name_for_second_player(self):
        item = {
            "event_first_player": "Sinner J.",
            "event_second_player": "Alcaraz C.",
            "prediction": {"predicted_winner": "Second Player"},
        }

        self.assertEqual(predicted_winner_name(item), "Alcaraz C.")

    def test_split_message_keeps_chunks_within_limit(self):
        message = "\n".join(f"Riga {index}" for index in range(50))

        chunks = split_message(message, limit=80)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 80 for chunk in chunks))

    def test_format_predictions_empty_response(self):
        message = format_predictions_day([], date(2026, 7, 4))

        self.assertIn("Nessun pronostico trovato", message)
        self.assertIn("informativo/statistico", message)

    def test_format_fixtures_empty_response(self):
        message = format_fixtures([], date(2026, 7, 4))

        self.assertIn("Nessuna partita trovata", message)

    def test_format_fixture_group_text_numbers_matches(self):
        message = format_fixture_group_text(
            [
                {
                    "event_date": "2026-07-04",
                    "event_time": "14:30:00",
                    "event_first_player": "Sinner J.",
                    "event_second_player": "Alcaraz C.",
                    "tournament_name": "Wimbledon",
                    "prediction": {
                        "predicted_winner": "First Player",
                        "predicted_winner_odds": 1.52,
                        "confidence": 0.74,
                    },
                }
            ],
            start_index=21,
        )

        self.assertIn("21. 2026-07-04 14:30", message)
        self.assertIn("Sinner J. vs Alcaraz C.", message)
        self.assertIn("Vincitore: Sinner J. | Quota 1.52 | Vittoria 74%", message)

    def test_format_betting_slips_empty_response(self):
        message = format_betting_slips({"date": "2026-07-04", "slips": []})

        self.assertIn("Nessuna schedina disponibile", message)
        self.assertIn("informativo/statistico", message)

    def test_format_betting_slip_text_is_compact(self):
        message = format_betting_slip_text(
            {
                "label": "Sicura",
                "combined_odds": 1.52,
                "potential_return": 15.2,
                "potential_profit": 5.2,
                "picks": [
                    {
                        "player_1": "Sinner J.",
                        "player_2": "Alcaraz C.",
                        "predicted_winner": "First Player",
                        "predicted_winner_label": "Sinner J.",
                        "odds": 1.52,
                        "confidence": 0.74,
                    }
                ],
            }
        )

        self.assertIn("Schedina: Sicura", message)
        self.assertIn("Quota combinata: 1.52", message)
        self.assertIn("Vincitore: Sinner J.", message)


if __name__ == "__main__":
    unittest.main()
