import unittest
from datetime import date, timedelta
from unittest.mock import patch

from backend.src.jobs.daily_pipeline import DailyPipeline
from backend.src.jobs.generate_upcoming_predictions import run_upcoming_prediction_generation


class DailyPipelineTest(unittest.TestCase):
    @patch("backend.src.jobs.daily_pipeline.run_upcoming_prediction_generation")
    @patch("backend.src.jobs.daily_pipeline.run_daily_next_fixture_import")
    @patch("backend.src.jobs.daily_pipeline.run_daily_fixture_import")
    def test_generates_predictions_after_next_fixture_import(
        self,
        mock_fixture_import,
        mock_next_import,
        mock_prediction_generation,
    ):
        mock_next_import.return_value = {"inserted": 2}
        mock_prediction_generation.return_value = {"predictions_generated": 2}

        result = DailyPipeline(sync_cloud=False, days_forward=7).run()

        mock_fixture_import.assert_called_once()
        mock_next_import.assert_called_once()
        mock_prediction_generation.assert_called_once_with(
            days_forward=7,
            model_version="v2",
            model_name=None,
        )
        self.assertEqual(result["next_fixtures"], {"inserted": 2})
        self.assertEqual(result["predictions"], {"predictions_generated": 2})

    @patch("backend.src.jobs.generate_upcoming_predictions.predict_upcoming_fixtures")
    @patch("backend.src.jobs.generate_upcoming_predictions.list_next_fixtures")
    @patch("backend.src.jobs.generate_upcoming_predictions.SessionLocal")
    def test_prediction_generation_returns_warning_when_model_file_is_missing(
        self,
        mock_session_local,
        mock_list_next_fixtures,
        mock_predict_upcoming_fixtures,
    ):
        today = date.today()
        mock_session_local.return_value.__enter__.return_value = object()
        mock_list_next_fixtures.return_value = [object()]
        mock_predict_upcoming_fixtures.side_effect = FileNotFoundError(
            "Model not found: backend/data/models/v3/random_forest.pkl"
        )

        result = run_upcoming_prediction_generation(
            days_forward=7,
            model_version="v3",
            model_name="random_forest",
        )

        self.assertEqual(result["fixtures_considered"], 1)
        self.assertEqual(result["predictions_generated"], 0)
        self.assertEqual(result["model_version"], "v3")
        self.assertEqual(result["model_name"], "random_forest")
        self.assertIn("warnings", result)
        self.assertIn("Model not found", result["warnings"][0])
        mock_list_next_fixtures.assert_called_once_with(
            db=mock_session_local.return_value.__enter__.return_value,
            from_date=today,
            to_date=today + timedelta(days=7),
            limit=500,
            odds_required=True,
        )


if __name__ == "__main__":
    unittest.main()
