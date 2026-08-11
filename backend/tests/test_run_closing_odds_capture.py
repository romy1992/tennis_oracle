"""Tests for the dedicated closing-odds capture CLI job (run_closing_odds_capture)."""

from __future__ import annotations

import contextlib
import unittest
from unittest.mock import MagicMock, patch

from backend.src.jobs.run_closing_odds_capture import main
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings


def _summary(**overrides) -> dict:
    base = {
        "window_minutes": 60,
        "candidates": 0,
        "captured": 0,
        "inserted_rows": 0,
        "skipped_no_odds": 0,
        "failed": 0,
        "event_keys": [],
    }
    base.update(overrides)
    return base


class RunClosingOddsCaptureJobTest(unittest.TestCase):
    def setUp(self):
        self._fake_session = MagicMock()
        self._session_patch = patch(
            "backend.src.jobs.run_closing_odds_capture.SessionLocal",
            return_value=contextlib.nullcontext(self._fake_session),
        )
        self._session_patch.start()

    def tearDown(self):
        self._session_patch.stop()
        clear_settings_override()

    def test_skipped_when_disabled_by_default(self):
        override_settings(make_test_settings(closing_odds_job_enabled=False))
        with patch(
            "backend.src.jobs.run_closing_odds_capture.run_closing_odds_capture_once"
        ) as run_mock:
            code = main([])
        run_mock.assert_not_called()
        self.assertEqual(code, 0)

    def test_force_runs_even_when_disabled(self):
        override_settings(make_test_settings(closing_odds_job_enabled=False))
        with patch(
            "backend.src.jobs.run_closing_odds_capture.run_closing_odds_capture_once",
            return_value=_summary(),
        ) as run_mock:
            code = main(["--force"])
        run_mock.assert_called_once()
        self.assertEqual(code, 0)

    def test_dry_run_only_lists_candidates_without_capturing(self):
        override_settings(make_test_settings(closing_odds_job_enabled=True))
        with (
            patch(
                "backend.src.jobs.run_closing_odds_capture.find_fixtures_pending_closing_capture",
                return_value=[(123, "2026-08-11T10:00:00")],
            ) as find_mock,
            patch(
                "backend.src.jobs.run_closing_odds_capture.run_closing_odds_capture_once"
            ) as run_mock,
        ):
            code = main(["--dry-run", "--window-minutes", "30"])
        find_mock.assert_called_once()
        self.assertEqual(find_mock.call_args.kwargs.get("window_minutes"), 30)
        run_mock.assert_not_called()
        self.assertEqual(code, 0)

    def test_default_window_minutes_comes_from_settings(self):
        override_settings(
            make_test_settings(
                closing_odds_job_enabled=True,
                closing_odds_capture_window_minutes=45,
            )
        )
        with patch(
            "backend.src.jobs.run_closing_odds_capture.run_closing_odds_capture_once",
            return_value=_summary(window_minutes=45),
        ) as run_mock:
            code = main([])
        self.assertEqual(run_mock.call_args.kwargs.get("window_minutes"), 45)
        self.assertEqual(code, 0)

    def test_enabled_runs_capture_and_reflects_failures_in_exit_code(self):
        override_settings(make_test_settings(closing_odds_job_enabled=True))
        with patch(
            "backend.src.jobs.run_closing_odds_capture.run_closing_odds_capture_once",
            return_value=_summary(candidates=2, captured=1, inserted_rows=4, failed=1),
        ) as run_mock:
            code = main(["--json"])
        run_mock.assert_called_once()
        self.assertEqual(code, 1)

    def test_success_with_no_failures_returns_zero(self):
        override_settings(make_test_settings(closing_odds_job_enabled=True))
        with patch(
            "backend.src.jobs.run_closing_odds_capture.run_closing_odds_capture_once",
            return_value=_summary(candidates=1, captured=1, inserted_rows=4),
        ):
            code = main([])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

