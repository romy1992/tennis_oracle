"""Discover enabled model/version combinations and run the global update orchestrator.

Shared by:
- frontend / API ``POST /api/global-update`` (background thread)
- optional in-app scheduler
- CLI job ``python -m backend.src.jobs.run_global_update`` (blocking worker)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.src.app.core.config import get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.model_versioning import MODEL_VERSIONS, ModelVersion
from backend.src.app.ml.prediction.predictor import (
    PredictUpcomingCancelled,
    clear_model_cache,
    predict_upcoming_fixtures,
)
from backend.src.app.models import Fixture
from backend.src.app.services.betting_slips import get_daily_betting_slips
from backend.src.app.services.import_state import get_import_status, record_fixture_import
from backend.src.app.services.imports import purge_future_incomplete_fixtures
from backend.src.app.services.live_publication_service import (
    is_public_combination,
    publish_official_plays_for_day,
    resolve_public_model_config,
)
from backend.src.app.services.pipeline_lock import (
    GLOBAL_UPDATE_LOCK_NAME,
    acquire_pipeline_lock,
    get_pipeline_lock,
    heartbeat_pipeline_lock,
    new_owner_token,
    release_pipeline_lock,
)
from backend.src.app.services.predictions import list_next_fixtures
from backend.src.entity.global_update_run import GlobalUpdateRun, GlobalUpdateRunItem
from backend.src.service.import_fixtures import run_daily_fixture_import
from backend.src.service.import_next_fixtures import run_daily_next_fixture_import

logger = logging.getLogger(__name__)


MODEL_NAMES = ("logistic_regression", "random_forest")
RUNNING_STATUSES = ("pending", "running")
RESUMABLE_STATUSES = ("interrupted", "failed", "cancelled")
PHASE_IMPORT_FIXTURES = "import_fixtures"
PHASE_IMPORT_NEXT = "import_next_fixtures"
PHASE_COMBINATIONS = "predict_combinations"
PHASE_SYNC_CLOUD = "sync_cloud"
PHASE_REPORT = "finalize_report"

GlobalUpdateOrigin = Literal["manual", "cron", "job"]

_active_thread_lock = threading.Lock()
_active_run_id: int | None = None
_cancel_requested: set[int] = set()
_cancel_cache: dict[int, tuple[float, bool]] = {}


class GlobalUpdateCancelled(Exception):
    """Raised when a run is cancelled cooperatively."""


class GlobalUpdateStepTimeout(Exception):
    """Raised when a pipeline step exceeds its configured timeout."""


@dataclass(frozen=True)
class ModelCombination:
    model_version: ModelVersion
    model_name: str


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def list_enabled_combinations() -> list[ModelCombination]:
    """Return all version/model pairs whose artifact exists on disk."""
    combinations: list[ModelCombination] = []
    for version in MODEL_VERSIONS:
        models_dir = MODEL_VERSIONS[version].models_dir
        for model_name in MODEL_NAMES:
            if (models_dir / f"{model_name}.pkl").exists():
                combinations.append(ModelCombination(version, model_name))
    return combinations


def _get_running_run(db: Session) -> GlobalUpdateRun | None:
    return db.scalar(
        select(GlobalUpdateRun)
        .where(GlobalUpdateRun.status.in_(RUNNING_STATUSES))
        .order_by(GlobalUpdateRun.id.desc())
        .limit(1)
    )


def _get_completed_run_for_date(db: Session, run_date: date) -> GlobalUpdateRun | None:
    return db.scalar(
        select(GlobalUpdateRun)
        .where(
            GlobalUpdateRun.run_date == run_date,
            GlobalUpdateRun.status.in_(("completed", "completed_with_errors")),
        )
        .order_by(GlobalUpdateRun.id.desc())
        .limit(1)
    )


def get_resumable_run(db: Session, run_id: int | None = None) -> GlobalUpdateRun | None:
    """Latest interrupted/failed/cancelled run, or a specific id if resumable."""
    stmt = (
        select(GlobalUpdateRun)
        .options(selectinload(GlobalUpdateRun.items))
        .where(GlobalUpdateRun.status.in_(RESUMABLE_STATUSES))
        .order_by(GlobalUpdateRun.id.desc())
    )
    if run_id is not None:
        stmt = (
            select(GlobalUpdateRun)
            .options(selectinload(GlobalUpdateRun.items))
            .where(
                GlobalUpdateRun.id == run_id,
                GlobalUpdateRun.status.in_(RESUMABLE_STATUSES + RUNNING_STATUSES),
            )
        )
    return db.scalar(stmt.limit(1))


def _run_to_read_dict(run: GlobalUpdateRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "run_date": run.run_date,
        "origin": run.origin,
        "status": run.status,
        "current_phase": run.current_phase,
        "progress_pct": run.progress_pct,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "duration_seconds": run.duration_seconds,
        "force": run.force == "true",
        "versions_processed": run.versions_processed,
        "models_processed": run.models_processed,
        "combinations_completed": run.combinations_completed,
        "combinations_failed": run.combinations_failed,
        "combinations_skipped": run.combinations_skipped,
        "fixtures_processed": run.fixtures_processed,
        "slips_generated": run.slips_generated,
        "errors": _json_loads(run.errors_json, []),
        "warnings": _json_loads(run.warnings_json, []),
        "items": [
            {
                "model_version": item.model_version,
                "model_name": item.model_name,
                "status": item.status,
                "started_at": item.started_at,
                "finished_at": item.finished_at,
                "duration_seconds": item.duration_seconds,
                "predictions_generated": item.predictions_generated,
                "slips_generated": item.slips_generated,
                "error_message": item.error_message,
                "warnings": _json_loads(item.warnings_json, []),
            }
            for item in run.items
        ],
    }


def get_run_by_id(db: Session, run_id: int) -> GlobalUpdateRun | None:
    return db.scalar(
        select(GlobalUpdateRun)
        .options(selectinload(GlobalUpdateRun.items))
        .where(GlobalUpdateRun.id == run_id)
    )


def get_latest_run(db: Session) -> GlobalUpdateRun | None:
    return db.scalar(
        select(GlobalUpdateRun)
        .options(selectinload(GlobalUpdateRun.items))
        .order_by(GlobalUpdateRun.id.desc())
        .limit(1)
    )


def get_active_run(db: Session) -> GlobalUpdateRun | None:
    return _get_running_run(db)


def is_cancel_requested(run_id: int) -> bool:
    if run_id in _cancel_requested:
        return True
    now = time.monotonic()
    cached = _cancel_cache.get(run_id)
    if cached and now - cached[0] < 1.0:
        return cached[1]
    try:
        with SessionLocal() as db:
            flag = db.scalar(
                select(GlobalUpdateRun.cancel_requested).where(GlobalUpdateRun.id == run_id)
            )
            value = flag == "true"
    except Exception:
        value = False
    _cancel_cache[run_id] = (now, value)
    if value:
        _cancel_requested.add(run_id)
    return value


def _finalize_cancelled_run(db: Session, run: GlobalUpdateRun, *, reason: str) -> None:
    now = datetime.now()
    run.status = "cancelled"
    run.current_phase = "Annullato"
    run.finished_at = now
    run.cancel_requested = "false"
    if run.started_at:
        run.duration_seconds = round((now - run.started_at).total_seconds(), 2)
    errors = _json_loads(run.errors_json, [])
    if reason not in errors:
        errors.append(reason)
    run.errors_json = _json_dumps(errors)
    for item in run.items:
        if item.status in ("pending", "running"):
            item.status = "cancelled"
            item.finished_at = now
            if item.started_at:
                item.duration_seconds = round((now - item.started_at).total_seconds(), 2)
    db.commit()


def _mark_interrupted(db: Session, run: GlobalUpdateRun, *, reason: str) -> None:
    now = datetime.now()
    run.status = "interrupted"
    run.current_phase = "Interrotto"
    run.finished_at = now
    if run.started_at:
        run.duration_seconds = round((now - run.started_at).total_seconds(), 2)
    errors = _json_loads(run.errors_json, [])
    if reason not in errors:
        errors.append(reason)
    run.errors_json = _json_dumps(errors)
    for item in run.items:
        if item.status == "running":
            item.status = "failed"
            item.error_message = item.error_message or reason
            item.finished_at = now
            if item.started_at:
                item.duration_seconds = round((now - item.started_at).total_seconds(), 2)
    db.commit()


def reconcile_orphaned_runs(db: Session) -> int:
    """Mark process-dead active runs as interrupted so they can be resumed."""
    global _active_run_id

    with _active_thread_lock:
        active_id = _active_run_id

    runs = db.scalars(
        select(GlobalUpdateRun)
        .options(selectinload(GlobalUpdateRun.items))
        .where(GlobalUpdateRun.status.in_(RUNNING_STATUSES))
    ).all()
    reconciled = 0
    for run in runs:
        if active_id == run.id:
            continue
        _mark_interrupted(
            db,
            run,
            reason="Run interrupted (backend restarted or worker lost). Resume with --resume.",
        )
        _cancel_requested.discard(run.id)
        _cancel_cache.pop(run.id, None)
        reconciled += 1
    return reconciled


def cancel_global_update(db: Session, run_id: int) -> tuple[bool, str]:
    global _active_run_id

    run = get_run_by_id(db, run_id)
    if run is None:
        return False, f"Run {run_id} not found."
    if run.status not in RUNNING_STATUSES:
        return False, f"Run {run_id} is not active (status={run.status})."

    run.cancel_requested = "true"
    db.commit()
    _cancel_requested.add(run_id)
    _cancel_cache[run_id] = (time.monotonic(), True)

    with _active_thread_lock:
        thread_active = _active_run_id == run_id

    if thread_active:
        return True, "Cancellation requested."

    # Another process (CLI job / other API worker) may still own the lease.
    lock = get_pipeline_lock(db)
    now = datetime.now()
    lock_held_for_run = (
        lock is not None
        and lock.run_id == run_id
        and lock.owner_token is not None
        and lock.expires_at is not None
        and lock.expires_at > now
    )
    if lock_held_for_run:
        return True, "Cancellation requested."

    # No local or remote worker: safe to finalize.
    _finalize_cancelled_run(db, run, reason="Run cancelled by user.")
    _cancel_requested.discard(run_id)
    _cancel_cache.pop(run_id, None)
    with _active_thread_lock:
        if _active_run_id == run_id:
            _active_run_id = None
    return True, "Run cancelled."


def _combo_progress_pct(index: int, total_combos: int, fixture_index: int, fixture_total: int) -> float:
    combo_span = 75.0 / max(total_combos, 1)
    combo_start = 10.0 + index * combo_span
    if fixture_total <= 0:
        return round(combo_start + combo_span, 2)
    fixture_ratio = min(max(fixture_index / fixture_total, 0.0), 1.0)
    return round(combo_start + fixture_ratio * combo_span, 2)


def _load_phases(run: GlobalUpdateRun) -> list[dict[str, Any]]:
    return list(_json_loads(run.phases_json, []))


def _phase_completed(phases: list[dict[str, Any]], phase: str) -> bool:
    return any(p.get("phase") == phase and p.get("status") == "completed" for p in phases)


def _upsert_phase(phases: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    name = entry.get("phase")
    updated = [p for p in phases if p.get("phase") != name]
    updated.append(entry)
    return updated


def _persist_phases(db: Session, run: GlobalUpdateRun, phases: list[dict[str, Any]]) -> None:
    run.phases_json = _json_dumps(phases)
    db.commit()


def _run_with_retry_timeout(
    *,
    label: str,
    fn: Callable[[], Any],
    retries: int,
    backoff_seconds: float,
    timeout_seconds: int,
    should_cancel: Callable[[], bool],
) -> Any:
    attempts = max(retries, 0) + 1
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        if should_cancel():
            raise GlobalUpdateCancelled()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(fn)
                return future.result(timeout=timeout_seconds)
        except FuturesTimeoutError as exc:
            last_exc = GlobalUpdateStepTimeout(
                f"{label} timed out after {timeout_seconds}s (attempt {attempt}/{attempts})"
            )
            logger.error("%s", last_exc)
        except GlobalUpdateCancelled:
            raise
        except Exception as exc:
            last_exc = exc
            logger.exception("%s failed (attempt %s/%s)", label, attempt, attempts)
        if attempt < attempts:
            time.sleep(max(backoff_seconds, 0.0) * attempt)
    assert last_exc is not None
    raise last_exc


def start_global_update(
    db: Session,
    *,
    origin: GlobalUpdateOrigin = "manual",
    force: bool = False,
    days_forward: int = 10,
    days_back_fixtures: int = 3,
    sync_cloud: bool = False,
    resume: bool = False,
    resume_run_id: int | None = None,
    blocking: bool = False,
) -> tuple[GlobalUpdateRun | None, str]:
    """Create or resume a run and start processing.

    When ``blocking=True`` the caller thread executes the pipeline (CLI job).
    Otherwise a daemon thread is started (API / in-app cron).
    """
    global _active_run_id
    settings = get_settings()

    with _active_thread_lock:
        if _active_run_id is not None and not settings.global_update_allow_concurrent_runs:
            existing = get_run_by_id(db, _active_run_id)
            if existing and existing.status in RUNNING_STATUSES:
                return None, f"Global update already running (run_id={_active_run_id})."
            _active_run_id = None

        if not settings.global_update_allow_concurrent_runs:
            running = _get_running_run(db)
            if running is not None:
                return None, f"Global update already running (run_id={running.id})."

        if resume or resume_run_id is not None:
            run = get_resumable_run(db, resume_run_id)
            if run is None:
                return None, "No resumable global update run found."
            if run.status in RUNNING_STATUSES and not settings.global_update_allow_concurrent_runs:
                return None, f"Global update already running (run_id={run.id})."

            run.status = "pending"
            run.cancel_requested = "false"
            run.finished_at = None
            run.resume_count = int(run.resume_count or 0) + 1
            run.current_phase = "Ripresa"
            run.progress_pct = run.progress_pct or 0.0
            for item in run.items:
                if item.status in ("failed", "cancelled", "running"):
                    item.status = "pending"
                    item.error_message = None
                    item.started_at = None
                    item.finished_at = None
                    item.duration_seconds = None
            db.commit()
            db.refresh(run)
            message = f"Global update resume started (run_id={run.id})."
        else:
            today = date.today()
            if not force:
                completed_today = _get_completed_run_for_date(db, today)
                if completed_today is not None:
                    return None, (
                        f"Global update already completed today (run_id={completed_today.id}). "
                        "Use force=true to run again."
                    )

            combinations = list_enabled_combinations()
            if not combinations:
                return None, "No enabled model/version combinations found."

            now = datetime.now()
            run = GlobalUpdateRun(
                run_date=today,
                origin=origin,
                status="pending",
                current_phase="Preparazione",
                progress_pct=0.0,
                force="true" if force else "false",
                cancel_requested="false",
                sync_cloud="true" if sync_cloud else "false",
                resume_count=0,
                created_at=now,
            )
            db.add(run)
            db.flush()

            for combo in combinations:
                db.add(
                    GlobalUpdateRunItem(
                        run_id=run.id,
                        model_version=combo.model_version,
                        model_name=combo.model_name,
                        status="pending",
                    )
                )
            db.commit()
            db.refresh(run)
            message = "Global update started."

        if blocking:
            _active_run_id = run.id
            try:
                _execute_global_update(
                    run.id,
                    days_forward,
                    days_back_fixtures,
                    sync_cloud=run.sync_cloud == "true" or sync_cloud,
                )
            finally:
                with _active_thread_lock:
                    if _active_run_id == run.id:
                        _active_run_id = None
            db.expire_all()
            refreshed = get_run_by_id(db, run.id)
            return refreshed, message

        run_id_for_thread = run.id
        sync_flag = run.sync_cloud == "true" or sync_cloud

        def _thread_target() -> None:
            global _active_run_id
            try:
                _execute_global_update(
                    run_id_for_thread,
                    days_forward,
                    days_back_fixtures,
                    sync_cloud=sync_flag,
                )
            finally:
                with _active_thread_lock:
                    if _active_run_id == run_id_for_thread:
                        _active_run_id = None

        thread = threading.Thread(
            target=_thread_target,
            name=f"global-update-{run_id_for_thread}",
            daemon=True,
        )
        _active_run_id = run_id_for_thread
        thread.start()
        return run, message


def _update_run_phase(
    db: Session,
    run: GlobalUpdateRun,
    *,
    phase: str,
    progress_pct: float | None = None,
    owner_token: str | None = None,
) -> None:
    run.current_phase = phase
    if progress_pct is not None:
        run.progress_pct = progress_pct
    db.commit()
    if owner_token:
        settings = get_settings()
        heartbeat_pipeline_lock(
            db,
            name=GLOBAL_UPDATE_LOCK_NAME,
            owner_token=owner_token,
            ttl_seconds=settings.global_update_lock_ttl_seconds,
        )


def _sync_cloud_step() -> dict[str, Any]:
    from backend.src.service.database_migrator import run_migration

    source = os.getenv("DATABASE_SOURCE_URL") or os.getenv("DATABASE_URL")
    target = os.getenv("DATABASE_TARGET_URL")
    if not source or not target:
        return {
            "skipped": True,
            "reason": "DATABASE_SOURCE_URL/DATABASE_URL or DATABASE_TARGET_URL missing",
        }
    if source == target:
        raise ValueError("SOURCE e TARGET non possono essere uguali.")
    summary = run_migration(
        upsert=True,
        tables=("fixture", "next_fixture", "match_prediction"),
    )
    return {"skipped": False, "summary": summary}


def _execute_global_update(
    run_id: int,
    days_forward: int,
    days_back_fixtures: int,
    *,
    sync_cloud: bool = False,
) -> None:
    global _active_run_id
    settings = get_settings()
    started = time.perf_counter()
    owner_token = new_owner_token()
    lock_acquired = False
    phases: list[dict[str, Any]] = []
    run_errors: list[str] = []
    run_warnings: list[str] = []

    try:
        with SessionLocal() as db:
            run = get_run_by_id(db, run_id)
            if run is None:
                return

            if not settings.global_update_allow_concurrent_runs:
                lock_acquired = acquire_pipeline_lock(
                    db,
                    owner_token=owner_token,
                    run_id=run_id,
                    ttl_seconds=settings.global_update_lock_ttl_seconds,
                )
                if not lock_acquired:
                    run.status = "failed"
                    run.current_phase = "Lock non acquisito"
                    run.finished_at = datetime.now()
                    run.errors_json = _json_dumps(
                        ["Could not acquire distributed pipeline lock (another worker holds it)."]
                    )
                    db.commit()
                    return

            run.status = "running"
            run.worker_id = owner_token
            if run.started_at is None:
                run.started_at = datetime.now()
            run.cancel_requested = "false"
            run.finished_at = None
            if sync_cloud:
                run.sync_cloud = "true"
            phases = _load_phases(run)
            run_errors = list(_json_loads(run.errors_json, []))
            run_warnings = list(_json_loads(run.warnings_json, []))
            _update_run_phase(
                db,
                run,
                phase="Preparazione",
                progress_pct=max(run.progress_pct or 0.0, 1.0),
                owner_token=owner_token,
            )

            combinations = [
                ModelCombination(item.model_version, item.model_name)  # type: ignore[arg-type]
                for item in run.items
            ]
            unique_versions = {combo.model_version for combo in combinations}
            unique_models = {combo.model_name for combo in combinations}
            run.versions_processed = len(unique_versions)
            run.models_processed = len(unique_models)
            db.commit()

            retries = settings.global_update_step_retries
            backoff = settings.global_update_retry_backoff_seconds
            timeout = settings.global_update_step_timeout_seconds

            # Phase: import fixtures
            if not _phase_completed(phases, PHASE_IMPORT_FIXTURES):
                phase_start = time.perf_counter()
                _update_run_phase(
                    db, run, phase="Recupero partite disputate", progress_pct=5.0, owner_token=owner_token
                )
                try:
                    def _import_fixtures() -> dict[str, Any]:
                        run_daily_fixture_import(
                            days_back_start=max(days_back_fixtures, 1),
                            days_back_stop=0,
                        )
                        with SessionLocal() as step_db:
                            purged = purge_future_incomplete_fixtures(step_db)
                            today_for_state = date.today()
                            date_from = today_for_state - timedelta(days=max(days_back_fixtures, 1))
                            last_match_date = step_db.scalar(
                                select(func.max(Fixture.event_date)).where(
                                    Fixture.event_date >= date_from,
                                    Fixture.event_date <= today_for_state,
                                )
                            )
                            record_fixture_import(
                                last_match_date=last_match_date,
                                imported_at=datetime.now(),
                                days_back_start=max(days_back_fixtures, 1),
                            )
                            return {
                                "purged_future_incomplete": purged,
                                "last_match_date": (
                                    last_match_date.isoformat() if last_match_date else None
                                ),
                            }

                    detail = _run_with_retry_timeout(
                        label=PHASE_IMPORT_FIXTURES,
                        fn=_import_fixtures,
                        retries=retries,
                        backoff_seconds=backoff,
                        timeout_seconds=timeout,
                        should_cancel=lambda: is_cancel_requested(run_id),
                    )
                    phases = _upsert_phase(
                        phases,
                        {
                            "phase": PHASE_IMPORT_FIXTURES,
                            "duration_seconds": round(time.perf_counter() - phase_start, 2),
                            "status": "completed",
                            **detail,
                        },
                    )
                except GlobalUpdateCancelled:
                    raise
                except Exception as exc:
                    msg = f"Fixture import failed: {exc}"
                    run_errors.append(msg)
                    phases = _upsert_phase(
                        phases,
                        {
                            "phase": PHASE_IMPORT_FIXTURES,
                            "duration_seconds": round(time.perf_counter() - phase_start, 2),
                            "status": "failed",
                            "error": str(exc),
                        },
                    )
                    logger.exception(msg)
                _persist_phases(db, run, phases)
                run.errors_json = _json_dumps(run_errors)
                db.commit()

            # Phase: import next fixtures
            fixtures_count = 0
            if not _phase_completed(phases, PHASE_IMPORT_NEXT):
                phase_start = time.perf_counter()
                _update_run_phase(
                    db, run, phase="Recupero prossime partite", progress_pct=10.0, owner_token=owner_token
                )
                try:
                    def _import_next() -> dict[str, Any]:
                        next_summary = run_daily_next_fixture_import(
                            days_forward=days_forward,
                            days_back=days_back_fixtures,
                        )
                        return {
                            "fixtures_imported": int(next_summary.get("inserted", 0) or 0),
                            "summary": next_summary,
                        }

                    detail = _run_with_retry_timeout(
                        label=PHASE_IMPORT_NEXT,
                        fn=_import_next,
                        retries=retries,
                        backoff_seconds=backoff,
                        timeout_seconds=timeout,
                        should_cancel=lambda: is_cancel_requested(run_id),
                    )
                    fixtures_count = int(detail.get("fixtures_imported", 0) or 0)
                    phases = _upsert_phase(
                        phases,
                        {
                            "phase": PHASE_IMPORT_NEXT,
                            "duration_seconds": round(time.perf_counter() - phase_start, 2),
                            "status": "completed",
                            "fixtures_imported": fixtures_count,
                        },
                    )
                except GlobalUpdateCancelled:
                    raise
                except Exception as exc:
                    msg = f"Next fixture import failed: {exc}"
                    run_errors.append(msg)
                    phases = _upsert_phase(
                        phases,
                        {
                            "phase": PHASE_IMPORT_NEXT,
                            "duration_seconds": round(time.perf_counter() - phase_start, 2),
                            "status": "failed",
                            "error": str(exc),
                        },
                    )
                    logger.exception(msg)
                _persist_phases(db, run, phases)
                run.errors_json = _json_dumps(run_errors)
                db.commit()

            today = date.today()
            upcoming_fixtures_by_version: dict[ModelVersion, list] = {}
            for version in unique_versions:
                upcoming_fixtures_by_version[version] = list_next_fixtures(
                    db=db,
                    from_date=today,
                    to_date=today + timedelta(days=days_forward),
                    limit=500,
                    odds_required=version == "v3",
                )
            run.fixtures_processed = max(
                (len(fixtures) for fixtures in upcoming_fixtures_by_version.values()),
                default=0,
            )
            db.commit()

            total_combos = len(combinations)
            completed = sum(1 for item in run.items if item.status == "completed")
            failed = 0
            skipped = sum(1 for item in run.items if item.status == "skipped")
            total_slips = sum(int(item.slips_generated or 0) for item in run.items)
            live_publication_report: dict[str, Any] | None = None

            public_cfg = resolve_public_model_config()
            if public_cfg.warning and public_cfg.warning not in run_warnings:
                run_warnings.append(public_cfg.warning)
            if public_cfg.is_ready:
                public_in_run = any(
                    combo.model_version == public_cfg.model_version
                    and combo.model_name == public_cfg.model_name
                    for combo in combinations
                )
                if not public_in_run:
                    warn = (
                        "Live publication enabled but public model "
                        f"{public_cfg.model_version}/{public_cfg.model_name} "
                        "is not among enabled combinations for this run "
                        "(missing artifact?). No tips published."
                    )
                    if warn not in run_warnings:
                        run_warnings.append(warn)

            clear_model_cache()

            for index, combo in enumerate(combinations):
                if is_cancel_requested(run_id):
                    raise GlobalUpdateCancelled()

                item = db.scalar(
                    select(GlobalUpdateRunItem).where(
                        GlobalUpdateRunItem.run_id == run.id,
                        GlobalUpdateRunItem.model_version == combo.model_version,
                        GlobalUpdateRunItem.model_name == combo.model_name,
                    )
                )
                if item is None:
                    continue

                # Idempotent resume: skip already successful/skipped items.
                if item.status in ("completed", "skipped"):
                    continue

                progress = _combo_progress_pct(index, total_combos, 0, 1)
                phase_label = f"Elaborazione {combo.model_version} / {combo.model_name}"
                _update_run_phase(
                    db, run, phase=phase_label, progress_pct=progress, owner_token=owner_token
                )

                item.status = "running"
                item.started_at = datetime.now()
                item.error_message = None
                db.commit()

                item_start = time.perf_counter()
                item_warnings: list[str] = []
                predictions_count = 0
                slips_count = 0
                live_publication_summary: dict[str, Any] | None = None

                try:
                    def _predict_combo() -> tuple[int, int, list[str], dict[str, Any] | None]:
                        local_warnings: list[str] = []
                        local_live: dict[str, Any] | None = None
                        local_preds = 0
                        local_slips = 0
                        with SessionLocal() as step_db:
                            fixtures = list_next_fixtures(
                                db=step_db,
                                from_date=today,
                                to_date=today + timedelta(days=days_forward),
                                limit=500,
                                odds_required=combo.model_version == "v3",
                            )
                            if fixtures:
                                def _progress_callback(fixture_index: int, fixture_total: int) -> None:
                                    if (
                                        fixture_total > 0
                                        and fixture_index not in (1, fixture_total)
                                        and fixture_index % 5 != 0
                                    ):
                                        return
                                    pct = _combo_progress_pct(
                                        index, total_combos, fixture_index, fixture_total
                                    )
                                    with SessionLocal() as prog_db:
                                        prog_run = get_run_by_id(prog_db, run_id)
                                        if prog_run is None:
                                            return
                                        _update_run_phase(
                                            prog_db,
                                            prog_run,
                                            phase=phase_label,
                                            progress_pct=pct,
                                            owner_token=owner_token,
                                        )

                                predictions = predict_upcoming_fixtures(
                                    db=step_db,
                                    fixtures=fixtures,
                                    model_version=combo.model_version,
                                    model_name=combo.model_name,
                                    persist=True,
                                    progress_callback=_progress_callback,
                                    should_cancel=lambda: is_cancel_requested(run_id),
                                )
                                local_preds = sum(
                                    1
                                    for p in predictions
                                    if p.get("prob_player_1_win") is not None
                                )
                            else:
                                local_warnings.append("no_upcoming_fixtures")

                            try:
                                daily = get_daily_betting_slips(
                                    db=step_db,
                                    slip_date=today,
                                    model_version=combo.model_version,
                                    model_name=combo.model_name,
                                    regenerate=True,
                                )
                                local_slips = len(daily.slips)
                                local_warnings.extend(daily.warnings)
                            except Exception as slip_exc:
                                step_db.rollback()
                                local_warnings.append(f"betting_slips:{slip_exc}")

                            if is_public_combination(combo.model_version, combo.model_name):
                                try:
                                    pub_report = publish_official_plays_for_day(
                                        step_db,
                                        slip_date=today,
                                        model_version=combo.model_version,
                                        model_name=combo.model_name,
                                    )
                                    local_live = pub_report.to_dict()
                                    if pub_report.config_warning:
                                        local_warnings.append(
                                            f"live_publication:{pub_report.config_warning}"
                                        )
                                    if pub_report.publication_errors:
                                        for err in pub_report.publication_errors:
                                            local_warnings.append(f"live_publication_error:{err}")
                                    local_warnings.append(
                                        "live_publication:"
                                        f"created={pub_report.publications_created},"
                                        f"duplicates={pub_report.duplicates_skipped},"
                                        f"excluded={pub_report.predictions_excluded},"
                                        f"candidates={pub_report.candidates_evaluated}"
                                    )
                                except Exception as pub_exc:
                                    step_db.rollback()
                                    local_warnings.append(f"live_publication_failed:{pub_exc}")
                                    local_live = {
                                        "config_status": "error",
                                        "error": str(pub_exc),
                                    }
                                    logger.exception(
                                        "Live publication failed for %s/%s",
                                        combo.model_version,
                                        combo.model_name,
                                    )
                        return local_preds, local_slips, local_warnings, local_live

                    predictions_count, slips_count, item_warnings, live_publication_summary = (
                        _run_with_retry_timeout(
                            label=f"combo:{combo.model_version}/{combo.model_name}",
                            fn=_predict_combo,
                            retries=retries,
                            backoff_seconds=backoff,
                            timeout_seconds=timeout,
                            should_cancel=lambda: is_cancel_requested(run_id),
                        )
                    )
                    if live_publication_summary is not None:
                        live_publication_report = live_publication_summary
                        for w in item_warnings:
                            if w.startswith("live_publication_error:") or w.startswith(
                                "live_publication_failed:"
                            ):
                                run_errors.append(
                                    f"{combo.model_version}/{combo.model_name}: {w}"
                                )

                    item.status = "completed"
                    completed += 1
                except GlobalUpdateCancelled:
                    raise
                except PredictUpcomingCancelled:
                    raise GlobalUpdateCancelled() from None
                except FileNotFoundError as exc:
                    item.status = "skipped"
                    item.error_message = str(exc)
                    skipped += 1
                    item_warnings.append("model_artifact_missing")
                except Exception as exc:
                    item.status = "failed"
                    item.error_message = str(exc)
                    failed += 1
                    run_errors.append(f"{combo.model_version}/{combo.model_name}: {exc}")
                    logger.exception(
                        "Global update failed for %s/%s",
                        combo.model_version,
                        combo.model_name,
                    )

                item.finished_at = datetime.now()
                item.duration_seconds = round(time.perf_counter() - item_start, 2)
                item.predictions_generated = predictions_count
                item.slips_generated = slips_count
                if live_publication_summary is not None:
                    item_warnings.append(
                        "live_publication_summary:"
                        + json.dumps(live_publication_summary, ensure_ascii=True)
                    )
                item.warnings_json = _json_dumps(item_warnings)
                total_slips += slips_count
                db.commit()

            phases = _upsert_phase(
                phases,
                {
                    "phase": PHASE_COMBINATIONS,
                    "status": "completed" if failed == 0 else "completed_with_errors",
                    "combinations_completed": completed,
                    "combinations_failed": failed,
                    "combinations_skipped": skipped,
                },
            )
            _persist_phases(db, run, phases)

            # Optional cloud sync (CLI / job); skipped for pure UI runs unless requested.
            want_sync = sync_cloud or run.sync_cloud == "true"
            if want_sync and not _phase_completed(phases, PHASE_SYNC_CLOUD):
                phase_start = time.perf_counter()
                _update_run_phase(
                    db, run, phase="Sync cloud", progress_pct=92.0, owner_token=owner_token
                )
                try:
                    detail = _run_with_retry_timeout(
                        label=PHASE_SYNC_CLOUD,
                        fn=_sync_cloud_step,
                        retries=retries,
                        backoff_seconds=backoff,
                        timeout_seconds=timeout,
                        should_cancel=lambda: is_cancel_requested(run_id),
                    )
                    if detail.get("skipped"):
                        run_warnings.append(f"sync_cloud_skipped:{detail.get('reason')}")
                    phases = _upsert_phase(
                        phases,
                        {
                            "phase": PHASE_SYNC_CLOUD,
                            "duration_seconds": round(time.perf_counter() - phase_start, 2),
                            "status": "completed",
                            **detail,
                        },
                    )
                except GlobalUpdateCancelled:
                    raise
                except Exception as exc:
                    msg = f"Cloud sync failed: {exc}"
                    run_errors.append(msg)
                    phases = _upsert_phase(
                        phases,
                        {
                            "phase": PHASE_SYNC_CLOUD,
                            "duration_seconds": round(time.perf_counter() - phase_start, 2),
                            "status": "failed",
                            "error": str(exc),
                        },
                    )
                    logger.exception(msg)
                _persist_phases(db, run, phases)

            if is_cancel_requested(run_id):
                raise GlobalUpdateCancelled()

            _update_run_phase(
                db, run, phase="Generazione report", progress_pct=95.0, owner_token=owner_token
            )

            # Recompute counters from items for accurate resume totals.
            db.refresh(run)
            completed = sum(1 for item in run.items if item.status == "completed")
            failed = sum(1 for item in run.items if item.status == "failed")
            skipped = sum(1 for item in run.items if item.status == "skipped")
            total_slips = sum(int(item.slips_generated or 0) for item in run.items)

            run.combinations_completed = completed
            run.combinations_failed = failed
            run.combinations_skipped = skipped
            run.slips_generated = total_slips
            run.finished_at = datetime.now()
            run.duration_seconds = round(time.perf_counter() - started, 2)
            if run.started_at:
                run.duration_seconds = round(
                    (run.finished_at - run.started_at).total_seconds(), 2
                )

            hard_phase_failures = [
                p for p in phases if p.get("status") == "failed" and p.get("phase") != PHASE_COMBINATIONS
            ]
            if failed > 0 and completed > 0:
                run.status = "completed_with_errors"
            elif failed > 0 and completed == 0:
                run.status = "failed"
            elif hard_phase_failures and completed == 0 and failed == 0:
                run.status = "failed"
            elif hard_phase_failures:
                run.status = "completed_with_errors"
            else:
                run.status = "completed"

            run.current_phase = "Completato"
            run.progress_pct = 100.0
            run.cancel_requested = "false"
            run.errors_json = _json_dumps(run_errors)
            run.warnings_json = _json_dumps(run_warnings)

            import_status = get_import_status(db)
            report = {
                "run_id": run.id,
                "run_date": run.run_date.isoformat(),
                "origin": run.origin,
                "status": run.status,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "duration_seconds": run.duration_seconds,
                "resume_count": run.resume_count,
                "summary": {
                    "versions_processed": run.versions_processed,
                    "models_processed": run.models_processed,
                    "combinations_total": total_combos,
                    "combinations_completed": completed,
                    "combinations_failed": failed,
                    "combinations_skipped": skipped,
                    "fixtures_processed": run.fixtures_processed,
                    "slips_generated": total_slips,
                    "sync_cloud": run.sync_cloud == "true",
                    "live_publication": live_publication_report
                    or {
                        "config_status": public_cfg.status,
                        "config_warning": public_cfg.warning,
                        "public_model_version": public_cfg.model_version,
                        "public_model_name": public_cfg.model_name,
                    },
                    "import_status": {
                        "next_fixtures_imported_today": import_status[
                            "next_fixtures_imported_today"
                        ],
                        "next_fixtures_max_date": (
                            import_status["next_fixtures_max_date"].isoformat()
                            if import_status["next_fixtures_max_date"]
                            else None
                        ),
                    },
                },
                "phases": phases,
                "items": _run_to_read_dict(run)["items"],
                "errors": run_errors,
                "warnings": run_warnings,
            }
            phases = _upsert_phase(
                phases,
                {
                    "phase": PHASE_REPORT,
                    "status": "completed",
                    "duration_seconds": 0,
                },
            )
            run.phases_json = _json_dumps(phases)
            run.report_json = _json_dumps(report)
            db.commit()
    except GlobalUpdateCancelled:
        with SessionLocal() as db:
            run = get_run_by_id(db, run_id)
            if run is not None and run.status in RUNNING_STATUSES:
                _finalize_cancelled_run(db, run, reason="Run cancelled by user.")
        _cancel_requested.discard(run_id)
        _cancel_cache.pop(run_id, None)
    except Exception as exc:
        logger.exception("Global update run_id=%s crashed: %s", run_id, exc)
        try:
            from backend.src.app.observability.errors import capture_exception

            capture_exception(exc, context={"run_id": run_id, "component": "global_update"})
        except Exception:
            pass
        with SessionLocal() as db:
            run = get_run_by_id(db, run_id)
            if run is not None and run.status in RUNNING_STATUSES:
                _mark_interrupted(db, run, reason=f"Run crashed: {exc}")
    finally:
        _cancel_requested.discard(run_id)
        _cancel_cache.pop(run_id, None)
        if lock_acquired:
            with SessionLocal() as db:
                release_pipeline_lock(db, owner_token=owner_token)
        with _active_thread_lock:
            if _active_run_id == run_id:
                _active_run_id = None
        try:
            from backend.src.app.observability.notify import notify_global_update_finished

            with SessionLocal() as db:
                finished = get_run_by_id(db, run_id)
                if finished is not None and finished.status not in RUNNING_STATUSES:
                    notify_global_update_finished(finished)
        except Exception:
            logger.warning(
                "Failed to emit pipeline observability for run_id=%s",
                run_id,
                exc_info=True,
            )


def build_run_report(run: GlobalUpdateRun) -> dict[str, Any]:
    stored = _json_loads(run.report_json, None)
    if stored:
        return stored
    return {
        "run_id": run.id,
        "run_date": run.run_date.isoformat(),
        "origin": run.origin,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": run.duration_seconds,
        "summary": {
            "versions_processed": run.versions_processed,
            "models_processed": run.models_processed,
            "combinations_completed": run.combinations_completed,
            "combinations_failed": run.combinations_failed,
            "combinations_skipped": run.combinations_skipped,
            "fixtures_processed": run.fixtures_processed,
            "slips_generated": run.slips_generated,
        },
        "phases": _json_loads(run.phases_json, []),
        "items": _run_to_read_dict(run)["items"],
        "errors": _json_loads(run.errors_json, []),
        "warnings": _json_loads(run.warnings_json, []),
    }


def exit_code_for_run(run: GlobalUpdateRun | None, *, message: str = "") -> int:
    """Map run outcome to process exit codes for cron/workers.

    0 = completed or idempotent skip (already done today)
    1 = completed_with_errors
    2 = failed / interrupted
    3 = cancelled
    4 = busy (lock / already running)
    5 = configuration / nothing to run
    """
    if run is None:
        lower = message.lower()
        if "already running" in lower or "lock" in lower:
            return 4
        if "already completed today" in lower:
            return 0
        return 5
    status = run.status
    if status == "completed":
        return 0
    if status == "completed_with_errors":
        return 1
    if status == "cancelled":
        return 3
    if status in ("failed", "interrupted"):
        return 2
    if status in RUNNING_STATUSES:
        return 4
    return 5


def get_models_versions_results(db: Session, *, target_date: date | None = None) -> dict[str, Any]:
    """Aggregate persisted results for all model/version combinations."""
    from backend.src.app.models import BettingSlip, MatchPrediction

    ref_date = target_date or date.today()
    latest_run = get_latest_run(db)

    combinations = list_enabled_combinations()
    version_map: dict[str, list[dict[str, Any]]] = {}

    for combo in combinations:
        pred_count = db.scalar(
            select(func.count())
            .select_from(MatchPrediction)
            .where(
                MatchPrediction.model_version == combo.model_version,
                MatchPrediction.model_name == combo.model_name,
            )
        )
        slip_count = db.scalar(
            select(func.count())
            .select_from(BettingSlip)
            .where(
                BettingSlip.slip_date == ref_date,
                BettingSlip.model_version == combo.model_version,
                BettingSlip.model_name == combo.model_name,
            )
        )

        item_status = "completed"
        if latest_run:
            for item in latest_run.items:
                if (
                    item.model_version == combo.model_version
                    and item.model_name == combo.model_name
                ):
                    item_status = item.status
                    break

        version_map.setdefault(combo.model_version, []).append(
            {
                "model": combo.model_name,
                "status": item_status,
                "predictions_count": int(pred_count or 0),
                "slips_count": int(slip_count or 0),
                "data": {},
            }
        )

    return {
        "date": ref_date,
        "last_updated_at": latest_run.finished_at if latest_run else None,
        "last_run_id": latest_run.id if latest_run else None,
        "last_run_origin": latest_run.origin if latest_run else None,
        "versions": [
            {"version": version, "models": models}
            for version, models in sorted(version_map.items())
        ],
    }
