@echo off
REM Esegui dalla cartella backend (Task Scheduler Windows, ore 09:00)
cd /d "%~dp0.."
set PYTHONPATH=%CD%
if not exist logs mkdir logs
python -m src.jobs.daily_pipeline >> logs\daily_pipeline.log 2>&1
