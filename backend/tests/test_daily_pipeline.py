import unittest
from unittest.mock import patch

from backend.src.jobs.daily_pipeline import DailyPipeline


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


if __name__ == "__main__":
    unittest.main()
