"""Persist and orchestrate walk-forward validation runs.

Results are stored separately from holdout ``baseline_*_metrics.json`` and never
update the live/public model selection.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.model_versioning import REPORTS_DIR
from backend.src.app.ml.training.walk_forward_markets import (
    ACTIVE_WALK_FORWARD_MARKET_VERSIONS,
    ALL_WALK_FORWARD_VERSIONS,
)
from backend.src.app.ml.training.walk_forward import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_INITIAL_TRAIN_DAYS,
    DEFAULT_MIN_TEST_ROWS,
    DEFAULT_MIN_TRAIN_ROWS,
    DEFAULT_STEP_DAYS,
    DEFAULT_TEST_DAYS,
    WalkForwardConfig,
    WalkForwardRunResult,
    run_walk_forward_validation,
    walk_forward_result_to_dict,
    write_walk_forward_report,
)
from backend.src.app.schemas.walk_forward import (
    WalkForwardFoldRead,
    WalkForwardGlobalUpdateSummary,
    WalkForwardRunListItem,
    WalkForwardRunRead,
    WalkForwardTriggerRequest,
)
from backend.src.app.services.background_job import (
    BackgroundJobCancelled,
    clear_cancel_state,
    get_active_thread_lock,
    is_cancel_requested,
    mark_cancel_requested,
    update_run_progress,
)
from backend.src.entity.walk_forward import WalkForwardFold, WalkForwardRun

logger = logging.getLogger(__name__)

_active_thread_lock = get_active_thread_lock()
_active_run_id: int | None = None
RUNNING_STATUSES = ("pending", "running")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def config_from_settings(
    settings: Settings | None = None,
    overrides: WalkForwardTriggerRequest | None = None,
) -> WalkForwardConfig:
    settings = settings or get_settings()
    mode = overrides.mode if overrides else settings.walk_forward_mode
    return WalkForwardConfig(
        mode=mode,  # type: ignore[arg-type]
        initial_train_days=(
            overrides.initial_train_days
            if overrides
            else settings.walk_forward_initial_train_days
        ),
        test_days=overrides.test_days if overrides else settings.walk_forward_test_days,
        step_days=overrides.step_days if overrides else settings.walk_forward_step_days,
        min_train_rows=(
            overrides.min_train_rows if overrides else settings.walk_forward_min_train_rows
        ),
        min_test_rows=(
            overrides.min_test_rows if overrides else settings.walk_forward_min_test_rows
        ),
        embargo_days=(
            overrides.embargo_days if overrides else settings.walk_forward_embargo_days
        ),
        edge_threshold=(
            overrides.edge_threshold if overrides else settings.walk_forward_edge_threshold
        ),
        random_state=(
            overrides.random_state if overrides else settings.walk_forward_random_state
        ),
    )


def resolve_versions(overrides: WalkForwardTriggerRequest | None = None) -> tuple[str, ...]:
    """Versions/markets included in a new walk-forward run.

    Default is every currently **active market** (``ACTIVE_WALK_FORWARD_MARKET_VERSIONS``:
    live match-winner + first_set_winner + over_under_games), not every archived
    key in ``MODEL_VERSIONS``. Pass ``versions=`` explicitly to backtest archived
    match-winner tags (v1–v3) or to scope a run to a single market.
    """
    if overrides and overrides.versions:
        unknown = [item for item in overrides.versions if item not in ALL_WALK_FORWARD_VERSIONS]
        if unknown:
            raise ValueError(f"Versioni walk-forward sconosciute: {unknown}")
        return tuple(overrides.versions)
    return ACTIVE_WALK_FORWARD_MARKET_VERSIONS


def fold_to_read(fold: WalkForwardFold) -> WalkForwardFoldRead:
    return WalkForwardFoldRead(
        id=fold.id,
        run_id=fold.run_id,
        fold_index=fold.fold_index,
        model_version=fold.model_version,
        model_name=fold.model_name,
        dataset_path=fold.dataset_path,
        status=fold.status,
        train_start=fold.train_start,
        train_end=fold.train_end,
        test_start=fold.test_start,
        test_end=fold.test_end,
        train_rows=fold.train_rows,
        test_rows=fold.test_rows,
        feature_set=_json_loads(fold.feature_set_json, []),
        metrics=_json_loads(fold.metrics_json, None),
        market_benchmark=_json_loads(fold.market_benchmark_json, None),
        coverage=_json_loads(fold.coverage_json, None),
        leakage_flags=_json_loads(fold.leakage_flags_json, []),
        skip_reason=fold.skip_reason,
    )


def run_to_read(run: WalkForwardRun, *, include_folds: bool = True) -> WalkForwardRunRead:
    folds = [fold_to_read(item) for item in (run.folds if include_folds else [])]
    return WalkForwardRunRead(
        id=run.id,
        status=run.status,
        mode=run.mode,
        initial_train_days=run.initial_train_days,
        test_days=run.test_days,
        step_days=run.step_days,
        min_train_rows=run.min_train_rows,
        min_test_rows=run.min_test_rows,
        embargo_days=run.embargo_days,
        edge_threshold=run.edge_threshold,
        random_state=run.random_state,
        versions_requested=run.versions_requested,
        origin=run.origin,
        current_phase=run.current_phase,
        progress_pct=run.progress_pct,
        progress_current=run.progress_current,
        progress_total=run.progress_total,
        cancel_requested=run.cancel_requested == "true",
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=run.duration_seconds,
        report_path=run.report_path,
        summary=_json_loads(run.summary_json, None),
        error_message=run.error_message,
        created_at=run.created_at,
        created_by=run.created_by,
        folds=folds,
    )


def run_to_list_item(run: WalkForwardRun) -> WalkForwardRunListItem:
    summary = _json_loads(run.summary_json, {}) or {}
    return WalkForwardRunListItem(
        id=run.id,
        status=run.status,
        mode=run.mode,
        initial_train_days=run.initial_train_days,
        test_days=run.test_days,
        step_days=run.step_days,
        versions_requested=run.versions_requested,
        origin=run.origin,
        current_phase=run.current_phase,
        progress_pct=run.progress_pct,
        progress_current=run.progress_current,
        progress_total=run.progress_total,
        cancel_requested=run.cancel_requested == "true",
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=run.duration_seconds,
        created_at=run.created_at,
        created_by=run.created_by,
        folds_completed=int(summary.get("folds_completed") or run.progress_current or 0),
        folds_skipped=int(summary.get("folds_skipped") or 0),
        folds_errors=int(summary.get("folds_errors") or 0),
        leakage_flags_total=int(summary.get("leakage_flags_total") or 0),
    )


def get_walk_forward_run(db: Session, run_id: int) -> WalkForwardRun | None:
    return db.scalar(
        select(WalkForwardRun)
        .options(selectinload(WalkForwardRun.folds))
        .where(WalkForwardRun.id == run_id)
    )


def get_latest_walk_forward_run(db: Session) -> WalkForwardRun | None:
    return db.scalar(
        select(WalkForwardRun)
        .options(selectinload(WalkForwardRun.folds))
        .order_by(WalkForwardRun.id.desc())
        .limit(1)
    )


def get_latest_completed_walk_forward_run(db: Session) -> WalkForwardRun | None:
    return db.scalar(
        select(WalkForwardRun)
        .options(selectinload(WalkForwardRun.folds))
        .where(WalkForwardRun.status.in_(("completed", "completed_with_errors")))
        .order_by(WalkForwardRun.id.desc())
        .limit(1)
    )


def list_walk_forward_runs(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[list[WalkForwardRun], int]:
    total = db.scalar(select(func.count()).select_from(WalkForwardRun)) or 0
    rows = list(
        db.scalars(
            select(WalkForwardRun)
            .order_by(WalkForwardRun.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, int(total)


def build_global_update_walk_forward_summary(db: Session) -> dict[str, Any]:
    """Embeddable observability block for global-update reports."""
    latest = get_latest_walk_forward_run(db)
    if latest is None:
        return WalkForwardGlobalUpdateSummary(available=False).model_dump(mode="json")
    item = run_to_list_item(latest)
    return WalkForwardGlobalUpdateSummary(
        available=True,
        latest_run_id=item.id,
        status=item.status,
        mode=item.mode,
        finished_at=item.finished_at,
        folds_completed=item.folds_completed,
        folds_skipped=item.folds_skipped,
        folds_errors=item.folds_errors,
        leakage_flags_total=item.leakage_flags_total,
    ).model_dump(mode="json")


def _create_run_row(
    db: Session,
    *,
    config: WalkForwardConfig,
    versions: tuple[str, ...],
    origin: str,
    created_by: str,
) -> WalkForwardRun:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    run = WalkForwardRun(
        status="pending",
        mode=config.mode,
        initial_train_days=config.initial_train_days,
        test_days=config.test_days,
        step_days=config.step_days,
        min_train_rows=config.min_train_rows,
        min_test_rows=config.min_test_rows,
        embargo_days=config.embargo_days,
        edge_threshold=config.edge_threshold,
        random_state=config.random_state,
        versions_requested=",".join(versions),
        origin=origin,
        current_phase="In coda",
        progress_pct=0.0,
        progress_current=0,
        progress_total=0,
        cancel_requested="false",
        created_at=now,
        created_by=created_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _persist_result(db: Session, run: WalkForwardRun, result: WalkForwardRunResult) -> None:
    payload = walk_forward_result_to_dict(result)
    report_path = write_walk_forward_report(
        result, reports_dir=REPORTS_DIR, run_id=run.id
    )
    for version in result.versions:
        for outcome in version.folds:
            db.add(
                WalkForwardFold(
                    run_id=run.id,
                    fold_index=outcome.fold.fold_index,
                    model_version=outcome.model_version,
                    model_name=outcome.model_name,
                    dataset_path=outcome.dataset_path,
                    status=outcome.status,
                    train_start=outcome.fold.train_start,
                    train_end=outcome.fold.train_end,
                    test_start=outcome.fold.test_start,
                    test_end=outcome.fold.test_end,
                    train_rows=outcome.train_rows,
                    test_rows=outcome.test_rows,
                    feature_set_json=_json_dumps(outcome.feature_set),
                    metrics_json=_json_dumps(outcome.metrics) if outcome.metrics else None,
                    market_benchmark_json=(
                        _json_dumps(outcome.market_benchmark)
                        if outcome.market_benchmark
                        else None
                    ),
                    coverage_json=_json_dumps(outcome.coverage),
                    leakage_flags_json=_json_dumps(outcome.leakage_flags),
                    skip_reason=outcome.skip_reason,
                )
            )
    summary = {
        **result.summary,
        "versions_detail": [
            {
                "model_version": version.model_version,
                "dataset_path": version.dataset_path,
                "dataset_rows": version.dataset_rows,
                "date_min": version.date_min,
                "date_max": version.date_max,
                "feature_set": version.feature_set,
                "aggregate_metrics": version.aggregate_metrics,
                "holdout_comparison": version.holdout_comparison,
                "coverage": version.coverage,
                "leakage_flags": version.leakage_flags,
            }
            for version in result.versions
        ],
        "config": payload["config"],
    }
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    started = run.started_at or finished
    run.finished_at = finished
    run.duration_seconds = max(0.0, (finished - started).total_seconds())
    run.report_path = str(report_path)
    run.summary_json = _json_dumps(summary)
    if result.summary.get("folds_errors"):
        run.status = "completed_with_errors"
    else:
        run.status = "completed"
    run.error_message = None
    db.commit()


def _finalize_cancelled_run(db: Session, run: WalkForwardRun, *, reason: str) -> None:
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = "cancelled"
    run.current_phase = "Annullato"
    run.finished_at = finished
    run.cancel_requested = "false"
    run.error_message = reason
    if run.started_at:
        run.duration_seconds = max(0.0, (finished - run.started_at).total_seconds())
    db.commit()


def _mark_interrupted_run(db: Session, run: WalkForwardRun, *, reason: str) -> None:
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = "failed"
    run.current_phase = "Interrotto"
    run.finished_at = finished
    run.cancel_requested = "false"
    run.error_message = reason
    if run.started_at:
        run.duration_seconds = max(0.0, (finished - run.started_at).total_seconds())
    db.commit()


def reconcile_orphaned_walk_forward_runs(db: Session) -> int:
    """Mark process-dead active runs as failed so new runs can start."""
    global _active_run_id

    with _active_thread_lock:
        active_id = _active_run_id

    runs = db.scalars(
        select(WalkForwardRun).where(WalkForwardRun.status.in_(RUNNING_STATUSES))
    ).all()
    reconciled = 0
    for run in runs:
        if active_id == run.id:
            continue
        _mark_interrupted_run(
            db,
            run,
            reason="Run interrotta (backend riavviato o worker perso).",
        )
        clear_cancel_state(run.id)
        reconciled += 1
    return reconciled


def cancel_walk_forward_run(db: Session, run_id: int) -> tuple[bool, str]:
    global _active_run_id

    run = get_walk_forward_run(db, run_id)
    if run is None:
        return False, f"Run {run_id} non trovata."
    if run.status not in RUNNING_STATUSES:
        return False, f"Run {run_id} non attiva (status={run.status})."

    run.cancel_requested = "true"
    db.commit()
    mark_cancel_requested(run_id)

    with _active_thread_lock:
        thread_active = _active_run_id == run_id

    if thread_active:
        return True, "Annullamento richiesto."

    _finalize_cancelled_run(db, run, reason="Run annullata dall'utente.")
    clear_cancel_state(run_id)
    with _active_thread_lock:
        if _active_run_id == run_id:
            _active_run_id = None
    return True, "Run annullata."


def _persist_progress(
    run_id: int,
    *,
    phase: str,
    progress_current: int,
    progress_total: int,
) -> None:
    pct = (100.0 * progress_current / progress_total) if progress_total else 0.0
    with SessionLocal() as db:
        run = get_walk_forward_run(db, run_id)
        if run is None or run.status not in RUNNING_STATUSES:
            return
        update_run_progress(
            db,
            run,
            phase=phase,
            progress_pct=pct,
            progress_current=progress_current,
            progress_total=progress_total,
        )


def _mark_run_failed(db: Session, run: WalkForwardRun, *, reason: str) -> None:
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = "failed"
    run.current_phase = "Fallita"
    run.finished_at = finished
    run.cancel_requested = "false"
    run.error_message = reason
    if run.started_at:
        run.duration_seconds = max(0.0, (finished - run.started_at).total_seconds())
    db.commit()


def _walk_forward_thread_entry(run_id: int) -> None:
    try:
        execute_walk_forward_run(run_id)
    except Exception:
        logger.exception("Walk-forward thread run_id=%s terminated uncaught", run_id)
        try:
            with SessionLocal() as db:
                run = get_walk_forward_run(db, run_id)
                if run is not None and run.status in RUNNING_STATUSES:
                    _mark_run_failed(
                        db,
                        run,
                        reason="Worker terminato in modo anomalo (controlla i log API).",
                    )
        except Exception:
            logger.exception("Failed to persist failure for walk-forward run_id=%s", run_id)


def execute_walk_forward_run(run_id: int) -> WalkForwardRun:
    """Blocking execution used by CLI / background worker."""
    global _active_run_id
    logger.info(
        "Walk-forward worker started run_id=%s thread=%s",
        run_id,
        threading.current_thread().name,
    )

    with _active_thread_lock:
        _active_run_id = run_id

    def should_cancel() -> bool:
        return is_cancel_requested(
            run_id,
            db_check=lambda: _read_cancel_flag(run_id),
        )

    def on_progress(phase: str, completed: int, total: int) -> None:
        _persist_progress(run_id, phase=phase, progress_current=completed, progress_total=total)

    def on_prepare(phase: str) -> None:
        with SessionLocal() as db:
            run = get_walk_forward_run(db, run_id)
            if run is None or run.status not in RUNNING_STATUSES:
                return
            update_run_progress(db, run, phase=phase, progress_pct=run.progress_pct or 0.0)

    try:
        with SessionLocal() as db:
            run = get_walk_forward_run(db, run_id)
            if run is None:
                raise ValueError(f"Walk-forward run {run_id} non trovata.")
            run.status = "running"
            run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.current_phase = "Avvio"
            run.cancel_requested = "false"
            run.progress_pct = 0.0
            db.commit()

        with SessionLocal() as db:
            run = get_walk_forward_run(db, run_id)
            assert run is not None
            config = WalkForwardConfig(
                mode=run.mode,  # type: ignore[arg-type]
                initial_train_days=run.initial_train_days,
                test_days=run.test_days,
                step_days=run.step_days,
                min_train_rows=run.min_train_rows,
                min_test_rows=run.min_test_rows,
                embargo_days=run.embargo_days,
                edge_threshold=run.edge_threshold,
                random_state=run.random_state,
            )
            versions = tuple(
                part.strip()
                for part in run.versions_requested.split(",")
                if part.strip()
            )
            result = run_walk_forward_validation(
                config,
                versions=versions,
                db=db,
                progress_callback=on_progress,
                prepare_progress_callback=on_prepare,
                should_cancel=should_cancel,
            )
            _persist_result(db, run, result)
            run.current_phase = "Completato"
            run.progress_pct = 100.0
            db.commit()
            db.refresh(run)
            logger.info("Walk-forward worker completed run_id=%s status=%s", run_id, run.status)
            return run
    except BackgroundJobCancelled:
        logger.info("Walk-forward run_id=%s cancelled", run_id)
        with SessionLocal() as db:
            run = get_walk_forward_run(db, run_id)
            if run is not None:
                _finalize_cancelled_run(db, run, reason="Run annullata dall'utente.")
                return run
        raise
    except Exception as exc:
        logger.exception("Walk-forward run_id=%s failed: %s", run_id, exc)
        with SessionLocal() as db:
            run = get_walk_forward_run(db, run_id)
            if run is not None:
                _mark_run_failed(db, run, reason=str(exc))
                return run
        raise
    finally:
        clear_cancel_state(run_id)
        with _active_thread_lock:
            if _active_run_id == run_id:
                _active_run_id = None


def _read_cancel_flag(run_id: int) -> bool:
    with SessionLocal() as db:
        flag = db.scalar(
            select(WalkForwardRun.cancel_requested).where(WalkForwardRun.id == run_id)
        )
        return flag == "true"


def start_walk_forward_run(
    db: Session,
    *,
    request: WalkForwardTriggerRequest | None = None,
    settings: Settings | None = None,
    origin: str = "manual",
    created_by: str = "api",
    blocking: bool | None = None,
) -> tuple[WalkForwardRun, bool, str]:
    """Create a run and optionally execute it in a background thread."""
    settings = settings or get_settings()
    request = request or WalkForwardTriggerRequest()
    config = config_from_settings(settings, request)
    config.validate()
    versions = resolve_versions(request)

    existing = db.scalar(
        select(WalkForwardRun)
        .where(WalkForwardRun.status.in_(RUNNING_STATUSES))
        .order_by(WalkForwardRun.id.desc())
        .limit(1)
    )
    if existing is not None:
        loaded = get_walk_forward_run(db, existing.id)
        assert loaded is not None
        return loaded, False, f"Walk-forward già in corso (run_id={existing.id})."

    run = _create_run_row(
        db,
        config=config,
        versions=versions,
        origin=origin,
        created_by=created_by,
    )
    should_block = request.blocking if blocking is None else blocking
    if should_block:
        executed = execute_walk_forward_run(run.id)
        db.expire_all()
        refreshed = get_walk_forward_run(db, executed.id)
        assert refreshed is not None
        return refreshed, True, "Walk-forward completato."

    thread = threading.Thread(
        target=_walk_forward_thread_entry,
        args=(run.id,),
        name=f"walk-forward-{run.id}",
        daemon=True,
    )
    thread.start()
    logger.info("Walk-forward background thread started run_id=%s", run.id)
    refreshed = get_walk_forward_run(db, run.id)
    assert refreshed is not None
    return refreshed, True, "Walk-forward avviato in background."


def maybe_run_walk_forward_for_global_update(db: Session, settings: Settings) -> dict[str, Any]:
    """Optional phase for global update: run WF only when explicitly enabled."""
    if not settings.walk_forward_in_global_update:
        summary = build_global_update_walk_forward_summary(db)
        summary["executed"] = False
        summary["reason"] = "WALK_FORWARD_IN_GLOBAL_UPDATE=false (solo osservabilità)."
        return summary

    run, started, message = start_walk_forward_run(
        db,
        settings=settings,
        origin="global_update",
        created_by="global_update",
        blocking=True,
    )
    payload = build_global_update_walk_forward_summary(db)
    payload["executed"] = started
    payload["message"] = message
    payload["run_id"] = run.id
    payload["status"] = run.status
    return payload


# Defaults re-exported for docs/tests.
DEFAULTS = {
    "initial_train_days": DEFAULT_INITIAL_TRAIN_DAYS,
    "test_days": DEFAULT_TEST_DAYS,
    "step_days": DEFAULT_STEP_DAYS,
    "min_train_rows": DEFAULT_MIN_TRAIN_ROWS,
    "min_test_rows": DEFAULT_MIN_TEST_ROWS,
    "embargo_days": DEFAULT_EMBARGO_DAYS,
}
