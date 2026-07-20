import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.app.db.session import get_db
from backend.src.app.main import app
from backend.src.app.services.import_state import record_fixture_import
from backend.src.app.services.imports import refresh_matches
from backend.src.entity import Fixture, NextFixture
from backend.src.entity.base import Base
from backend.tests.auth_helpers import (
    clear_settings_override,
    create_admin,
    auth_header_for_admin,
    make_test_settings,
    override_settings,
)


class ImportRoutesTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.settings = make_test_settings()
        override_settings(self.settings)

        def override_get_db():
            with self.Session() as session:
                yield session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        with self.Session() as session:
            admin = create_admin(session)
            self.auth_headers = auth_header_for_admin(admin, self.settings)

    def tearDown(self):
        clear_settings_override()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_import_status_reports_next_fixture_and_fixture_dates(self):
        today = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=1,
                    event_date=date.today(),
                    imported_at=today,
                    is_completed=False,
                )
            )
            session.add(
                Fixture(
                    id_fixture=1,
                    event_key=10,
                    event_date=date(2026, 6, 27),
                )
            )
            session.commit()

        record_fixture_import(
            last_match_date=date(2026, 6, 27),
            imported_at=today,
            days_back_start=1,
        )

        response = self.client.get("/api/imports/status", headers=self.auth_headers)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["next_fixtures_imported_today"])
        self.assertEqual(payload["fixtures_last_match_date"], "2026-06-27")
        self.assertIsNotNone(payload["fixtures_last_imported_at"])

    @patch("backend.src.app.services.imports.run_upcoming_prediction_generation")
    @patch("backend.src.app.services.imports.run_daily_next_fixture_import")
    def test_refresh_skips_next_import_when_already_done_today(
        self,
        mock_next_import,
        mock_predictions,
    ):
        today = datetime.now(timezone.utc).replace(tzinfo=None)
        mock_predictions.return_value = {
            "fixtures_considered": 10,
            "predictions_generated": 10,
            "model_version": "v2",
            "model_name": "random_forest",
        }

        with self.Session() as session:
            session.add(
                NextFixture(
                    event_key=1,
                    event_date=date.today(),
                    imported_at=today,
                    is_completed=False,
                )
            )
            session.commit()

            result = refresh_matches(session, model_version="v2")

        self.assertFalse(result["next_fixtures_imported"])
        mock_next_import.assert_not_called()
        mock_predictions.assert_called_once()

    @patch("backend.src.app.services.imports.run_upcoming_prediction_generation")
    @patch("backend.src.app.services.imports.run_daily_next_fixture_import")
    def test_refresh_runs_next_import_when_missing_today(
        self,
        mock_next_import,
        mock_predictions,
    ):
        mock_next_import.return_value = {"inserted": 2, "updated": 1}
        mock_predictions.return_value = {
            "fixtures_considered": 3,
            "predictions_generated": 3,
            "model_version": "v2",
            "model_name": "random_forest",
        }

        with self.Session() as session:
            result = refresh_matches(session, model_version="v2")

        self.assertTrue(result["next_fixtures_imported"])
        mock_next_import.assert_called_once()
        mock_predictions.assert_called_once()

    @patch("backend.src.app.services.imports.import_played_fixtures")
    @patch("backend.src.app.services.imports.run_daily_next_fixture_import")
    @patch("backend.src.jobs.generate_upcoming_predictions.select_best_model")
    def test_refresh_route_returns_200_when_v3_metrics_are_missing(
        self,
        mock_select_best_model,
        mock_next_import,
        mock_import_played,
    ):
        mock_select_best_model.side_effect = FileNotFoundError(
            "Metrics report not found: baseline_v3_metrics.json"
        )
        mock_next_import.return_value = {"inserted": 2, "updated": 1}
        mock_import_played.return_value = {"days_back": 3}

        response = self.client.post(
            "/api/imports/refresh",
            params={"model_version": "v3", "force_next_import": "true"},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["next_fixtures_imported"])
        self.assertEqual(payload["predictions_summary"]["model_version"], "v3")
        self.assertEqual(payload["predictions_summary"]["predictions_generated"], 0)
        self.assertIn("warnings", payload["predictions_summary"])
        self.assertIn(
            "Metrics report not found",
            payload["predictions_summary"]["warnings"][0],
        )
        mock_next_import.assert_called_once()
        mock_import_played.assert_called_once()

    def test_debug_agent_log_endpoint_removed(self):
        response = self.client.post(
            "/api/debug/agent-log",
            json={"message": "should-not-exist"},
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
