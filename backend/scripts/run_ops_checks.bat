@echo off
REM Cron / Task Scheduler wrapper for operational checks + admin alerts.
setlocal
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%;%PYTHONPATH%
python -m backend.src.jobs.run_ops_checks --alert %*
exit /b %ERRORLEVEL%
