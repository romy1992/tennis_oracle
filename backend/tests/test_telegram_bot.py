import unittest
from datetime import date, datetime, timezone

from backend.src.app.telegram.bot import MENU_HELP, MENU_PARTITE, MENU_SCALATE, main_menu_keyboard
from backend.src.app.telegram.dates import parse_date_or_offset
from backend.src.app.telegram.fixture_value import enrich_fixture_value, expand_fixtures_by_market
from backend.src.app.telegram.messages import (
    DISCLAIMER,
    account_status_label,
    append_message_footer,
    filter_slips_by_kind,
    format_betting_slips,
    format_betting_slip_photo_caption,
    format_betting_slip_text,
    format_betting_slips_intro,
    format_bot_stats_text,
    format_fixture_group_text,
    format_fixtures,
    format_fixtures_empty,
    format_fixtures_intro,
    format_help_text,
    format_datetime_rome,
    format_last_updated,
    format_predictions_day,
    format_subscription_overview,
    format_user_error,
    format_welcome_text,
    predicted_winner_name,
    slip_kind_of,
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

        self.assertIn("Nessuna partita disponibile", message)
        self.assertIn("Riprova più tardi", message)
        self.assertIn("informativo/statistico", message)

    def test_format_fixtures_empty_includes_last_updated_and_feedback(self):
        message = format_fixtures_empty(
            date(2026, 7, 4),
            last_updated="2026-07-04T10:15:00+00:00",
            feedback_url="https://example.com/feedback",
        )
        self.assertIn("Ultimo aggiornamento:", message)
        self.assertIn("Feedback / segnalazioni: https://example.com/feedback", message)
        self.assertNotIn("logistic", message)

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
                    "market": "match_winner",
                    "market_odds": 1.52,
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

        self.assertIn("21. 14:30 | Wimbledon | Erba", message)
        self.assertIn("Sinner J. vs Alcaraz C.", message)
        self.assertIn("Match: Sinner J.", message)
        self.assertIn("Percentuale di riuscita 74%", message)
        self.assertIn("Quota 1.52", message)
        self.assertNotIn("Void", message)
        self.assertNotIn("Valore", message)

    def test_format_fixtures_intro_is_public_and_coherent(self):
        message = format_fixtures_intro(
            [{"event_key": 1}],
            "2026-07-19",
            last_updated=datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc),
        )
        self.assertIn("Partite di oggi (2026-07-19)", message)
        self.assertIn("Verde = Presa", message)
        self.assertIn("Mercati: Match", message)
        self.assertIn("Ultimo aggiornamento:", message)
        self.assertIn(DISCLAIMER, message)
        self.assertNotIn("logistic", message)
        self.assertNotIn("v3", message)

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
        self.assertEqual(enriched["market"], "match_winner")

    def test_expand_fixtures_by_market_emits_match_first_set_and_ou(self):
        items = [
            {
                "event_key": 42,
                "event_first_player": "Sinner J.",
                "event_second_player": "Alcaraz C.",
                "tournament_name": "Wimbledon",
                "prediction": {
                    "predicted_winner": "First Player",
                    "prob_player_1_win": 0.62,
                    "predicted_winner_odds": 1.55,
                    "confidence": 0.62,
                },
                "extra_markets": [
                    {
                        "market": "over_under_games",
                        "selection": "Over 20.5",
                        "probability": 0.57,
                        "odds": 1.90,
                        "void_odds": 1.7544,
                    },
                    {
                        "market": "first_set_winner",
                        "selection": "First Player",
                        "probability": 0.61,
                        "odds": 1.70,
                        "void_odds": 1.6393,
                    },
                ],
            }
        ]
        rows = expand_fixtures_by_market(items, min_edge_percent=2.0)
        self.assertEqual([row["market"] for row in rows], [
            "match_winner",
            "first_set_winner",
            "over_under_games",
        ])
        self.assertEqual(rows[1]["predicted_winner_label"], "Sinner J.")
        self.assertEqual(rows[2]["predicted_winner_label"], "Over 20.5")
        self.assertAlmostEqual(rows[2]["market_odds"], 1.90)
        self.assertNotIn("extra_markets", rows[0])

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
                        "market": "first_set_winner",
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
        self.assertIn("1° set: Sinner J.", message)
        self.assertIn("Percentuale di riuscita 74%", message)
        self.assertIn("Quota 1.52", message)
        self.assertNotIn("Void", message)
        self.assertNotIn("Edge", message)
        self.assertNotIn("ROI", message)

    def test_format_betting_slips_intro_is_public_and_coherent(self):
        message = format_betting_slips_intro(
            {
                "date": "2026-07-19",
                "model_name": "logistic_regression",
                "model_version": "v3",
                "stake": 10,
                "slips": [{"label": "x"}],
            },
            min_edge_percent=2.0,
            feedback_url="https://example.com/feedback",
        )

        self.assertIn("Schedine di oggi (2026-07-19)", message)
        self.assertIn("Verde = Presa", message)
        self.assertIn("Rosso = Persa", message)
        self.assertIn("Grigio = In corso", message)
        self.assertIn("Mercati: Match", message)
        self.assertIn(DISCLAIMER, message)
        self.assertIn("Feedback / segnalazioni:", message)
        self.assertNotIn("logistic_regression", message)
        self.assertNotIn("random_forest", message)
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

    def test_format_subscription_overview_trial_and_renewal(self):
        text = format_subscription_overview(
            plan_name="Pro",
            subscription_status="trialing",
            trial_ends_at=datetime(2026, 8, 10, 18, 30, tzinfo=timezone.utc),
            expires_at=datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc),
            auto_renew=True,
            cancel_at_period_end=False,
            payment_failed=False,
            feedback_url="https://example.com/feedback",
        )

        self.assertIn("Piano attuale: Pro", text)
        self.assertIn("Stato abbonamento: In prova", text)
        self.assertIn("Periodo di prova fino al:", text)
        self.assertIn("Prossimo rinnovo stimato:", text)
        self.assertIn("Feedback / segnalazioni: https://example.com/feedback", text)
        self.assertNotIn(DISCLAIMER, text)

    def test_format_subscription_overview_handles_payment_failed_and_cancel(self):
        text = format_subscription_overview(
            plan_name="Pro",
            subscription_status="suspended",
            trial_ends_at=None,
            expires_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
            auto_renew=False,
            cancel_at_period_end=True,
            payment_failed=True,
        )
        self.assertIn("Stato abbonamento: Sospeso", text)
        self.assertIn("Cancellazione programmata al:", text)
        self.assertIn("Pagamento non riuscito rilevato", text)

    def test_format_subscription_overview_hides_subscription_commands_when_disabled(self):
        text = format_subscription_overview(
            plan_name="Pro",
            subscription_status="expired",
            trial_ends_at=None,
            expires_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
            auto_renew=False,
            cancel_at_period_end=False,
            payment_failed=True,
            include_subscription_commands=False,
        )
        self.assertNotIn("/gestisci_abbonamento", text)
        self.assertNotIn("/abbonati", text)
        self.assertIn("Contatta il supporto", text)

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


class TelegramBotUxTest(unittest.TestCase):
    def test_main_menu_keyboard_has_primary_actions(self):
        markup = main_menu_keyboard(
            flags={
                "telegram.fixtures_enabled": True,
                "telegram.slips_enabled": True,
                "telegram.statistics_enabled": True,
            }
        )
        labels = [button.text for row in markup.inline_keyboard for button in row]
        data = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertEqual(labels, ["Partite", "Schedine", "Scalate", "Statistiche", "Aiuto"])
        self.assertIn(MENU_PARTITE, data)
        self.assertIn(MENU_SCALATE, data)
        self.assertIn(MENU_HELP, data)

    def test_help_and_welcome_are_synthetic_and_public(self):
        help_text = format_help_text(feedback_url="https://example.com/feedback")
        welcome = format_welcome_text()
        self.assertIn("/partite", help_text)
        self.assertIn("/schedine", help_text)
        self.assertIn("/scalate", help_text)
        self.assertIn("/statistiche", help_text)
        self.assertIn("/piano", help_text)
        self.assertIn("/abbonati", help_text)
        self.assertIn("/gestisci_abbonamento", help_text)
        self.assertIn("/feedback", help_text)
        self.assertIn("/annulla", help_text)
        self.assertIn("pulsanti", help_text.lower())
        self.assertIn(DISCLAIMER, help_text)
        self.assertIn("Feedback / segnalazioni:", help_text)
        self.assertIn("/partite", welcome)
        self.assertIn("/scalate", welcome)
        self.assertIn("/piano", welcome)
        self.assertIn("/feedback", welcome)
        self.assertNotIn("logistic_regression", help_text)
        self.assertNotIn("random_forest", welcome)
        self.assertNotIn("v3", welcome)

    def test_filter_slips_by_kind_separates_ladders(self):
        payload = {
            "date": "2026-06-28",
            "slips": [
                {"slip_key": "play_safe", "label": "Play · Sicura", "picks": []},
                {
                    "slip_key": "ladder_play_3",
                    "slip_kind": "ladder",
                    "label": "Scalata · Play 3",
                    "picks": [],
                },
            ],
        }
        parlays = filter_slips_by_kind(payload, slip_kind="parlay")
        ladders = filter_slips_by_kind(payload, slip_kind="ladder")
        self.assertEqual([s["slip_key"] for s in parlays["slips"]], ["play_safe"])
        self.assertEqual([s["slip_key"] for s in ladders["slips"]], ["ladder_play_3"])
        self.assertEqual(slip_kind_of(ladders["slips"][0]), "ladder")
        intro = format_betting_slips_intro(slip_date="2026-06-28", slip_kind="ladder")
        self.assertIn("Scalate di oggi", intro)
        self.assertIn("reinvestito", intro)
        caption = format_betting_slip_photo_caption(ladders["slips"][0])
        self.assertIn("step", caption)

    def test_help_and_welcome_hide_subscription_commands_when_disabled(self):
        help_text = format_help_text(include_subscription_commands=False)
        welcome = format_welcome_text(include_subscription_commands=False)
        self.assertNotIn("/piano", help_text)
        self.assertNotIn("/abbonati", help_text)
        self.assertNotIn("/gestisci_abbonamento", help_text)
        self.assertNotIn("/piano", welcome)
        self.assertNotIn("/abbonati", welcome)
        self.assertNotIn("/gestisci_abbonamento", welcome)

    def test_format_last_updated_rome(self):
        line = format_last_updated("2026-07-04T10:15:00+00:00")
        self.assertIsNotNone(line)
        assert line is not None
        self.assertTrue(line.startswith("Ultimo aggiornamento:"))
        self.assertIn("ora italiana", line)

    def test_format_datetime_rome_without_prefix(self):
        line = format_datetime_rome(datetime(2026, 7, 4, 10, 15, tzinfo=timezone.utc))
        self.assertIsNotNone(line)
        assert line is not None
        self.assertRegex(line, r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}")

    def test_format_user_error_is_uniform(self):
        message = format_user_error("Backend non disponibile.")
        self.assertIn("Backend non disponibile.", message)
        self.assertIn(DISCLAIMER, message)
        scrubbed = format_user_error("Traceback (most recent call last):\nSQLAlchemy boom")
        self.assertIn("problema temporaneo", scrubbed)
        self.assertNotIn("SQLAlchemy", scrubbed)

    def test_account_status_label_is_italian(self):
        self.assertEqual(account_status_label("active"), "Attivo")
        self.assertEqual(account_status_label("invited"), "In lista di attesa")

    def test_append_message_footer_order(self):
        text = append_message_footer(
            "Corpo",
            last_updated="2026-07-04T10:15:00+00:00",
            feedback_url="https://example.com/feedback",
        )
        disclaimer_at = text.index(DISCLAIMER)
        feedback_at = text.index("Feedback / segnalazioni:")
        update_at = text.index("Ultimo aggiornamento:")
        self.assertLess(update_at, disclaimer_at)
        self.assertLess(disclaimer_at, feedback_at)


if __name__ == "__main__":
    unittest.main()
