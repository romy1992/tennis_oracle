from unittest.mock import patch

from backend.src.jobs.daily_pipeline import DailyPipeline, run_daily_pipeline


class TestDailyPipelineDelegation:
    @patch("backend.src.jobs.daily_pipeline.run_job", return_value=0)
    def test_run_delegates_to_shared_orchestrator(self, mock_run_job):
        pipeline = DailyPipeline(
            sync_cloud=False,
            days_forward=7,
            prediction_model_version="v2",
        )
        result = pipeline.run()
        assert result["orchestrator"] == "global_update"
        assert result["exit_code"] == 0
        mock_run_job.assert_called_once()
        kwargs = mock_run_job.call_args.kwargs
        assert kwargs["sync_cloud"] is False
        assert kwargs["days_forward"] == 7
        assert kwargs["force"] is True

    @patch("backend.src.jobs.daily_pipeline.run_job", return_value=1)
    def test_run_daily_pipeline_wrapper(self, mock_run_job):
        result = run_daily_pipeline(sync_cloud=True, days_forward=10)
        assert result["exit_code"] == 1
        mock_run_job.assert_called_once()
