"""Persist and orchestrate probability calibration runs.

Uses OOS walk-forward predictions only. Never updates live/public model selection.
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
from backend.src.app.ml.model_versioning import (
    ACTIVE_MATCH_WINNER_VERSIONS,
    MODEL_VERSIONS,
    REPORTS_DIR,
)
from backend.src.app.ml.training.calibration import (
    CALIBRATION_METHODS,
    CalibrationConfig,
    CalibrationRunResult,
    calibration_result_to_dict,
    run_calibration_validation,
    write_calibration_report,
)
from backend.src.app.ml.training.walk_forward import WalkForwardConfig
from backend.src.app.schemas.calibration import (
    CalibrationResultRead,
    CalibrationRunListItem,
    CalibrationRunRead,
    CalibrationTriggerRequest,
)
from backend.src.app.services.background_job import (
    BackgroundJobCancelled,
    clear_cancel_state,
    get_active_thread_lock,
    is_cancel_requested,
    mark_cancel_requested,
    update_run_progress,
)
from backend.src.entity.calibration import CalibrationResult, CalibrationRun

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
    overrides: CalibrationTriggerRequest | None = None,
) -> CalibrationConfig:
    settings = settings or get_settings()
    request = overrides or CalibrationTriggerRequest()
    wf = WalkForwardConfig(
        mode=request.mode or settings.walk_forward_mode,  # type: ignore[arg-type]
        initial_train_days=request.initial_train_days or settings.walk_forward_initial_train_days,
        test_days=request.test_days or settings.walk_forward_test_days,
        step_days=request.step_days or settings.walk_forward_step_days,
        min_train_rows=request.min_train_rows or settings.walk_forward_min_train_rows,
        min_test_rows=request.min_test_rows or settings.walk_forward_min_test_rows,
        embargo_days=(
            request.embargo_days
            if request.embargo_days is not None
            else settings.walk_forward_embargo_days
        ),
        edge_threshold=(
            request.edge_threshold
            if request.edge_threshold is not None
            else settings.walk_forward_edge_threshold
        ),
        random_state=request.random_state or settings.walk_forward_random_state,
    )
    methods = tuple(request.methods) if request.methods else CALIBRATION_METHODS
    return CalibrationConfig(
        n_bins=request.n_bins or settings.calibration_n_bins,
        min_bin_samples=request.min_bin_samples or settings.calibration_min_bin_samples,
        min_calibrator_train_samples=(
            request.min_calibrator_train_samples or settings.calibration_min_calibrator_train_samples
        ),
        methods=methods,  # type: ignore[arg-type]
        walk_forward=wf,
    )


def resolve_versions(overrides: CalibrationTriggerRequest | None = None) -> tuple[str, ...]:
    """Default: live match-winner versions only (not archived v1–v3)."""
    if overrides and overrides.versions:
        unknown = [item for item in overrides.versions if item not in MODEL_VERSIONS]
        if unknown:
            raise ValueError(f"Versioni calibrazione sconosciute: {unknown}")
        return tuple(overrides.versions)
    return tuple(sorted(ACTIVE_MATCH_WINNER_VERSIONS))


def result_to_read(result: CalibrationResult) -> CalibrationResultRead:
    return CalibrationResultRead(
        id=result.id,
        run_id=result.run_id,
        model_version=result.model_version,
        model_name=result.model_name,
        dataset_path=result.dataset_path,
        date_min=result.date_min,
        date_max=result.date_max,
        oos_samples_total=result.oos_samples_total,
        aggregate=_json_loads(result.metrics_json, None),
        comparison=_json_loads(result.comparison_json, None),
        fold_outcomes=_json_loads(result.fold_outcomes_json, []),
        artifacts=_json_loads(result.artifacts_json, {}),
        leakage_flags=_json_loads(result.leakage_flags_json, []),
        skip_reason=result.skip_reason,
    )


def run_to_read(run: CalibrationRun, *, include_results: bool = True) -> CalibrationRunRead:
    results = [result_to_read(item) for item in (run.results if include_results else [])]
    return CalibrationRunRead(
        id=run.id,
        status=run.status,
        walk_forward_run_id=run.walk_forward_run_id,
        n_bins=run.n_bins,
        min_bin_samples=run.min_bin_samples,
        min_calibrator_train_samples=run.min_calibrator_train_samples,
        wf_mode=run.wf_mode,
        wf_initial_train_days=run.wf_initial_train_days,
        wf_test_days=run.wf_test_days,
        wf_step_days=run.wf_step_days,
        wf_min_train_rows=run.wf_min_train_rows,
        wf_min_test_rows=run.wf_min_test_rows,
        wf_embargo_days=run.wf_embargo_days,
        wf_edge_threshold=run.wf_edge_threshold,
        wf_random_state=run.wf_random_state,
        methods_requested=run.methods_requested,
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
        results=results,
    )


def run_to_list_item(run: CalibrationRun) -> CalibrationRunListItem:
    summary = _json_loads(run.summary_json, {}) or {}
    return CalibrationRunListItem(
        id=run.id,
        status=run.status,
        wf_mode=run.wf_mode,
        wf_initial_train_days=run.wf_initial_train_days,
        wf_test_days=run.wf_test_days,
        wf_step_days=run.wf_step_days,
        methods_requested=run.methods_requested,
        versions_requested=run.versions_requested,
        walk_forward_run_id=run.walk_forward_run_id,
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
        models_with_oos=int(summary.get("models_with_oos") or 0),
        oos_samples_total=int(summary.get("oos_samples_total") or run.progress_current or 0),
        leakage_flags_total=int(summary.get("leakage_flags_total") or 0),
    )


def get_calibration_run(db: Session, run_id: int) -> CalibrationRun | None:
    return db.scalar(
        select(CalibrationRun)
        .options(selectinload(CalibrationRun.results))
        .where(CalibrationRun.id == run_id)
    )


def get_latest_calibration_run(db: Session) -> CalibrationRun | None:
    return db.scalar(
        select(CalibrationRun)
        .options(selectinload(CalibrationRun.results))
        .order_by(CalibrationRun.id.desc())
        .limit(1)
    )


def list_calibration_runs(
    db: Session, *, limit: int = 20, offset: int = 0
) -> tuple[list[CalibrationRun], int]:
    total = db.scalar(select(func.count()).select_from(CalibrationRun)) or 0
    rows = list(
        db.scalars(
            select(CalibrationRun)
            .order_by(CalibrationRun.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, int(total)


def _create_run_row(
    db: Session,
    *,
    config: CalibrationConfig,
    versions: tuple[str, ...],
    methods: tuple[str, ...],
    origin: str,
    created_by: str,
    walk_forward_run_id: int | None,
) -> CalibrationRun:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    wf = config.walk_forward
    run = CalibrationRun(
        status="pending",
        walk_forward_run_id=walk_forward_run_id,
        n_bins=config.n_bins,
        min_bin_samples=config.min_bin_samples,
        min_calibrator_train_samples=config.min_calibrator_train_samples,
        wf_mode=wf.mode,
        wf_initial_train_days=wf.initial_train_days,
        wf_test_days=wf.test_days,
        wf_step_days=wf.step_days,
        wf_min_train_rows=wf.min_train_rows,
        wf_min_test_rows=wf.min_test_rows,
        wf_embargo_days=wf.embargo_days,
        wf_edge_threshold=wf.edge_threshold,
        wf_random_state=wf.random_state,
        methods_requested=",".join(methods),
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


def _persist_result(db: Session, run: CalibrationRun, result: CalibrationRunResult) -> None:
    payload = calibration_result_to_dict(result)
    report_path = write_calibration_report(result, run_id=run.id, reports_dir=REPORTS_DIR)
    for model in result.models:
        db.add(
            CalibrationResult(
                run_id=run.id,
                model_version=model.model_version,
                model_name=model.model_name,
                dataset_path=model.dataset_path,
                date_min=model.date_min,
                date_max=model.date_max,
                oos_samples_total=model.oos_samples_total,
                metrics_json=_json_dumps(
                    {key: value.to_dict() for key, value in model.aggregate.items()}
                ),
                comparison_json=_json_dumps(model.comparison),
                fold_outcomes_json=_json_dumps([item.to_dict() for item in model.fold_outcomes]),
                artifacts_json=_json_dumps(model.artifacts),
                leakage_flags_json=_json_dumps(model.leakage_flags),
                skip_reason=model.leakage_flags[0] if model.leakage_flags else None,
            )
        )
    summary = {
        **result.summary,
        "models_detail": [item.to_dict() for item in result.models],
        "config": payload["config"],
    }
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    started = run.started_at or finished
    run.finished_at = finished
    run.duration_seconds = max(0.0, (finished - started).total_seconds())
    run.report_path = str(report_path)
    run.summary_json = _json_dumps(summary)
    if result.summary.get("leakage_flags_total"):
        run.status = "completed_with_errors"
    else:
        run.status = "completed"
    run.error_message = None
    db.commit()


def _finalize_cancelled_run(db: Session, run: CalibrationRun, *, reason: str) -> None:
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = "cancelled"
    run.current_phase = "Annullato"
    run.finished_at = finished
    run.cancel_requested = "false"
    run.error_message = reason
    if run.started_at:
        run.duration_seconds = max(0.0, (finished - run.started_at).total_seconds())
    db.commit()


def _mark_interrupted_run(db: Session, run: CalibrationRun, *, reason: str) -> None:
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = "failed"
    run.current_phase = "Interrotto"
    run.finished_at = finished
    run.cancel_requested = "false"
    run.error_message = reason
    if run.started_at:
        run.duration_seconds = max(0.0, (finished - run.started_at).total_seconds())
    db.commit()


def reconcile_orphaned_calibration_runs(db: Session) -> int:
    global _active_run_id

    with _active_thread_lock:
        active_id = _active_run_id

    runs = db.scalars(
        select(CalibrationRun).where(CalibrationRun.status.in_(RUNNING_STATUSES))
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


def cancel_calibration_run(db: Session, run_id: int) -> tuple[bool, str]:
    global _active_run_id

    run = get_calibration_run(db, run_id)
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


def _read_cancel_flag(run_id: int) -> bool:
    with SessionLocal() as db:
        flag = db.scalar(
            select(CalibrationRun.cancel_requested).where(CalibrationRun.id == run_id)
        )
        return flag == "true"


def _persist_progress(
    run_id: int,
    *,
    phase: str,
    progress_current: int,
    progress_total: int,
) -> None:
    pct = (100.0 * progress_current / progress_total) if progress_total else 0.0
    with SessionLocal() as db:
        run = get_calibration_run(db, run_id)
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


def _mark_run_failed(db: Session, run: CalibrationRun, *, reason: str) -> None:
    finished = datetime.now(timezone.utc).replace(tzinfo=None)
    run.status = "failed"
    run.current_phase = "Fallita"
    run.finished_at = finished
    run.cancel_requested = "false"
    run.error_message = reason
    if run.started_at:
        run.duration_seconds = max(0.0, (finished - run.started_at).total_seconds())
    db.commit()


def _calibration_thread_entry(run_id: int) -> None:
    try:
        execute_calibration_run(run_id)
    except Exception:
        logger.exception("Calibration thread run_id=%s terminated uncaught", run_id)
        try:
            with SessionLocal() as db:
                run = get_calibration_run(db, run_id)
                if run is not None and run.status in RUNNING_STATUSES:
                    _mark_run_failed(
                        db,
                        run,
                        reason="Worker terminato in modo anomalo (controlla i log API).",
                    )
        except Exception:
            logger.exception("Failed to persist failure for calibration run_id=%s", run_id)


def execute_calibration_run(run_id: int) -> CalibrationRun:
    global _active_run_id
    logger.info(
        "Calibration worker started run_id=%s thread=%s",
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
            run = get_calibration_run(db, run_id)
            if run is None or run.status not in RUNNING_STATUSES:
                return
            update_run_progress(db, run, phase=phase, progress_pct=run.progress_pct or 0.0)

    try:
        with SessionLocal() as db:
            run = get_calibration_run(db, run_id)
            if run is None:
                raise ValueError(f"Calibration run {run_id} non trovata.")
            run.status = "running"
            run.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.current_phase = "Avvio"
            run.cancel_requested = "false"
            run.progress_pct = 0.0
            db.commit()

        with SessionLocal() as db:
            run = get_calibration_run(db, run_id)
            assert run is not None
            wf = WalkForwardConfig(
                mode=run.wf_mode,  # type: ignore[arg-type]
                initial_train_days=run.wf_initial_train_days,
                test_days=run.wf_test_days,
                step_days=run.wf_step_days,
                min_train_rows=run.wf_min_train_rows,
                min_test_rows=run.wf_min_test_rows,
                embargo_days=run.wf_embargo_days,
                edge_threshold=run.wf_edge_threshold,
                random_state=run.wf_random_state,
            )
            config = CalibrationConfig(
                n_bins=run.n_bins,
                min_bin_samples=run.min_bin_samples,
                min_calibrator_train_samples=run.min_calibrator_train_samples,
                methods=tuple(  # type: ignore[arg-type]
                    part.strip()
                    for part in run.methods_requested.split(",")
                    if part.strip()
                ),
                walk_forward=wf,
            )
            versions = tuple(
                part.strip() for part in run.versions_requested.split(",") if part.strip()
            )
            result = run_calibration_validation(
                config,
                versions=versions,
                walk_forward_run_id=run.walk_forward_run_id,
                run_id=run.id,
                persist_artifacts=True,
                progress_callback=on_progress,
                prepare_progress_callback=on_prepare,
                should_cancel=should_cancel,
            )
            _persist_result(db, run, result)
            run.current_phase = "Completato"
            run.progress_pct = 100.0
            db.commit()
            db.refresh(run)
            logger.info("Calibration worker completed run_id=%s status=%s", run_id, run.status)
            return run
    except BackgroundJobCancelled:
        logger.info("Calibration run_id=%s cancelled", run_id)
        with SessionLocal() as db:
            run = get_calibration_run(db, run_id)
            if run is not None:
                _finalize_cancelled_run(db, run, reason="Run annullata dall'utente.")
                return run
        raise
    except Exception as exc:
        logger.exception("Calibration run_id=%s failed: %s", run_id, exc)
        with SessionLocal() as db:
            run = get_calibration_run(db, run_id)
            if run is not None:
                _mark_run_failed(db, run, reason=str(exc))
                return run
        raise
    finally:
        clear_cancel_state(run_id)
        with _active_thread_lock:
            if _active_run_id == run_id:
                _active_run_id = None


def start_calibration_run(
    db: Session,
    *,
    request: CalibrationTriggerRequest | None = None,
    settings: Settings | None = None,
    origin: str = "manual",
    created_by: str = "api",
    blocking: bool | None = None,
) -> tuple[CalibrationRun, bool, str]:
    settings = settings or get_settings()
    request = request or CalibrationTriggerRequest()
    config = config_from_settings(settings, request)
    config.validate()
    versions = resolve_versions(request)
    methods = config.methods

    existing = db.scalar(
        select(CalibrationRun)
        .where(CalibrationRun.status.in_(RUNNING_STATUSES))
        .order_by(CalibrationRun.id.desc())
        .limit(1)
    )
    if existing is not None:
        loaded = get_calibration_run(db, existing.id)
        assert loaded is not None
        return loaded, False, f"Calibrazione già in corso (run_id={existing.id})."

    run = _create_run_row(
        db,
        config=config,
        versions=versions,
        methods=methods,
        origin=origin,
        created_by=created_by,
        walk_forward_run_id=request.walk_forward_run_id,
    )
    should_block = request.blocking if blocking is None else blocking
    if should_block:
        executed = execute_calibration_run(run.id)
        db.expire_all()
        refreshed = get_calibration_run(db, executed.id)
        assert refreshed is not None
        return refreshed, True, "Calibrazione completata."

    thread = threading.Thread(
        target=_calibration_thread_entry,
        args=(run.id,),
        name=f"calibration-{run.id}",
        daemon=True,
    )
    thread.start()
    logger.info("Calibration background thread started run_id=%s", run.id)
    refreshed = get_calibration_run(db, run.id)
    assert refreshed is not None
    return refreshed, True, "Calibrazione avviata in background."
