import unittest
from datetime import date, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.db.session import get_db
from backend.src.app.main import app
from backend.src.app.services.global_update import (
    list_enabled_combinations,
    start_global_update,
)
from backend.src.entity.base import Base
from backend.src.entity.global_update_run import GlobalUpdateRun


class GlobalUpdateServiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

        def override_get_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    @patch("backend.src.app.services.global_update._execute_global_update")
    def test_start_global_update_creates_run(self, mock_execute, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
            type("C", (), {"model_version": "v2", "model_name": "random_forest"})(),
        ]

        with self.Session() as session:
            run, message = start_global_update(session, origin="manual", force=True)
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(run.status, "pending")
            self.assertEqual(run.origin, "manual")
            self.assertEqual(len(run.items), 2)
            self.assertIn("started", message.lower())

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    @patch("backend.src.app.services.global_update._execute_global_update")
    def test_concurrent_run_blocked(self, mock_execute, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
        ]

        with self.Session() as session:
            first, _ = start_global_update(session, origin="manual", force=True)
            assert first is not None
            first.status = "running"
            session.commit()

            second, message = start_global_update(session, origin="manual", force=True)
            self.assertIsNone(second)
            self.assertIn("already running", message.lower())

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    def test_post_global_update_endpoint(self, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
        ]
        with patch("backend.src.app.services.global_update._execute_global_update"):
            response = self.client.post("/api/global-update", json={"force": True})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("run_id", payload)
        self.assertEqual(payload["status"], "pending")

    def test_get_status_endpoint_empty(self):
        response = self.client.get("/api/global-update/status")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    def test_models_versions_results_endpoint(self, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
        ]
        with self.Session() as session:
            run = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="completed",
                force="false",
                created_at=datetime.now(),
                finished_at=datetime.now(),
            )
            session.add(run)
            session.commit()

        response = self.client.get("/api/models-versions/results")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("versions", payload)
        self.assertEqual(payload["date"], date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
