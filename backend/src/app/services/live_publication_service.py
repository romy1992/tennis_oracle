"""Centralized live publication of official PLAY tips into PublishedPrediction.

Uses the ML-07 public model registry when a DB session is available; falls back to
``PUBLIC_MODEL_*`` env only when no active registry entry exists (legacy bootstrap).
Does not create a second prediction system: reuses ``build_candidate_pool`` criteria
and ``publish_prediction``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.src.app.core.config import Settings, get_settings
from backend.src.app.schemas.prematch_odds_snapshot import PrematchOddsSnapshotCreate
from backend.src.app.schemas.published_prediction import PublishedPredictionCreate
from backend.src.app.services.betting_slips import CandidatePick, build_candidate_pool
from backend.src.app.services.prematch_odds_snapshots import record_snapshot
from backend.src.app.services.published_predictions import (
    PublishedPredictionError,
    publish_prediction,
)
from backend.src.entity.betting_slip import BettingSlip, BettingSlipPick
from backend.src.entity.match_prediction import MatchPrediction
from backend.src.entity.published_prediction import PublishedPrediction

logger = logging.getLogger(__name__)

PUBLICATION_SOURCE = "global_update"
UNIT_STAKE = 1.0
# Documented sentinel when no bookmaker is available for a publication snapshot.
# Do not invent a real bookmaker name.
PUBLICATION_BOOKMAKER = "publication"

from backend.src.app.services.public_model_registry import (  # noqa: E402
    ALLOWED_PUBLIC_MODEL_NAMES,
    ALLOWED_PUBLIC_MODEL_VERSIONS,
    resolve_public_model_from_registry,
)

PublicConfigStatus = Literal[
    "ready",
    "disabled",
    "incomplete",
    "invalid",
]

PublicConfigSource = Literal["registry", "env"]


@dataclass(frozen=True)
class PublicModelPublicationConfig:
    """Resolved public-model config for live publication."""

    enabled: bool
    model_version: str | None
    model_name: str | None
    status: PublicConfigStatus
    source: PublicConfigSource | None = None
    warning: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == "ready" and self.enabled


ExclusionReason = Literal[
    "not_play",
    "missing_selection",
    "invalid_probability",
    "missing_odds",
    "match_started",
    "publish_error",
]


@dataclass
class LivePublicationReport:
    """Observable counters for a live publication pass."""

    config_status: PublicConfigStatus
    config_warning: str | None = None
    public_model_version: str | None = None
    public_model_name: str | None = None
    candidates_evaluated: int = 0
    publications_created: int = 0
    duplicates_skipped: int = 0
    predictions_excluded: int = 0
    exclusion_reasons: dict[str, int] = field(default_factory=dict)
    publication_errors: list[str] = field(default_factory=list)
    snapshot_publications_created: int = 0
    snapshot_publications_duplicates: int = 0

    def to_dict(self) -> dict:
        return {
            "config_status": self.config_status,
            "config_warning": self.config_warning,
            "public_model_version": self.public_model_version,
            "public_model_name": self.public_model_name,
            "candidates_evaluated": self.candidates_evaluated,
            "publications_created": self.publications_created,
            "duplicates_skipped": self.duplicates_skipped,
            "predictions_excluded": self.predictions_excluded,
            "exclusion_reasons": dict(self.exclusion_reasons),
            "publication_errors": list(self.publication_errors),
            "snapshot_publications_created": self.snapshot_publications_created,
            "snapshot_publications_duplicates": self.snapshot_publications_duplicates,
        }

    def _bump_exclusion(self, reason: ExclusionReason) -> None:
        self.predictions_excluded += 1
        self.exclusion_reasons[reason] = self.exclusion_reasons.get(reason, 0) + 1


def resolve_public_model_config(
    settings: Settings | None = None,
    db: Session | None = None,
) -> PublicModelPublicationConfig:
    """Resolve public model from registry (preferred) or legacy env vars."""
    cfg = settings or get_settings()
    enabled = bool(cfg.live_publication_enabled)

    registry_combo = resolve_public_model_from_registry(db)
    source: PublicConfigSource | None = None
    version: str | None = None
    name: str | None = None

    if registry_combo is not None:
        version, name = registry_combo
        source = "registry"
    else:
        version = (cfg.public_model_version or "").strip() or None
        name = (cfg.public_model_name or "").strip() or None
        if version is not None and name is not None:
            source = "env"

    if not enabled:
        return PublicModelPublicationConfig(
            enabled=False,
            model_version=version,
            model_name=name,
            status="disabled",
            source=source,
            warning=(
                "Live publication disabled (LIVE_PUBLICATION_ENABLED=false). "
                "Pipeline continues without writing PublishedPrediction."
            ),
        )

    if version is None or name is None:
        detail = (
            "Live publication enabled but nessun modello attivo nel registro ML-07 "
            "e PUBLIC_MODEL_VERSION / PUBLIC_MODEL_NAME non configurati."
            if source is None
            else "Live publication enabled but PUBLIC_MODEL_VERSION and/or "
            "PUBLIC_MODEL_NAME are missing. No tips published; no fallback."
        )
        return PublicModelPublicationConfig(
            enabled=True,
            model_version=version,
            model_name=name,
            status="incomplete",
            source=source,
            warning=detail,
        )

    if version not in ALLOWED_PUBLIC_MODEL_VERSIONS or name not in ALLOWED_PUBLIC_MODEL_NAMES:
        return PublicModelPublicationConfig(
            enabled=True,
            model_version=version,
            model_name=name,
            status="invalid",
            source=source,
            warning=(
                f"Invalid public model config {version}/{name}. "
                f"Allowed versions={sorted(ALLOWED_PUBLIC_MODEL_VERSIONS)}, "
                f"names={sorted(ALLOWED_PUBLIC_MODEL_NAMES)}. No fallback."
            ),
        )

    return PublicModelPublicationConfig(
        enabled=True,
        model_version=version,
        model_name=name,
        status="ready",
        source=source,
        warning=None,
    )


def find_existing_live_publication(
    db: Session,
    *,
    event_key: int,
    selection: str,
    model_version: str,
    model_name: str,
    publication_source: str = PUBLICATION_SOURCE,
) -> PublishedPrediction | None:
    """Return content_version=1 row for the logical tip identity, if any."""
    return db.scalar(
        select(PublishedPrediction)
        .where(
            PublishedPrediction.event_key == event_key,
            PublishedPrediction.selection == selection.strip(),
            PublishedPrediction.model_version == model_version,
            PublishedPrediction.model_name == model_name,
            PublishedPrediction.publication_source == publication_source,
            PublishedPrediction.content_version == 1,
        )
        .limit(1)
    )


def _match_prediction_id(
    db: Session,
    *,
    event_key: int,
    model_version: str,
    model_name: str,
) -> int | None:
    row = db.scalar(
        select(MatchPrediction.id)
        .where(
            MatchPrediction.event_key == event_key,
            MatchPrediction.model_version == model_version,
            MatchPrediction.model_name == model_name,
        )
        .limit(1)
    )
    return int(row) if row is not None else None


def _play_slip_pick_id(
    db: Session,
    *,
    event_key: int,
    model_version: str,
    model_name: str,
    slip_date: date,
) -> int | None:
    """Prefer a persisted pick from play_* profiles (PLAY-only slips)."""
    row = db.scalar(
        select(BettingSlipPick.id)
        .join(BettingSlip, BettingSlip.id == BettingSlipPick.betting_slip_id)
        .where(
            BettingSlipPick.event_key == event_key,
            BettingSlip.model_version == model_version,
            BettingSlip.model_name == model_name,
            BettingSlip.slip_date == slip_date,
            BettingSlip.slip_key.like("play_%"),
        )
        .order_by(BettingSlipPick.id.asc())
        .limit(1)
    )
    return int(row) if row is not None else None


def _selection_for_candidate(candidate: CandidatePick) -> str | None:
    label = (candidate.predicted_winner_label or "").strip()
    if label:
        return label
    winner = (candidate.predicted_winner or "").strip()
    return winner or None


def _is_publishable_play(
    candidate: CandidatePick,
    report: LivePublicationReport,
) -> tuple[bool, str | None]:
    """Apply official PLAY criteria; return (ok, selection)."""
    if candidate.value_decision != "PLAY":
        report._bump_exclusion("not_play")
        return False, None

    selection = _selection_for_candidate(candidate)
    if not selection:
        report._bump_exclusion("missing_selection")
        return False, None

    probability = float(candidate.model_prob)
    if not (0.0 < probability < 1.0):
        report._bump_exclusion("invalid_probability")
        return False, None

    if candidate.odds is None or float(candidate.odds) <= 1.0:
        report._bump_exclusion("missing_odds")
        return False, None

    if candidate.void_odds is None or float(candidate.void_odds) <= 1.0:
        report._bump_exclusion("missing_odds")
        return False, None

    return True, selection


def _record_publication_snapshot(
    db: Session,
    *,
    event_key: int,
    selection: str,
    odds: float,
    player_1_name: str | None,
    player_2_name: str | None,
    report: LivePublicationReport,
) -> None:
    created = record_snapshot(
        db,
        PrematchOddsSnapshotCreate(
            event_key=event_key,
            selection=selection,
            bookmaker=PUBLICATION_BOOKMAKER,
            odds=float(odds),
            source="publication",
            snapshot_type="publication",
            player_1_name=player_1_name,
            player_2_name=player_2_name,
        ),
        commit=False,
    )
    if created is None:
        report.snapshot_publications_duplicates += 1
    else:
        report.snapshot_publications_created += 1


def publish_official_plays_for_day(
    db: Session,
    *,
    slip_date: date,
    model_version: str | None = None,
    model_name: str | None = None,
    settings: Settings | None = None,
    min_edge_percent: float | None = None,
) -> LivePublicationReport:
    """Publish PLAY candidates for the configured public model (idempotent).

    When config is not ready, returns a report with warning and creates nothing.
    """
    public = resolve_public_model_config(settings, db=db)
    report = LivePublicationReport(
        config_status=public.status,
        config_warning=public.warning,
        public_model_version=public.model_version,
        public_model_name=public.model_name,
    )

    if not public.is_ready:
        return report

    version = model_version or public.model_version
    name = model_name or public.model_name
    assert version is not None and name is not None
    report.public_model_version = version
    report.public_model_name = name

    if version != public.model_version or name != public.model_name:
        # Refuse publishing a non-public combo even if caller passes overrides by mistake.
        report.config_status = "invalid"
        report.config_warning = (
            f"Refusing to publish non-public combo {version}/{name}; "
            f"configured public is {public.model_version}/{public.model_name}."
        )
        return report

    candidates = build_candidate_pool(
        db,
        slip_date=slip_date,
        model_version=version,  # type: ignore[arg-type]
        model_name=name,
        min_edge_percent=min_edge_percent,
    )
    report.candidates_evaluated = len(candidates)

    for candidate in candidates:
        ok, selection = _is_publishable_play(candidate, report)
        if not ok or selection is None:
            continue

        existing = find_existing_live_publication(
            db,
            event_key=candidate.event_key,
            selection=selection,
            model_version=version,
            model_name=name,
            publication_source=PUBLICATION_SOURCE,
        )
        if existing is not None:
            report.duplicates_skipped += 1
            continue

        payload = PublishedPredictionCreate(
            event_key=candidate.event_key,
            selection=selection,
            model_version=version,
            model_name=name,
            probability=float(candidate.model_prob),
            odds=float(candidate.odds) if candidate.odds is not None else None,
            void_odds=float(candidate.void_odds),
            edge=float(candidate.edge_percent),
            unit_stake=UNIT_STAKE,
            publication_source=PUBLICATION_SOURCE,
            initial_status="published",
            player_1_name=candidate.player_1_name,
            player_2_name=candidate.player_2_name,
            tournament_name=candidate.tournament_name,
            event_date=candidate.event_date,
            event_time=candidate.event_time,
            match_prediction_id=_match_prediction_id(
                db,
                event_key=candidate.event_key,
                model_version=version,
                model_name=name,
            ),
            betting_slip_pick_id=_play_slip_pick_id(
                db,
                event_key=candidate.event_key,
                model_version=version,
                model_name=name,
                slip_date=slip_date,
            ),
        )

        try:
            published = publish_prediction(db, payload)
        except PublishedPredictionError as exc:
            if exc.status_code == 409:
                report._bump_exclusion("match_started")
            else:
                report._bump_exclusion("publish_error")
                report.publication_errors.append(
                    f"event_key={candidate.event_key}: {exc.message}"
                )
            continue
        except IntegrityError:
            db.rollback()
            # Concurrent re-run or race: treat as duplicate.
            report.duplicates_skipped += 1
            continue
        except Exception as exc:  # noqa: BLE001 — surface in report, do not hide
            report._bump_exclusion("publish_error")
            report.publication_errors.append(
                f"event_key={candidate.event_key}: {exc}"
            )
            logger.exception(
                "Live publication failed for event_key=%s",
                candidate.event_key,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
            continue

        report.publications_created += 1
        if published.odds is not None:
            try:
                _record_publication_snapshot(
                    db,
                    event_key=published.event_key,
                    selection=published.selection,
                    odds=float(published.odds),
                    player_1_name=published.player_1_name,
                    player_2_name=published.player_2_name,
                    report=report,
                )
                db.commit()
            except Exception as exc:  # noqa: BLE001
                report.publication_errors.append(
                    f"snapshot event_key={published.event_key}: {exc}"
                )
                logger.exception(
                    "Publication odds snapshot failed for event_key=%s",
                    published.event_key,
                )
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass

    return report


def is_public_combination(
    model_version: str,
    model_name: str,
    db: Session | None = None,
) -> bool:
    public = resolve_public_model_config(db=db)
    return (
        public.is_ready
        and public.model_version == model_version
        and public.model_name == model_name
    )
