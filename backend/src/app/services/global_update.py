"""Discover enabled model/version combinations and run the global update orchestrator."""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

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
from backend.src.app.services.predictions import list_next_fixtures
from backend.src.entity.global_update_run import GlobalUpdateRun, GlobalUpdateRunItem
from backend.src.service.import_fixtures import run_daily_fixture_import
from backend.src.service.import_next_fixtures import run_daily_next_fixture_import

logger = logging.getLogger(__name__)


MODEL_NAMES = ("logistic_regression", "random_forest")
RUNNING_STATUSES = ("pending", "running")
GlobalUpdateOrigin = Literal["manual", "cron"]

_active_thread_lock = threading.Lock()
_active_run_id: int | None = None
_cancel_requested: set[int] = set()


class GlobalUpdateCancelled(Exception):
    """Raised when a run is cancelled cooperatively."""


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
    return run_id in _cancel_requested


def _finalize_cancelled_run(db: Session, run: GlobalUpdateRun, *, reason: str) -> None:
    now = datetime.now()
    run.status = "cancelled"
    run.current_phase = "Annullato"
    run.finished_at = now
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


def reconcile_orphaned_runs(db: Session) -> int:
    """Mark in-memory-dead runs as cancelled after a process restart."""
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
        _finalize_cancelled_run(
            db,
            run,
            reason="Run interrupted (backend restarted or worker lost).",
        )
        _cancel_requested.discard(run.id)
        reconciled += 1
    return reconciled


def cancel_global_update(db: Session, run_id: int) -> tuple[bool, str]:
    global _active_run_id

    run = get_run_by_id(db, run_id)
    if run is None:
        return False, f"Run {run_id} not found."
    if run.status not in RUNNING_STATUSES:
        return False, f"Run {run_id} is not active (status={run.status})."

    _cancel_requested.add(run_id)
    with _active_thread_lock:
        thread_active = _active_run_id == run_id

    if not thread_active:
        _finalize_cancelled_run(db, run, reason="Run cancelled by user.")
        _cancel_requested.discard(run_id)
        with _active_thread_lock:
            if _active_run_id == run_id:
                _active_run_id = None
        return True, "Run cancelled."

    return True, "Cancellation requested."


def _combo_progress_pct(index: int, total_combos: int, fixture_index: int, fixture_total: int) -> float:
    combo_span = 75.0 / max(total_combos, 1)
    combo_start = 10.0 + index * combo_span
    if fixture_total <= 0:
        return round(combo_start + combo_span, 2)
    fixture_ratio = min(max(fixture_index / fixture_total, 0.0), 1.0)
    return round(combo_start + fixture_ratio * combo_span, 2)


def start_global_update(
    db: Session,
    *,
    origin: GlobalUpdateOrigin = "manual",
    force: bool = False,
    days_forward: int = 10,
    days_back_fixtures: int = 3,
) -> tuple[GlobalUpdateRun | None, str]:
    """Create a run and start background processing. Returns (run, message)."""
    global _active_run_id

    with _active_thread_lock:
        if _active_run_id is not None:
            existing = get_run_by_id(db, _active_run_id)
            if existing and existing.status in RUNNING_STATUSES:
                return None, f"Global update already running (run_id={_active_run_id})."

        running = _get_running_run(db)
        if running is not None:
            _active_run_id = running.id
            return None, f"Global update already running (run_id={running.id})."

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

        thread = threading.Thread(
            target=_execute_global_update,
            args=(run.id, days_forward, days_back_fixtures),
            name=f"global-update-{run.id}",
            daemon=True,
        )
        _active_run_id = run.id
        thread.start()
        return run, "Global update started."


def _update_run_phase(
    db: Session,
    run: GlobalUpdateRun,
    *,
    phase: str,
    progress_pct: float | None = None,
) -> None:
    run.current_phase = phase
    if progress_pct is not None:
        run.progress_pct = progress_pct
    db.commit()


def _execute_global_update(run_id: int, days_forward: int, days_back_fixtures: int) -> None:
    global _active_run_id
    started = time.perf_counter()
    phases: list[dict[str, Any]] = []
    run_errors: list[str] = []
    run_warnings: list[str] = []

    try:
        with SessionLocal() as db:
            run = get_run_by_id(db, run_id)
            if run is None:
                return

            run.status = "running"
            run.started_at = datetime.now()
            _update_run_phase(db, run, phase="Preparazione", progress_pct=1.0)

            combinations = [
                ModelCombination(item.model_version, item.model_name)  # type: ignore[arg-type]
                for item in run.items
            ]
            unique_versions = {combo.model_version for combo in combinations}
            unique_models = {combo.model_name for combo in combinations}
            run.versions_processed = len(unique_versions)
            run.models_processed = len(unique_models)
            db.commit()

            # Phase: import fixtures (shared)
            phase_start = time.perf_counter()
            _update_run_phase(db, run, phase="Recupero partite disputate", progress_pct=5.0)
            try:
                run_daily_fixture_import(
                    days_back_start=max(days_back_fixtures, 1),
                    days_back_stop=0,
                )
                purged = purge_future_incomplete_fixtures(db)
                today_for_state = date.today()
                date_from = today_for_state - timedelta(days=max(days_back_fixtures, 1))
                last_match_date = db.scalar(
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
                phases.append(
                    {
                        "phase": "import_fixtures",
                        "duration_seconds": round(time.perf_counter() - phase_start, 2),
                        "status": "completed",
                        "purged_future_incomplete": purged,
                        "last_match_date": (
                            last_match_date.isoformat() if last_match_date else None
                        ),
                    }
                )
            except Exception as exc:
                msg = f"Fixture import failed: {exc}"
                run_errors.append(msg)
                phases.append(
                    {
                        "phase": "import_fixtures",
                        "duration_seconds": round(time.perf_counter() - phase_start, 2),
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                logger.exception(msg)

            # Phase: import next fixtures (shared, once)
            phase_start = time.perf_counter()
            _update_run_phase(db, run, phase="Recupero prossime partite", progress_pct=10.0)
            fixtures_count = 0
            try:
                next_summary = run_daily_next_fixture_import(
                    days_forward=days_forward,
                    days_back=days_back_fixtures,
                )
                fixtures_count = int(next_summary.get("inserted", 0) or 0)
                phases.append(
                    {
                        "phase": "import_next_fixtures",
                        "duration_seconds": round(time.perf_counter() - phase_start, 2),
                        "status": "completed",
                        "fixtures_imported": fixtures_count,
                    }
                )
            except Exception as exc:
                msg = f"Next fixture import failed: {exc}"
                run_errors.append(msg)
                phases.append(
                    {
                        "phase": "import_next_fixtures",
                        "duration_seconds": round(time.perf_counter() - phase_start, 2),
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                logger.exception(msg)

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
                len(fixtures) for fixtures in upcoming_fixtures_by_version.values()
            ) if upcoming_fixtures_by_version else 0
            db.commit()

            total_combos = len(combinations)
            completed = 0
            failed = 0
            skipped = 0
            total_slips = 0
            live_publication_report: dict[str, Any] | None = None

            public_cfg = resolve_public_model_config()
            if public_cfg.warning:
                run_warnings.append(public_cfg.warning)
            if public_cfg.is_ready:
                public_in_run = any(
                    combo.model_version == public_cfg.model_version
                    and combo.model_name == public_cfg.model_name
                    for combo in combinations
                )
                if not public_in_run:
                    run_warnings.append(
                        "Live publication enabled but public model "
                        f"{public_cfg.model_version}/{public_cfg.model_name} "
                        "is not among enabled combinations for this run "
                        "(missing artifact?). No tips published."
                    )

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

                progress = _combo_progress_pct(index, total_combos, 0, 1)
                phase_label = f"Elaborazione {combo.model_version} / {combo.model_name}"
                _update_run_phase(db, run, phase=phase_label, progress_pct=progress)

                item.status = "running"
                item.started_at = datetime.now()
                db.commit()

                item_start = time.perf_counter()
                item_warnings: list[str] = []
                predictions_count = 0
                slips_count = 0
                live_publication_summary: dict[str, Any] | None = None

                try:
                    fixtures = upcoming_fixtures_by_version.get(combo.model_version, [])
                    if fixtures:
                        def _progress_callback(fixture_index: int, fixture_total: int) -> None:
                            if (
                                fixture_total > 0
                                and fixture_index not in (1, fixture_total)
                                and fixture_index % 5 != 0
                            ):
                                return
                            pct = _combo_progress_pct(index, total_combos, fixture_index, fixture_total)
                            _update_run_phase(
                                db,
                                run,
                                phase=phase_label,
                                progress_pct=pct,
                            )

                        predictions = predict_upcoming_fixtures(
                            db=db,
                            fixtures=fixtures,
                            model_version=combo.model_version,
                            model_name=combo.model_name,
                            persist=True,
                            progress_callback=_progress_callback,
                            should_cancel=lambda: is_cancel_requested(run_id),
                        )
                        predictions_count = sum(
                            1 for p in predictions if p.get("prob_player_1_win") is not None
                        )
                    else:
                        item_warnings.append("no_upcoming_fixtures")

                    # Generate betting slips for today
                    try:
                        _update_run_phase(
                            db,
                            run,
                            phase=f"{phase_label} · schedine",
                            progress_pct=_combo_progress_pct(index, total_combos, 1, 1),
                        )
                        daily = get_daily_betting_slips(
                            db=db,
                            slip_date=today,
                            model_version=combo.model_version,
                            model_name=combo.model_name,
                            regenerate=True,
                        )
                        slips_count = len(daily.slips)
                        item_warnings.extend(daily.warnings)
                    except Exception as slip_exc:
                        db.rollback()
                        item_warnings.append(f"betting_slips:{slip_exc}")

                    # Live publication: only the configured public model combination.
                    if is_public_combination(combo.model_version, combo.model_name):
                        _update_run_phase(
                            db,
                            run,
                            phase=f"{phase_label} · pubblicazione live",
                            progress_pct=_combo_progress_pct(index, total_combos, 1, 1),
                        )
                        try:
                            pub_report = publish_official_plays_for_day(
                                db,
                                slip_date=today,
                                model_version=combo.model_version,
                                model_name=combo.model_name,
                            )
                            live_publication_summary = pub_report.to_dict()
                            live_publication_report = live_publication_summary
                            if pub_report.config_warning:
                                item_warnings.append(
                                    f"live_publication:{pub_report.config_warning}"
                                )
                            if pub_report.publication_errors:
                                for err in pub_report.publication_errors:
                                    item_warnings.append(f"live_publication_error:{err}")
                                    run_errors.append(
                                        f"live_publication {combo.model_version}/"
                                        f"{combo.model_name}: {err}"
                                    )
                            item_warnings.append(
                                "live_publication:"
                                f"created={pub_report.publications_created},"
                                f"duplicates={pub_report.duplicates_skipped},"
                                f"excluded={pub_report.predictions_excluded},"
                                f"candidates={pub_report.candidates_evaluated}"
                            )
                        except Exception as pub_exc:
                            # Visible failure — do not swallow silently.
                            db.rollback()
                            msg = f"live_publication_failed:{pub_exc}"
                            item_warnings.append(msg)
                            run_errors.append(
                                f"{combo.model_version}/{combo.model_name}: {msg}"
                            )
                            live_publication_summary = {
                                "config_status": "error",
                                "error": str(pub_exc),
                            }
                            live_publication_report = live_publication_summary
                            logger.exception(
                                "Live publication failed for %s/%s",
                                combo.model_version,
                                combo.model_name,
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
                    run_errors.append(
                        f"{combo.model_version}/{combo.model_name}: {exc}"
                    )
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

            _update_run_phase(db, run, phase="Generazione report", progress_pct=95.0)

            run.combinations_completed = completed
            run.combinations_failed = failed
            run.combinations_skipped = skipped
            run.slips_generated = total_slips
            run.finished_at = datetime.now()
            run.duration_seconds = round(time.perf_counter() - started, 2)

            if failed > 0 and completed > 0:
                run.status = "completed_with_errors"
            elif failed > 0 and completed == 0:
                run.status = "failed"
            else:
                run.status = "completed"

            run.current_phase = "Completato"
            run.progress_pct = 100.0
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
                "summary": {
                    "versions_processed": run.versions_processed,
                    "models_processed": run.models_processed,
                    "combinations_total": total_combos,
                    "combinations_completed": completed,
                    "combinations_failed": failed,
                    "combinations_skipped": skipped,
                    "fixtures_processed": run.fixtures_processed,
                    "slips_generated": total_slips,
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
            run.report_json = _json_dumps(report)
            db.commit()
    except GlobalUpdateCancelled:
        with SessionLocal() as db:
            run = get_run_by_id(db, run_id)
            if run is not None and run.status in RUNNING_STATUSES:
                _finalize_cancelled_run(db, run, reason="Run cancelled by user.")
        _cancel_requested.discard(run_id)
    finally:
        _cancel_requested.discard(run_id)
        with _active_thread_lock:
            if _active_run_id == run_id:
                _active_run_id = None


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
        "phases": [],
        "items": _run_to_read_dict(run)["items"],
        "errors": _json_loads(run.errors_json, []),
        "warnings": _json_loads(run.warnings_json, []),
    }


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
