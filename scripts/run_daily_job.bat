@echo off
REM Esegui dal root del progetto (Task Scheduler Windows, ore 09:00)
cd /d "%~dp0.."
set PYTHONPATH=%CD%
if not exist logs mkdir logs
python scripts\run_import_fixtures_report_backup.py >> logs\import_fixtures_report_backup.log 2>&1
