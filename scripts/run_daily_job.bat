@echo off
REM Esegui dal root del progetto (Task Scheduler Windows, ore 09:00)
cd /d "%~dp0.."
set PYTHONPATH=%CD%
python -m src.jobs.daily_pipeline >> logs\daily_pipeline.log 2>&1
