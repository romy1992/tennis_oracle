"""Tests for walk-forward / calibration background job controls."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.src.app.services.background_job import BackgroundJobCancelled, clear_cancel_state
from backend.src.app.services.calibration import (
    cancel_calibration_run,
    reconcile_orphaned_calibration_runs,
)
from backend.src.app.services.walk_forward import (
    cancel_walk_forward_run,
    reconcile_orphaned_walk_forward_runs,
)
from backend.src.entity.calibration import CalibrationRun
from backend.src.entity.walk_forward import WalkForwardRun


def _walk_forward_run(*, run_id: int = 1, status: str = "running") -> WalkForwardRun:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return WalkForwardRun(
        id=run_id,
        status=status,
        mode="expanding",
        initial_train_days=365,
        test_days=90,
        step_days=90,
        min_train_rows=200,
        min_test_rows=50,
        embargo_days=0,
        edge_threshold=0.03,
        random_state=42,
        versions_requested="v1,v2,v3",
        origin="manual",
        cancel_requested="false",
        created_at=now,
        created_by="test",
    )


def _calibration_run(*, run_id: int = 2, status: str = "running") -> CalibrationRun:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return CalibrationRun(
        id=run_id,
        status=status,
        n_bins=10,
        min_bin_samples=30,
        min_calibrator_train_samples=100,
        wf_mode="expanding",
        wf_initial_train_days=365,
        wf_test_days=90,
        wf_step_days=90,
        wf_min_train_rows=200,
        wf_min_test_rows=50,
        wf_embargo_days=0,
        wf_edge_threshold=0.03,
        wf_random_state=42,
        methods_requested="raw,platt,isotonic",
        versions_requested="v1,v2,v3",
        origin="manual",
        cancel_requested="false",
        created_at=now,
        created_by="test",
    )


class BackgroundJobControlsTest(unittest.TestCase):
    def tearDown(self) -> None:
        clear_cancel_state(1)
        clear_cancel_state(2)

    @patch("backend.src.app.services.walk_forward.get_walk_forward_run")
    def test_cancel_walk_forward_marks_orphan_as_cancelled(self, get_run_mock: MagicMock) -> None:
        run = _walk_forward_run()
        get_run_mock.return_value = run
        db = MagicMock()

        ok, message = cancel_walk_forward_run(db, 1)

        self.assertTrue(ok)
        self.assertIn("annull", message.lower())
        self.assertEqual(run.status, "cancelled")
        db.commit.assert_called()

    @patch("backend.src.app.services.calibration.get_calibration_run")
    def test_cancel_calibration_marks_orphan_as_cancelled(self, get_run_mock: MagicMock) -> None:
        run = _calibration_run()
        get_run_mock.return_value = run
        db = MagicMock()

        ok, message = cancel_calibration_run(db, 2)

        self.assertTrue(ok)
        self.assertIn("annull", message.lower())
        self.assertEqual(run.status, "cancelled")
        db.commit.assert_called()

    @patch("backend.src.app.services.walk_forward._active_run_id", None)
    def test_reconcile_orphaned_walk_forward_runs(self) -> None:
        run = _walk_forward_run(status="running")
        db = MagicMock()
        db.scalars.return_value.all.return_value = [run]

        count = reconcile_orphaned_walk_forward_runs(db)

        self.assertEqual(count, 1)
        self.assertEqual(run.status, "failed")
        self.assertIn("interrott", (run.error_message or "").lower())

    @patch("backend.src.app.services.calibration._active_run_id", None)
    def test_reconcile_orphaned_calibration_runs(self) -> None:
        run = _calibration_run(status="pending")
        db = MagicMock()
        db.scalars.return_value.all.return_value = [run]

        count = reconcile_orphaned_calibration_runs(db)

        self.assertEqual(count, 1)
        self.assertEqual(run.status, "failed")

    def test_background_job_cancelled_is_exception(self) -> None:
        with self.assertRaises(BackgroundJobCancelled):
            raise BackgroundJobCancelled("cancelled")


if __name__ == "__main__":
    unittest.main()
