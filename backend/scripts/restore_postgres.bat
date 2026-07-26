@echo off
REM PostgreSQL restore wrapper. Prefer --mode dry-run or --mode test before overwrite.
REM Credentials: DATABASE_URL or PG* / POSTGRES_* — never hard-code passwords here.
setlocal
cd /d "%~dp0..\.."
set PYTHONPATH=%CD%;%PYTHONPATH%
python -m backend.src.jobs.run_db_restore %*
exit /b %ERRORLEVEL%
