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
    _steal_stale_lock_if_orphaned,
)
from backend.src.app.services.pipeline_lock import (
    acquire_pipeline_lock,
    get_pipeline_lock,
    new_owner_token,
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

    def test_reconcile_releases_stale_lock_tied_to_orphaned_run(self):
        """Regression test: a worker that dies mid-run (process kill, host
        crash, forced container recreate) leaves the distributed lock held
        for its run_id forever, since its `finally` release never runs. Once
        reconcile proves that run is dead, the lock must be freed too -
        otherwise every subsequent "Aggiorna" click fails instantly with
        "Could not acquire distributed pipeline lock" until the TTL (hours)
        expires on its own.
        """
        with self.Session() as session:
            run = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="running",
                force="false",
                created_at=datetime.now(),
                started_at=datetime.now(),
            )
            session.add(run)
            session.flush()
            run_id = run.id
            session.commit()

            dead_token = new_owner_token()
            self.assertTrue(
                acquire_pipeline_lock(
                    session, owner_token=dead_token, run_id=run_id, ttl_seconds=6 * 60 * 60
                )
            )

            count = reconcile_orphaned_runs(session)
            self.assertEqual(count, 1)

            refreshed = session.get(GlobalUpdateRun, run_id)
            assert refreshed is not None
            self.assertEqual(refreshed.status, "interrupted")

            lock = get_pipeline_lock(session)
            assert lock is not None
            self.assertIsNone(lock.owner_token)
            self.assertIsNone(lock.run_id)

            # A brand new run must now be able to acquire the lock immediately.
            new_token = new_owner_token()
            self.assertTrue(
                acquire_pipeline_lock(
                    session, owner_token=new_token, run_id=run_id + 1, ttl_seconds=60
                )
            )

    def test_reconcile_does_not_touch_lock_of_still_active_run(self):
        """A lock legitimately held by a run that is still genuinely running
        (e.g. owned by the active in-process thread) must survive reconcile
        of an *unrelated* orphaned run.
        """
        import backend.src.app.services.global_update as gu

        with self.Session() as session:
            orphaned = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="running",
                force="false",
                created_at=datetime.now(),
                started_at=datetime.now(),
            )
            active = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="running",
                force="false",
                created_at=datetime.now(),
                started_at=datetime.now(),
            )
            session.add_all([orphaned, active])
            session.flush()
            orphaned_id, active_id = orphaned.id, active.id
            session.commit()

            gu._active_run_id = active_id
            try:
                token = new_owner_token()
                self.assertTrue(
                    acquire_pipeline_lock(
                        session, owner_token=token, run_id=active_id, ttl_seconds=6 * 60 * 60
                    )
                )

                count = reconcile_orphaned_runs(session)
                self.assertEqual(count, 1)

                refreshed_orphaned = session.get(GlobalUpdateRun, orphaned_id)
                assert refreshed_orphaned is not None
                self.assertEqual(refreshed_orphaned.status, "interrupted")

                lock = get_pipeline_lock(session)
                assert lock is not None
                self.assertEqual(lock.owner_token, token)
                self.assertEqual(lock.run_id, active_id)
            finally:
                gu._active_run_id = None

    def test_steal_stale_lock_if_orphaned_recovers_dead_worker(self):
        with self.Session() as session:
            dead_run = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="interrupted",
                force="false",
                created_at=datetime.now(),
            )
            session.add(dead_run)
            session.flush()
            dead_run_id = dead_run.id
            session.commit()

            dead_token = new_owner_token()
            self.assertTrue(
                acquire_pipeline_lock(
                    session, owner_token=dead_token, run_id=dead_run_id, ttl_seconds=6 * 60 * 60
                )
            )

            new_run_id = dead_run_id + 1
            new_token = new_owner_token()
            stolen = _steal_stale_lock_if_orphaned(
                session, owner_token=new_token, run_id=new_run_id, ttl_seconds=60
            )
            self.assertTrue(stolen)

            lock = get_pipeline_lock(session)
            assert lock is not None
            self.assertEqual(lock.owner_token, new_token)
            self.assertEqual(lock.run_id, new_run_id)

    def test_steal_stale_lock_if_orphaned_refuses_genuinely_running_holder(self):
        with self.Session() as session:
            live_run = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="running",
                force="false",
                created_at=datetime.now(),
                started_at=datetime.now(),
            )
            session.add(live_run)
            session.flush()
            live_run_id = live_run.id
            session.commit()

            live_token = new_owner_token()
            self.assertTrue(
                acquire_pipeline_lock(
                    session, owner_token=live_token, run_id=live_run_id, ttl_seconds=6 * 60 * 60
                )
            )

            stolen = _steal_stale_lock_if_orphaned(
                session,
                owner_token=new_owner_token(),
                run_id=live_run_id + 1,
                ttl_seconds=60,
            )
            self.assertFalse(stolen)

            lock = get_pipeline_lock(session)
            assert lock is not None
            self.assertEqual(lock.owner_token, live_token)
            self.assertEqual(lock.run_id, live_run_id)

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
