@echo off
REM Esegui dalla root del repository (Task Scheduler Windows, ore 09:00)
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%
if not exist backend\logs mkdir backend\logs
python -m backend.src.jobs.daily_pipeline --days-forward 10 >> backend\logs\daily_pipeline.log 2>&1
