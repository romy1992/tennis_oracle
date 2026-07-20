import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from backend.src.service import import_next_fixtures as module


class ImportNextFixturesTest(unittest.TestCase):
    def test_is_singles_match_filters_doubles(self):
        self.assertTrue(
            module.is_singles_match({"event_type_type": "Atp Singles"})
        )
        self.assertFalse(
            module.is_singles_match({"event_type_type": "Atp Doubles"})
        )
        self.assertFalse(module.is_singles_match("unexpected"))

    def test_is_match_completed_detects_winner(self):
        self.assertTrue(
            module.is_match_completed({"event_winner": "First Player"})
        )
        self.assertFalse(module.is_match_completed({"event_winner": None}))
        self.assertFalse(
            module.is_match_completed(
                {"event_winner": None, "event_final_result": "2 - 0", "event_status": "Cancelled"}
            )
        )

    def test_iso_week_bounds(self):
        week_start, week_end = module.iso_week_bounds(date(2026, 6, 21))
        self.assertEqual(week_start, date(2026, 6, 15))
        self.assertEqual(week_end, date(2026, 6, 21))

    def test_iter_date_chunks_respects_api_max_range(self):
        start = date(2026, 7, 18)
        end = start + timedelta(days=10)
        chunks = list(module.iter_date_chunks(start, end, max_span_days=7))
        self.assertEqual(
            chunks,
            [
                (date(2026, 7, 18), date(2026, 7, 25)),
                (date(2026, 7, 26), date(2026, 7, 28)),
            ],
        )

    def test_normalize_raises_on_api_error_string(self):
        with self.assertRaises(RuntimeError) as ctx:
            module._normalize_fixtures_response(
                "Maximum date range for odds is 7 days.",
                "upcoming_window",
            )
        self.assertIn("Maximum date range", str(ctx.exception))

    @patch.object(module, "next_fixtures_repo")
    @patch.object(module, "fixtures_repo")
    @patch.object(module, "predictions_repo")
    def test_promote_completed_match_upserts_fixture_and_resolves_predictions(
        self,
        mock_predictions_repo,
        mock_fixtures_repo,
        mock_next_repo,
    ):
        payload = {
            "event_key": 123,
            "event_date": "2026-06-20",
            "event_winner": "First Player",
            "event_final_result": "2 - 0",
            "event_type_type": "Atp Singles",
            "event_first_player": "A",
            "first_player_key": 1,
            "event_second_player": "B",
            "second_player_key": 2,
        }
        mock_fixtures_repo.search_filter.return_value = []
        mock_predictions_repo.search_filter.return_value = [
            type(
                "Prediction",
                (),
                {
                    "event_key": 123,
                    "predicted_winner": "First Player",
                    "actual_winner": None,
                    "is_correct": None,
                },
            )()
        ]
        mock_next_repo.search_filter.return_value = [
            type(
                "NextFixture",
                (),
                {
                    "event_key": 123,
                    "is_completed": False,
                    "moved_to_fixture_at": None,
                    "event_status": "Finished",
                },
            )()
        ]

        summary = module.promote_completed_match(payload)

        self.assertEqual(summary["fixtures_inserted"], 1)
        self.assertEqual(summary["predictions_resolved"], 1)
        mock_fixtures_repo.save.assert_called()
        mock_predictions_repo.save.assert_called()
        mock_next_repo.save.assert_called()

    @patch.object(module, "request_api")
    @patch.object(module, "next_fixtures_repo")
    @patch.object(module, "fetch_odds_for_match", return_value=None)
    def test_import_next_fixtures_upserts_upcoming_singles(
        self,
        _mock_odds,
        mock_next_repo,
        mock_request_api,
    ):
        mock_request_api.side_effect = [
            [
                {
                    "event_key": 999,
                    "event_date": module.today_local().strftime("%Y-%m-%d"),
                    "event_type_type": "Atp Singles",
                    "event_first_player": "A",
                    "first_player_key": 10,
                    "event_second_player": "B",
                    "second_player_key": 20,
                }
            ],
            [],
        ]
        mock_next_repo.search_filter.return_value = []
        mock_next_repo.delete_outside_date_range.return_value = 0
        mock_next_repo.delete_completed.return_value = 0

        summary = module.import_next_fixtures(days_forward=7, days_back=0, import_odds=False)

        self.assertEqual(summary["inserted"], 1)
        mock_next_repo.save.assert_called()

    @patch.object(module, "request_api")
    @patch.object(module, "next_fixtures_repo")
    @patch.object(module, "fetch_odds_for_match", return_value=None)
    def test_import_next_fixtures_handles_dict_response_and_invalid_items(
        self,
        _mock_odds,
        mock_next_repo,
        mock_request_api,
    ):
        mock_request_api.side_effect = [
            {
                "result": [
                    "bad-item",
                    {
                        "event_key": 1001,
                        "event_date": module.today_local().strftime("%Y-%m-%d"),
                        "event_type_type": "Atp Singles",
                        "event_first_player": "A",
                        "first_player_key": 11,
                        "event_second_player": "B",
                        "second_player_key": 22,
                    },
                ]
            },
            {"result": []},
        ]
        mock_next_repo.search_filter.return_value = []
        mock_next_repo.delete_outside_date_range.return_value = 0
        mock_next_repo.delete_completed.return_value = 0

        summary = module.import_next_fixtures(days_forward=7, days_back=0, import_odds=False)

        self.assertEqual(summary["inserted"], 1)
        mock_next_repo.save.assert_called()

    @patch.object(module, "request_api")
    @patch.object(module, "next_fixtures_repo")
    @patch.object(module, "fetch_odds_for_match", return_value=None)
    def test_import_next_fixtures_chunks_wide_window(
        self,
        _mock_odds,
        mock_next_repo,
        mock_request_api,
    ):
        today = module.today_local()
        mock_request_api.side_effect = [
            [
                {
                    "event_key": 2001,
                    "event_date": today.strftime("%Y-%m-%d"),
                    "event_type_type": "Atp Singles",
                    "event_first_player": "A",
                    "first_player_key": 1,
                    "event_second_player": "B",
                    "second_player_key": 2,
                }
            ],
            [
                {
                    "event_key": 2002,
                    "event_date": (today + timedelta(days=9)).strftime("%Y-%m-%d"),
                    "event_type_type": "Atp Singles",
                    "event_first_player": "C",
                    "first_player_key": 3,
                    "event_second_player": "D",
                    "second_player_key": 4,
                }
            ],
            [],  # recent refresh chunk
        ]
        mock_next_repo.search_filter.return_value = []
        mock_next_repo.delete_outside_date_range.return_value = 0
        mock_next_repo.delete_completed.return_value = 0

        summary = module.import_next_fixtures(days_forward=10, days_back=0, import_odds=False)

        self.assertEqual(summary["inserted"], 2)
        self.assertEqual(summary["api_chunks"], 2)
        # 2 upcoming chunks + 1 recent chunk
        self.assertEqual(mock_request_api.call_count, 3)
        mock_next_repo.delete_outside_date_range.assert_called_once()

    @patch.object(module, "request_api")
    @patch.object(module, "next_fixtures_repo")
    def test_import_next_fixtures_skips_cleanup_when_api_fails(
        self,
        mock_next_repo,
        mock_request_api,
    ):
        mock_request_api.side_effect = RuntimeError(
            "API Tennis error: Maximum date range for odds is 7 days."
        )

        with self.assertRaises(RuntimeError):
            module.import_next_fixtures(days_forward=10, days_back=0, import_odds=False)

        mock_next_repo.delete_outside_date_range.assert_not_called()
        mock_next_repo.delete_completed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
