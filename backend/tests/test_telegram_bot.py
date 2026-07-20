import unittest
from datetime import date

from backend.src.app.telegram.dates import parse_date_or_offset
from backend.src.app.telegram.fixture_value import enrich_fixture_value
from backend.src.app.telegram.messages import (
    format_betting_slips,
    format_betting_slip_photo_caption,
    format_betting_slip_text,
    format_betting_slips_intro,
    format_bot_stats_text,
    format_fixture_group_text,
    format_fixtures,
    format_fixtures_intro,
    format_predictions_day,
    predicted_winner_name,
    split_message,
)
from backend.src.app.telegram.public_labels import (
    build_public_labels,
    build_stats_series,
    public_model_label,
)
from backend.src.app.telegram.slips_compare import (
    betting_slips_equivalent,
    fixtures_equivalent,
    select_distinct_fixture_models,
    select_distinct_model_payloads,
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
                    "surface": "Grass",
                    "void_odds": 1.40,
                    "value_decision": "PLAY",
                    "prediction": {
                        "predicted_winner": "First Player",
                        "predicted_winner_odds": 1.52,
                        "confidence": 0.74,
                    },
                }
            ],
            start_index=21,
        )

        self.assertIn("21. 14:30 | Wimbledon | Grass", message)
        self.assertIn("Sinner J. vs Alcaraz C.", message)
        self.assertIn("Predetto: Sinner J.", message)
        self.assertIn("Void 1.40", message)
        self.assertIn("Valore PLAY", message)

    def test_format_fixtures_intro_is_date_and_status_legend_only(self):
        message = format_fixtures_intro(
            [{"event_key": 1}],
            "2026-07-19",
        )
        self.assertIn("Partite di oggi (2026-07-19)", message)
        self.assertIn("Verde = Presa", message)
        self.assertNotIn("logistic", message)

    def test_enrich_fixture_value_from_prediction_fallback(self):
        enriched = enrich_fixture_value(
            {
                "event_key": 10,
                "prediction": {
                    "predicted_winner": "First Player",
                    "prob_player_1_win": 0.7,
                    "predicted_winner_odds": 1.60,
                    "confidence": 0.7,
                    "is_correct": None,
                },
            },
            min_edge_percent=2.0,
        )
        self.assertAlmostEqual(enriched["void_odds"], 1 / 0.7, places=4)
        self.assertEqual(enriched["value_decision"], "PLAY")
        self.assertEqual(enriched["pick_status"], "pending")

    def test_select_distinct_fixture_models_keeps_both_when_winners_differ(self):
        left = [
            {
                "event_key": 1,
                "prediction": {"predicted_winner": "First Player"},
            }
        ]
        right = [
            {
                "event_key": 1,
                "prediction": {"predicted_winner": "Second Player"},
            }
        ]
        selected = select_distinct_fixture_models(
            [("logistic_regression", left), ("random_forest", right)]
        )
        self.assertEqual(len(selected), 2)
        self.assertFalse(fixtures_equivalent(left, right))

    def test_format_betting_slips_empty_response(self):
        message = format_betting_slips({"date": "2026-07-04", "slips": []})

        self.assertIn("Nessuna schedina disponibile", message)
        self.assertIn("informativo/statistico", message)

    def test_format_betting_slip_text_matches_dashboard_columns(self):
        message = format_betting_slip_text(
            {
                "label": "Play · Sicura",
                "description": "Solo PLAY, priorità confidenza",
                "slip_status": "pending",
                "picks_won": 0,
                "picks_total": 1,
                "combined_odds": 1.52,
                "potential_return": 15.2,
                "potential_profit": 5.2,
                "picks": [
                    {
                        "event_time": "14:30:00",
                        "tournament_name": "Wimbledon",
                        "player_1": "Sinner J.",
                        "player_2": "Alcaraz C.",
                        "predicted_winner": "First Player",
                        "predicted_winner_label": "Sinner J.",
                        "odds": 1.52,
                        "void_odds": 1.40,
                        "edge_percent": 8.5,
                        "expected_roi": 0.12,
                        "value_decision": "PLAY",
                        "confidence": 0.74,
                        "pick_status": "pending",
                    }
                ],
            }
        )

        self.assertIn("Schedina: Play · Sicura", message)
        self.assertIn("Stato: In corso", message)
        self.assertIn("Quota combinata: 1.52", message)
        self.assertIn("Pick: Sinner J.", message)
        self.assertIn("Void 1.40", message)
        self.assertIn("Edge +8.5%", message)
        self.assertIn("ROI +12.0%", message)
        self.assertIn("PLAY", message)

    def test_format_betting_slips_intro_is_date_and_status_legend_only(self):
        message = format_betting_slips_intro(
            {
                "date": "2026-07-19",
                "model_name": "logistic_regression",
                "model_version": "v3",
                "stake": 10,
                "slips": [{"label": "x"}],
            },
            min_edge_percent=2.0,
        )

        self.assertIn("Schedine di oggi (2026-07-19)", message)
        self.assertIn("Verde = Presa", message)
        self.assertIn("Rosso = Persa", message)
        self.assertIn("Grigio = In corso", message)
        self.assertNotIn("logistic_regression", message)
        self.assertNotIn("Modello:", message)
        self.assertNotIn("Stake:", message)

    def test_format_betting_slip_photo_caption_includes_series_label(self):
        caption = format_betting_slip_photo_caption(
            {
                "label": "Play · Value",
                "slip_status": "won",
                "picks_won": 4,
                "picks_total": 4,
                "combined_odds": 8.2,
                "potential_profit": 72.0,
            },
            series_label="Serie A · accuratezza 58.2%",
        )

        self.assertIn("Play · Value", caption)
        self.assertIn("Presa", caption)
        self.assertIn("4/4 pick", caption)
        self.assertIn("Serie A · accuratezza 58.2%", caption)
        self.assertNotIn("logistic", caption)
        self.assertNotIn("random_forest", caption)
        self.assertNotIn("Verde", caption)

    def test_public_model_label_hides_technical_names(self):
        labels = build_public_labels(
            ["logistic_regression", "random_forest"],
            accuracy_by_model={
                "logistic_regression": 58.2,
                "random_forest": 54.1,
            },
        )
        joined = " | ".join(labels.values())
        self.assertIn("Serie A · accuratezza 58.2%", joined)
        self.assertIn("Serie B · accuratezza 54.1%", joined)
        self.assertNotIn("logistic", joined)
        self.assertNotIn("random_forest", joined)
        self.assertEqual(public_model_label(accuracy_pct=None), "Predizione (accuratezza n.d.)")

    def test_format_bot_stats_text_is_generic(self):
        series = build_stats_series(
            model_names=["logistic_regression", "random_forest"],
            model_version="v3",
            prediction_summary={
                "breakdown": [
                    {
                        "model_version": "v3",
                        "model_name": "logistic_regression",
                        "accuracy_pct": 58.2,
                        "predictions_resolved": 100,
                        "predictions_correct": 58,
                        "predictions_lost": 42,
                        "pending": 5,
                        "theoretical_profit_units": 3.2,
                        "theoretical_roi_pct": 4.1,
                    },
                    {
                        "model_version": "v3",
                        "model_name": "random_forest",
                        "accuracy_pct": 54.1,
                        "predictions_resolved": 90,
                        "predictions_correct": 49,
                        "predictions_lost": 41,
                        "pending": 2,
                        "theoretical_profit_units": -1.5,
                        "theoretical_roi_pct": -2.0,
                    },
                ]
            },
            slip_stats={
                "rows": [
                    {
                        "model_version": "v3",
                        "model_name": "logistic_regression",
                        "slip_win_rate_pct": 22.0,
                        "slips_won": 2,
                        "slips_lost": 7,
                        "slips_pending": 1,
                        "pick_hit_rate_pct": 61.0,
                        "theoretical_profit_units": 12.5,
                        "theoretical_roi_pct": 15.0,
                    },
                    {
                        "model_version": "v3",
                        "model_name": "random_forest",
                        "slip_win_rate_pct": 10.0,
                        "slips_won": 1,
                        "slips_lost": 9,
                        "slips_pending": 0,
                        "pick_hit_rate_pct": 55.0,
                        "theoretical_profit_units": -8.0,
                        "theoretical_roi_pct": -10.0,
                    },
                ]
            },
        )
        text = format_bot_stats_text(series)
        self.assertIn("Serie A · accuratezza 58.2%", text)
        self.assertIn("Profitto schedine", text)
        self.assertNotIn("logistic_regression", text)
        self.assertNotIn("random_forest", text)

    def test_select_distinct_model_payloads_keeps_one_when_equal(self):
        shared_slips = [
            {
                "slip_key": "play_safe",
                "picks": [
                    {"event_key": 1, "predicted_winner": "First Player"},
                    {"event_key": 2, "predicted_winner": "Second Player"},
                ],
            }
        ]
        left = {"model_name": "logistic_regression", "slips": shared_slips}
        right = {"model_name": "random_forest", "slips": shared_slips}

        selected = select_distinct_model_payloads(
            [left, right],
            preferred_model_name="logistic_regression",
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["model_name"], "logistic_regression")
        self.assertTrue(betting_slips_equivalent(left, right))

    def test_select_distinct_model_payloads_keeps_both_when_different(self):
        left = {
            "model_name": "logistic_regression",
            "slips": [
                {
                    "slip_key": "play_safe",
                    "picks": [{"event_key": 1, "predicted_winner": "First Player"}],
                }
            ],
        }
        right = {
            "model_name": "random_forest",
            "slips": [
                {
                    "slip_key": "play_safe",
                    "picks": [{"event_key": 1, "predicted_winner": "Second Player"}],
                }
            ],
        }

        selected = select_distinct_model_payloads([left, right])

        self.assertEqual(len(selected), 2)
        self.assertFalse(betting_slips_equivalent(left, right))


if __name__ == "__main__":
    unittest.main()
