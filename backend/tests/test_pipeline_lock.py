"""Tests for distributed pipeline_lock."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from backend.src.app.services.pipeline_lock import (
    GLOBAL_UPDATE_LOCK_NAME,
    acquire_pipeline_lock,
    force_release_pipeline_lock,
    heartbeat_pipeline_lock,
    new_owner_token,
    release_pipeline_lock,
)
from backend.src.entity.pipeline_lock import PipelineLock
from backend.tests.db_helpers import create_session_factory, create_test_engine


class PipelineLockTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_acquire_and_release(self):
        token = new_owner_token()
        with self.Session() as session:
            ok = acquire_pipeline_lock(session, owner_token=token, run_id=1, ttl_seconds=60)
            self.assertTrue(ok)
            lock = session.get(PipelineLock, GLOBAL_UPDATE_LOCK_NAME)
            assert lock is not None
            self.assertEqual(lock.owner_token, token)
            self.assertEqual(lock.run_id, 1)

            other = new_owner_token()
            blocked = acquire_pipeline_lock(session, owner_token=other, run_id=2, ttl_seconds=60)
            self.assertFalse(blocked)

            released = release_pipeline_lock(session, owner_token=token)
            self.assertTrue(released)
            second = acquire_pipeline_lock(session, owner_token=other, run_id=2, ttl_seconds=60)
            self.assertTrue(second)

    def test_expired_lock_can_be_stolen(self):
        token = new_owner_token()
        with self.Session() as session:
            self.assertTrue(
                acquire_pipeline_lock(session, owner_token=token, run_id=9, ttl_seconds=60)
            )
            lock = session.get(PipelineLock, GLOBAL_UPDATE_LOCK_NAME)
            assert lock is not None
            lock.expires_at = datetime.now() - timedelta(seconds=1)
            session.commit()

            thief = new_owner_token()
            self.assertTrue(
                acquire_pipeline_lock(session, owner_token=thief, run_id=10, ttl_seconds=60)
            )
            lock = session.get(PipelineLock, GLOBAL_UPDATE_LOCK_NAME)
            assert lock is not None
            self.assertEqual(lock.owner_token, thief)

    def test_heartbeat_extends_ttl(self):
        token = new_owner_token()
        with self.Session() as session:
            self.assertTrue(
                acquire_pipeline_lock(session, owner_token=token, run_id=1, ttl_seconds=60)
            )
            lock = session.get(PipelineLock, GLOBAL_UPDATE_LOCK_NAME)
            assert lock is not None
            before = lock.expires_at
            self.assertTrue(
                heartbeat_pipeline_lock(session, owner_token=token, ttl_seconds=120)
            )
            lock = session.get(PipelineLock, GLOBAL_UPDATE_LOCK_NAME)
            assert lock is not None and before is not None and lock.expires_at is not None
            self.assertGreaterEqual(lock.expires_at, before)

    def test_force_release_clears_lock_regardless_of_owner(self):
        token = new_owner_token()
        with self.Session() as session:
            self.assertTrue(
                acquire_pipeline_lock(session, owner_token=token, run_id=5, ttl_seconds=6 * 60 * 60)
            )
            # A different owner cannot release it normally...
            self.assertFalse(
                release_pipeline_lock(session, owner_token=new_owner_token())
            )
            # ...but force-release clears it unconditionally (recovery path).
            self.assertTrue(force_release_pipeline_lock(session))
            lock = session.get(PipelineLock, GLOBAL_UPDATE_LOCK_NAME)
            assert lock is not None
            self.assertIsNone(lock.owner_token)
            self.assertIsNone(lock.run_id)
            self.assertIsNone(lock.expires_at)

            other = new_owner_token()
            self.assertTrue(
                acquire_pipeline_lock(session, owner_token=other, run_id=6, ttl_seconds=60)
            )

    def test_force_release_no_op_when_already_free(self):
        with self.Session() as session:
            self.assertFalse(force_release_pipeline_lock(session))


if __name__ == "__main__":
    unittest.main()
