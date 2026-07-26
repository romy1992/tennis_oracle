@echo off
REM Task Scheduler wrapper for PostgreSQL backup + admin alerts on failure.
REM Credentials: DATABASE_URL or PG* / POSTGRES_* — never hard-code passwords here.
setlocal
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%;%PYTHONPATH%
python -m backend.src.jobs.run_db_backup --alert %*
exit /b %ERRORLEVEL%
