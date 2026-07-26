"""Tests for the production global-update CLI job and resume/exit codes."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from unittest.mock import patch

from backend.src.app.services.global_update import (
    exit_code_for_run,
    get_resumable_run,
    reconcile_orphaned_runs,
    start_global_update,
)
from backend.src.entity.global_update_run import GlobalUpdateRun, GlobalUpdateRunItem
from backend.src.jobs.run_global_update import run_job
from backend.tests.auth_helpers import clear_settings_override, make_test_settings, override_settings
from backend.tests.db_helpers import create_session_factory, create_test_engine
import backend.src.app.db.session as session_mod


class ExitCodeTest(unittest.TestCase):
    def test_exit_codes(self):
        run = GlobalUpdateRun(
            run_date=date.today(),
            origin="job",
            status="completed",
            force="false",
            created_at=datetime.now(),
        )
        self.assertEqual(exit_code_for_run(run), 0)
        run.status = "completed_with_errors"
        self.assertEqual(exit_code_for_run(run), 1)
        run.status = "failed"
        self.assertEqual(exit_code_for_run(run), 2)
        run.status = "interrupted"
        self.assertEqual(exit_code_for_run(run), 2)
        run.status = "cancelled"
        self.assertEqual(exit_code_for_run(run), 3)
        self.assertEqual(exit_code_for_run(None, message="already running"), 4)
        self.assertEqual(exit_code_for_run(None, message="already completed today"), 0)
        self.assertEqual(exit_code_for_run(None, message="No enabled"), 5)


class ResumeAndReconcileTest(unittest.TestCase):
    def setUp(self):
        import backend.src.app.services.global_update as gu

        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self._prev_session_local = session_mod.SessionLocal
        session_mod.SessionLocal = self.Session
        self.settings = make_test_settings()
        override_settings(self.settings)
        gu._active_run_id = None
        gu._cancel_requested.clear()
        gu._cancel_cache.clear()

    def tearDown(self):
        import backend.src.app.services.global_update as gu

        gu._active_run_id = None
        gu._cancel_requested.clear()
        gu._cancel_cache.clear()
        session_mod.SessionLocal = self._prev_session_local
        clear_settings_override()
        self.engine.dispose()

    def test_reconcile_marks_interrupted(self):
        with self.Session() as session:
            run = GlobalUpdateRun(
                run_date=date.today(),
                origin="job",
                status="running",
                force="false",
                created_at=datetime.now(),
                started_at=datetime.now(),
            )
            session.add(run)
            session.flush()
            session.add(
                GlobalUpdateRunItem(
                    run_id=run.id,
                    model_version="v3",
                    model_name="logistic_regression",
                    status="running",
                    started_at=datetime.now(),
                )
            )
            session.commit()
            run_id = run.id

            count = reconcile_orphaned_runs(session)
            self.assertEqual(count, 1)
            refreshed = session.get(GlobalUpdateRun, run_id)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "interrupted")
            resumable = get_resumable_run(session)
            assert resumable is not None
            self.assertEqual(resumable.id, run_id)

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    @patch("backend.src.app.services.global_update._execute_global_update")
    def test_resume_resets_failed_items(self, mock_execute, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v3", "model_name": "logistic_regression"})(),
        ]
        with self.Session() as session:
            run = GlobalUpdateRun(
                run_date=date.today(),
                origin="job",
                status="interrupted",
                force="true",
                created_at=datetime.now(),
                phases_json='[{"phase":"import_fixtures","status":"completed"}]',
            )
            session.add(run)
            session.flush()
            session.add(
                GlobalUpdateRunItem(
                    run_id=run.id,
                    model_version="v3",
                    model_name="logistic_regression",
                    status="failed",
                    error_message="boom",
                )
            )
            session.commit()

            resumed, message = start_global_update(
                session,
                origin="job",
                resume=True,
                resume_run_id=run.id,
                blocking=False,
            )
            self.assertIsNotNone(resumed)
            assert resumed is not None
            self.assertIn("resume", message.lower())
            self.assertEqual(resumed.resume_count, 1)
            self.assertEqual(resumed.items[0].status, "pending")
            mock_execute.assert_called_once()

    @patch("backend.src.jobs.run_global_update.start_global_update")
    @patch("backend.src.jobs.run_global_update.reconcile_orphaned_runs", return_value=0)
    def test_run_job_returns_exit_code(self, _reconcile, mock_start):
        run = GlobalUpdateRun(
            id=42,
            run_date=date.today(),
            origin="job",
            status="completed",
            force="false",
            created_at=datetime.now(),
            duration_seconds=1.0,
        )
        mock_start.return_value = (run, "ok")
        code = run_job(force=True, sync_cloud=False, auto_resume=False)
        self.assertEqual(code, 0)
        mock_start.assert_called_once()
        kwargs = mock_start.call_args.kwargs
        self.assertTrue(kwargs["blocking"])
        self.assertEqual(kwargs["origin"], "job")


if __name__ == "__main__":
    unittest.main()
