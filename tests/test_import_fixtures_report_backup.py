import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.service import import_fixtures
from src.service import run_import_fixtures_report_backup as runner
from src.utility import request_api as request_api_module


class FakeFixtureRepository:
    def __init__(self, existing_event_keys=None):
        self.existing_event_keys = existing_event_keys or []
        self.saved = []

    def search_column_values(self, column_name):
        self.searched_column = column_name
        return self.existing_event_keys

    def save_all(self, fixtures):
        self.saved.extend(fixtures)


class ImportFixturesTest(unittest.TestCase):
    def test_import_fixtures_by_params_returns_stats_and_saves_only_new_records(self):
        fixture_repo = FakeFixtureRepository(existing_event_keys=[10])

        def fake_request_api(method, params=None):
            if method == "get_fixtures":
                return [
                    {"event_key": 10, "event_first_player": "Existing"},
                    {"event_key": 11, "event_first_player": "New player"},
                ]
            if method == "get_odds":
                return {"home": {"1": "1.5"}}
            raise AssertionError(f"Unexpected method: {method}")

        with patch.object(import_fixtures, "fixtures_repo", fixture_repo), \
                patch.object(import_fixtures, "request_api", side_effect=fake_request_api):
            stats = import_fixtures.import_fixtures_by_params(
                {"date_start": "2026-06-05", "date_stop": "2026-06-06"}
            )

        self.assertEqual(stats["status"], "success")
        self.assertEqual(stats["fixtures_received"], 2)
        self.assertEqual(stats["fixtures_already_present"], 1)
        self.assertEqual(stats["fixtures_imported"], 1)
        self.assertEqual(stats["odds_enriched"], 1)
        self.assertEqual([fixture.event_key for fixture in fixture_repo.saved], [11])
        self.assertEqual(fixture_repo.saved[0].odds, {"home": {"1": "1.5"}})


class ReportAndBackupRunnerTest(unittest.TestCase):
    def test_backup_database_uses_pg_dump_without_exposing_password_in_command(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_file = Path(tmp_dir) / "tennis_db_20260606_050000.sql"

            def fake_run(command, capture_output, env, text):
                backup_file.write_text("-- backup\n", encoding="utf-8")
                self.assertNotIn("secret", command)
                self.assertEqual(env["PGPASSWORD"], "secret")
                return Mock(returncode=0, stdout="", stderr="")

            with patch.object(runner.shutil, "which", return_value="/usr/bin/pg_dump"), \
                    patch.object(runner.subprocess, "run", side_effect=fake_run):
                result = runner.backup_database(
                    database_url="postgresql://postgres:secret@localhost:5432/tennis_db",
                    backup_dir=tmp_dir,
                    timestamp="20260606_050000",
                )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["method"], "pg_dump")
        self.assertEqual(result["path"], str(backup_file))
        self.assertGreater(result["size_bytes"], 0)

    def test_run_writes_report_with_failed_backup_status(self):
        import_stats = {
            "status": "success",
            "fixtures_received": 1,
            "fixtures_already_present": 0,
            "fixtures_imported": 1,
            "odds_enriched": 1,
            "errors": [],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir) / "reports"
            backup_dir = Path(tmp_dir) / "backups"
            with patch.object(runner, "import_fixtures_by_params", return_value=import_stats), \
                    patch.object(runner, "backup_database", side_effect=RuntimeError("pg_dump non trovato")):
                result = runner.run(
                    date_start="2026-06-05",
                    date_stop="2026-06-06",
                    report_dir=report_dir,
                    backup_dir=backup_dir,
                )

            report_path = Path(result["report_path"])
            report = report_path.read_text(encoding="utf-8")

        self.assertFalse(result["success"])
        self.assertIn("Esito generale: KO", report)
        self.assertIn("- stato: failed", report)
        self.assertIn("Backup database: pg_dump non trovato", report)


class RequestApiTest(unittest.TestCase):
    def test_request_api_raises_for_application_error_and_masks_api_key_in_logs(self):
        response = Mock(
            status_code=200,
            url="https://api.api-tennis.com/tennis/?APIkey=secret&method=get_fixtures",
        )
        response.json.return_value = {"result": [{"cod": 1006, "msg": "Please make the payment"}]}

        with patch.object(request_api_module, "API_KEY", "secret"), \
                patch.object(request_api_module.requests, "get", return_value=response), \
                self.assertLogs(level="INFO") as logs:
            with self.assertRaises(request_api_module.ApiTennisError):
                request_api_module.request_api("get_fixtures", {"date_start": "2026-06-05"})

        joined_logs = "\n".join(logs.output)
        self.assertIn("APIkey=%2A%2A%2A%2A", joined_logs)
        self.assertNotIn("APIkey=secret", joined_logs)


if __name__ == "__main__":
    unittest.main()
