import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from backend.src.app.main import app
from backend.src.app.services.global_update import (
    _execute_global_update,
    start_global_update,
)
from backend.src.entity.global_update_run import GlobalUpdateRun, GlobalUpdateRunItem
from backend.tests.db_helpers import create_session_factory, create_test_engine, make_api_client
from backend.tests.auth_helpers import (
    auth_header_for_admin,
    clear_settings_override,
    create_admin,
    make_test_settings,
    override_settings,
)


class GlobalUpdateServiceTest(unittest.TestCase):
    def setUp(self):
        import backend.src.app.services.global_update as gu

        self.engine = create_test_engine()
        self.Session = create_session_factory(self.engine)
        self.settings = make_test_settings()
        override_settings(self.settings)
        gu._active_run_id = None
        gu._cancel_requested.clear()
        gu._cancel_cache.clear()

        self.client = make_api_client(app, self.Session)
        with self.Session() as session:
            admin = create_admin(session)
            self.auth_headers = auth_header_for_admin(admin, self.settings)

    def tearDown(self):
        import backend.src.app.services.global_update as gu
        import time

        # Let mocked background threads finish and clear active run id.
        time.sleep(0.05)
        gu._active_run_id = None
        gu._cancel_requested.clear()
        gu._cancel_cache.clear()
        clear_settings_override()
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
    def test_start_global_update_filters_by_versions(self, mock_execute, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
            type("C", (), {"model_version": "v3", "model_name": "logistic_regression"})(),
            type("C", (), {"model_version": "v4", "model_name": "voting_ensemble"})(),
        ]

        with self.Session() as session:
            run, message = start_global_update(
                session, origin="manual", force=True, versions=["v3", "v4"]
            )
            self.assertIsNotNone(run)
            assert run is not None
            self.assertEqual(len(run.items), 2)
            self.assertEqual(
                {item.model_version for item in run.items}, {"v3", "v4"}
            )
            self.assertIn("started", message.lower())

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    @patch("backend.src.app.services.global_update._execute_global_update")
    def test_start_global_update_filters_by_versions_no_match(self, mock_execute, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
        ]

        with self.Session() as session:
            run, message = start_global_update(
                session, origin="manual", force=True, versions=["v4"]
            )
            self.assertIsNone(run)
            self.assertIn("nessuna combinazione abilitata", message.lower())
            mock_execute.assert_not_called()

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
    @patch("backend.src.app.services.global_update._execute_global_update")
    def test_idempotent_same_day_skip(self, mock_execute, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
        ]
        with self.Session() as session:
            done = GlobalUpdateRun(
                run_date=date.today(),
                origin="job",
                status="completed",
                force="false",
                created_at=datetime.now(),
                finished_at=datetime.now(),
            )
            session.add(done)
            session.commit()

            run, message = start_global_update(session, origin="job", force=False)
            self.assertIsNone(run)
            self.assertIn("already completed today", message.lower())
            mock_execute.assert_not_called()

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    def test_post_global_update_endpoint(self, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v2", "model_name": "logistic_regression"})(),
        ]
        with patch("backend.src.app.services.global_update._execute_global_update"):
            response = self.client.post(
                "/api/global-update",
                json={"force": True},
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("run_id", payload)
        self.assertEqual(payload["status"], "pending")

    @patch("backend.src.app.services.global_update.list_enabled_combinations")
    def test_post_global_update_endpoint_with_versions_filter(self, mock_combinations):
        mock_combinations.return_value = [
            type("C", (), {"model_version": "v3", "model_name": "logistic_regression"})(),
            type("C", (), {"model_version": "v4", "model_name": "voting_ensemble"})(),
        ]
        with patch("backend.src.app.services.global_update._execute_global_update"):
            response = self.client.post(
                "/api/global-update",
                json={"force": True, "versions": ["v4"]},
                headers=self.auth_headers,
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("run_id", payload)
        run = self.client.get(
            f"/api/global-update/{payload['run_id']}", headers=self.auth_headers
        ).json()
        self.assertEqual(len(run["items"]), 1)
        self.assertEqual(run["items"][0]["model_version"], "v4")

    def test_get_status_endpoint_empty(self):
        response = self.client.get("/api/global-update/status", headers=self.auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_extra_markets_are_generated_before_mixed_slips(self):
        import backend.src.app.services.global_update as gu

        override_settings(
            make_test_settings(
                global_update_allow_concurrent_runs=True,
                global_update_step_retries=0,
                global_update_step_timeout_seconds=10,
            )
        )
        with self.Session() as session:
            run = GlobalUpdateRun(
                run_date=date.today(),
                origin="manual",
                status="pending",
                force="true",
                created_at=datetime.now(),
            )
            session.add(run)
            session.flush()
            session.add(
                GlobalUpdateRunItem(
                    run_id=run.id,
                    model_version="v4",
                    model_name="voting_ensemble",
                    status="pending",
                )
            )
            session.commit()
            run_id = run.id

        call_order: list[str] = []

        def generate_extra(**_kwargs):
            call_order.append("extra_markets")
            return {"fixtures_considered": 0, "totals": {}, "by_market": {}}

        def generate_slips(**_kwargs):
            call_order.append("betting_slips")
            return SimpleNamespace(slips=[], warnings=[])

        disabled_public = SimpleNamespace(
            status="disabled",
            warning=None,
            model_version=None,
            model_name=None,
            is_ready=False,
        )
        import_status = {
            "next_fixtures_imported_today": False,
            "next_fixtures_max_date": None,
        }

        with (
            patch.object(gu, "SessionLocal", self.Session),
            patch.object(gu, "run_daily_fixture_import"),
            patch.object(gu, "purge_future_incomplete_fixtures", return_value=0),
            patch.object(gu, "record_fixture_import"),
            patch.object(gu, "run_daily_next_fixture_import", return_value={"inserted": 0}),
            patch.object(gu, "list_next_fixtures", return_value=[]),
            patch.object(gu, "clear_model_cache"),
            patch.object(
                gu,
                "run_extra_market_predictions_generation",
                side_effect=generate_extra,
            ),
            patch.object(gu, "get_daily_betting_slips", side_effect=generate_slips),
            patch.object(gu, "resolve_public_model_config", return_value=disabled_public),
            patch.object(gu, "heartbeat_pipeline_lock"),
            patch.object(gu, "is_cancel_requested", return_value=False),
            patch.object(gu, "get_import_status", return_value=import_status),
            patch.object(
                gu,
                "_run_with_retry_timeout",
                side_effect=lambda **kwargs: kwargs["fn"](),
            ),
            patch(
                "backend.src.app.services.walk_forward.maybe_run_walk_forward_for_global_update",
                return_value={"available": False, "executed": False},
            ),
            patch("backend.src.app.observability.notify.notify_global_update_finished"),
        ):
            _execute_global_update(run_id, days_forward=1, days_back_fixtures=1)

        self.assertEqual(call_order, ["extra_markets", "betting_slips"])
        with self.Session() as session:
            completed = session.get(GlobalUpdateRun, run_id)
            self.assertIsNotNone(completed)
            self.assertEqual(completed.status, "completed")

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
