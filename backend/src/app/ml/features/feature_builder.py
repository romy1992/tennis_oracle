import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from backend.src.app.models import FeatureSnapshot, MLMatch, RankingSnapshot

logger = logging.getLogger(__name__)


def _player_match_filter(player_id: int):
    return or_(MLMatch.player_1_id == player_id, MLMatch.player_2_id == player_id)


def _completed_match_filter():
    return MLMatch.winner_id.is_not(None)


def _historical_matches_for_player(
    db: Session,
    player_id: int,
    before_date: date,
    limit: int | None = None,
    surface: str | None = None,
) -> list[MLMatch]:
    conditions = [
        MLMatch.match_date < before_date,
        _player_match_filter(player_id),
        _completed_match_filter(),
    ]
    if surface:
        conditions.append(MLMatch.surface == surface)

    stmt = select(MLMatch).where(and_(*conditions)).order_by(MLMatch.match_date.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).all())


def calculate_ranking_pre_match(
    db: Session,
    player_id: int,
    match_date: date,
    tour: str | None = None,
) -> RankingSnapshot | None:
    conditions = [
        RankingSnapshot.player_id == player_id,
        RankingSnapshot.ranking_date < match_date,
    ]
    if tour:
        conditions.append(RankingSnapshot.tour == tour)

    stmt = (
        select(RankingSnapshot)
        .where(and_(*conditions))
        .order_by(RankingSnapshot.ranking_date.desc(), RankingSnapshot.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def calculate_win_rate_last_n(
    db: Session,
    player_id: int,
    before_date: date,
    n: int,
    surface: str | None = None,
) -> float | None:
    matches = _historical_matches_for_player(
        db=db,
        player_id=player_id,
        before_date=before_date,
        limit=n,
        surface=surface,
    )
    if not matches:
        return None
    wins = sum(1 for match in matches if match.winner_id == player_id)
    return wins / len(matches)


def calculate_surface_win_rate_last_n(
    db: Session,
    player_id: int,
    before_date: date,
    surface: str | None,
    n: int,
) -> float | None:
    if not surface:
        return None
    return calculate_win_rate_last_n(
        db=db,
        player_id=player_id,
        before_date=before_date,
        n=n,
        surface=surface,
    )


def calculate_days_since_last_match(
    db: Session,
    player_id: int,
    before_date: date,
) -> int | None:
    matches = _historical_matches_for_player(
        db=db,
        player_id=player_id,
        before_date=before_date,
        limit=1,
    )
    if not matches:
        return None
    return (before_date - matches[0].match_date).days


def calculate_matches_last_14_days(
    db: Session,
    player_id: int,
    before_date: date,
) -> int:
    start_date = before_date - timedelta(days=14)
    stmt = select(MLMatch).where(
        and_(
            MLMatch.match_date >= start_date,
            MLMatch.match_date < before_date,
            _player_match_filter(player_id),
            _completed_match_filter(),
        )
    )
    return len(db.scalars(stmt).all())


def calculate_h2h(
    db: Session,
    player_1_id: int,
    player_2_id: int,
    before_date: date,
    surface: str | None = None,
) -> tuple[int, int]:
    conditions = [
        MLMatch.match_date < before_date,
        _completed_match_filter(),
        or_(
            and_(MLMatch.player_1_id == player_1_id, MLMatch.player_2_id == player_2_id),
            and_(MLMatch.player_1_id == player_2_id, MLMatch.player_2_id == player_1_id),
        ),
    ]
    if surface:
        conditions.append(MLMatch.surface == surface)

    matches = db.scalars(select(MLMatch).where(and_(*conditions))).all()
    player_1_wins = sum(1 for match in matches if match.winner_id == player_1_id)
    player_2_wins = sum(1 for match in matches if match.winner_id == player_2_id)
    return player_1_wins, player_2_wins


def prepare_feature_snapshot_row(
    db: Session,
    match: MLMatch,
    player_1_elo: float | None = None,
    player_2_elo: float | None = None,
    player_1_surface_elo: float | None = None,
    player_2_surface_elo: float | None = None,
) -> FeatureSnapshot:
    match_date = match.match_date
    surface = match.surface
    player_1_rank = calculate_ranking_pre_match(db, match.player_1_id, match_date)
    player_2_rank = calculate_ranking_pre_match(db, match.player_2_id, match_date)
    h2h_player_1_wins, h2h_player_2_wins = calculate_h2h(
        db,
        match.player_1_id,
        match.player_2_id,
        match_date,
    )
    h2h_surface_player_1_wins, h2h_surface_player_2_wins = calculate_h2h(
        db,
        match.player_1_id,
        match.player_2_id,
        match_date,
        surface=surface,
    )

    rank_1 = player_1_rank.rank if player_1_rank else None
    rank_2 = player_2_rank.rank if player_2_rank else None

    return FeatureSnapshot(
        match_id=match.id,
        player_1_id=match.player_1_id,
        player_2_id=match.player_2_id,
        feature_date=match_date,
        surface=surface,
        player_1_rank=rank_1,
        player_2_rank=rank_2,
        rank_diff=rank_1 - rank_2 if rank_1 is not None and rank_2 is not None else None,
        player_1_elo=player_1_elo,
        player_2_elo=player_2_elo,
        elo_diff=(
            player_1_elo - player_2_elo
            if player_1_elo is not None and player_2_elo is not None
            else None
        ),
        player_1_surface_elo=player_1_surface_elo,
        player_2_surface_elo=player_2_surface_elo,
        surface_elo_diff=(
            player_1_surface_elo - player_2_surface_elo
            if player_1_surface_elo is not None and player_2_surface_elo is not None
            else None
        ),
        player_1_last_5_win_rate=calculate_win_rate_last_n(db, match.player_1_id, match_date, 5),
        player_2_last_5_win_rate=calculate_win_rate_last_n(db, match.player_2_id, match_date, 5),
        player_1_last_10_win_rate=calculate_win_rate_last_n(db, match.player_1_id, match_date, 10),
        player_2_last_10_win_rate=calculate_win_rate_last_n(db, match.player_2_id, match_date, 10),
        player_1_surface_last_10_win_rate=calculate_surface_win_rate_last_n(
            db,
            match.player_1_id,
            match_date,
            surface,
            10,
        ),
        player_2_surface_last_10_win_rate=calculate_surface_win_rate_last_n(
            db,
            match.player_2_id,
            match_date,
            surface,
            10,
        ),
        player_1_matches_last_14_days=calculate_matches_last_14_days(
            db,
            match.player_1_id,
            match_date,
        ),
        player_2_matches_last_14_days=calculate_matches_last_14_days(
            db,
            match.player_2_id,
            match_date,
        ),
        player_1_days_since_last_match=calculate_days_since_last_match(
            db,
            match.player_1_id,
            match_date,
        ),
        player_2_days_since_last_match=calculate_days_since_last_match(
            db,
            match.player_2_id,
            match_date,
        ),
        h2h_player_1_wins=h2h_player_1_wins,
        h2h_player_2_wins=h2h_player_2_wins,
        h2h_surface_player_1_wins=h2h_surface_player_1_wins,
        h2h_surface_player_2_wins=h2h_surface_player_2_wins,
        target_player_1_win=(
            1
            if match.winner_id == match.player_1_id
            else 0
            if match.winner_id == match.player_2_id
            else None
        ),
    )


@dataclass
class FeatureBuildResult:
    matches_processed: int = 0
    features_created: int = 0
    matches_skipped: int = 0
    skip_reasons: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.matches_skipped += 1
        self.skip_reasons[reason] = self.skip_reasons.get(reason, 0) + 1


@dataclass(frozen=True)
class PlayerMatchHistoryItem:
    match_date: date
    surface: str | None
    won: bool


@dataclass
class PlayerHistoricalState:
    matches: list[PlayerMatchHistoryItem] = field(default_factory=list)

    def win_rate_last_n(self, n: int, surface: str | None = None) -> float | None:
        matches = [
            match
            for match in reversed(self.matches)
            if surface is None or match.surface == surface
        ][:n]
        if not matches:
            return None
        return sum(1 for match in matches if match.won) / len(matches)

    def days_since_last_match(self, match_date: date) -> int | None:
        if not self.matches:
            return None
        return (match_date - self.matches[-1].match_date).days

    def matches_last_14_days(self, match_date: date) -> int:
        start_date = match_date - timedelta(days=14)
        return sum(1 for match in self.matches if match.match_date >= start_date)

    def record_match(
        self,
        match_date: date,
        surface: str | None,
        won: bool,
    ) -> None:
        self.matches.append(
            PlayerMatchHistoryItem(match_date=match_date, surface=surface, won=won)
        )


class FeatureEngineeringState:
    def __init__(self) -> None:
        self.players: dict[int, PlayerHistoricalState] = defaultdict(PlayerHistoricalState)
        self.h2h: dict[tuple[int, int], dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self.surface_h2h: dict[tuple[int, int, str], dict[int, int]] = defaultdict(
            lambda: defaultdict(int)
        )

    def player_state(self, player_id: int) -> PlayerHistoricalState:
        return self.players[player_id]

    def h2h_wins(
        self,
        player_1_id: int,
        player_2_id: int,
        surface: str | None = None,
    ) -> tuple[int, int]:
        if surface is None:
            wins = self.h2h[_h2h_key(player_1_id, player_2_id)]
        else:
            wins = self.surface_h2h[_surface_h2h_key(player_1_id, player_2_id, surface)]
        return wins[player_1_id], wins[player_2_id]

    def record_match(self, match: MLMatch) -> None:
        player_1_won = match.winner_id == match.player_1_id
        player_2_won = match.winner_id == match.player_2_id

        self.player_state(match.player_1_id).record_match(
            match_date=match.match_date,
            surface=match.surface,
            won=player_1_won,
        )
        self.player_state(match.player_2_id).record_match(
            match_date=match.match_date,
            surface=match.surface,
            won=player_2_won,
        )

        pair_key = _h2h_key(match.player_1_id, match.player_2_id)
        self.h2h[pair_key][match.winner_id] += 1
        if match.surface:
            surface_key = _surface_h2h_key(
                match.player_1_id,
                match.player_2_id,
                match.surface,
            )
            self.surface_h2h[surface_key][match.winner_id] += 1


def _h2h_key(player_1_id: int, player_2_id: int) -> tuple[int, int]:
    return tuple(sorted((player_1_id, player_2_id)))


def _surface_h2h_key(
    player_1_id: int,
    player_2_id: int,
    surface: str,
) -> tuple[int, int, str]:
    player_low, player_high = _h2h_key(player_1_id, player_2_id)
    return player_low, player_high, surface


def _rank_value_for_match(
    db: Session,
    match: MLMatch,
    player_id: int,
) -> int | None:
    ranking = calculate_ranking_pre_match(db, player_id, match.match_date)
    if ranking:
        return ranking.rank
    if player_id == match.player_1_id:
        return match.player_1_rank_at_match
    if player_id == match.player_2_id:
        return match.player_2_rank_at_match
    return None


def prepare_feature_snapshot_from_state(
    db: Session,
    match: MLMatch,
    state: FeatureEngineeringState,
) -> FeatureSnapshot:
    player_1_state = state.player_state(match.player_1_id)
    player_2_state = state.player_state(match.player_2_id)
    player_1_rank = _rank_value_for_match(db, match, match.player_1_id)
    player_2_rank = _rank_value_for_match(db, match, match.player_2_id)
    h2h_player_1_wins, h2h_player_2_wins = state.h2h_wins(
        match.player_1_id,
        match.player_2_id,
    )
    if match.surface:
        h2h_surface_player_1_wins, h2h_surface_player_2_wins = state.h2h_wins(
            match.player_1_id,
            match.player_2_id,
            surface=match.surface,
        )
    else:
        h2h_surface_player_1_wins, h2h_surface_player_2_wins = 0, 0

    return FeatureSnapshot(
        match_id=match.id,
        player_1_id=match.player_1_id,
        player_2_id=match.player_2_id,
        feature_date=match.match_date,
        surface=match.surface,
        player_1_rank=player_1_rank,
        player_2_rank=player_2_rank,
        rank_diff=(
            player_1_rank - player_2_rank
            if player_1_rank is not None and player_2_rank is not None
            else None
        ),
        player_1_last_5_win_rate=player_1_state.win_rate_last_n(5),
        player_2_last_5_win_rate=player_2_state.win_rate_last_n(5),
        player_1_last_10_win_rate=player_1_state.win_rate_last_n(10),
        player_2_last_10_win_rate=player_2_state.win_rate_last_n(10),
        player_1_surface_last_10_win_rate=(
            player_1_state.win_rate_last_n(10, surface=match.surface)
            if match.surface
            else None
        ),
        player_2_surface_last_10_win_rate=(
            player_2_state.win_rate_last_n(10, surface=match.surface)
            if match.surface
            else None
        ),
        player_1_matches_last_14_days=player_1_state.matches_last_14_days(
            match.match_date
        ),
        player_2_matches_last_14_days=player_2_state.matches_last_14_days(
            match.match_date
        ),
        player_1_days_since_last_match=player_1_state.days_since_last_match(
            match.match_date
        ),
        player_2_days_since_last_match=player_2_state.days_since_last_match(
            match.match_date
        ),
        h2h_player_1_wins=h2h_player_1_wins,
        h2h_player_2_wins=h2h_player_2_wins,
        h2h_surface_player_1_wins=h2h_surface_player_1_wins,
        h2h_surface_player_2_wins=h2h_surface_player_2_wins,
        target_player_1_win=1 if match.winner_id == match.player_1_id else 0,
    )


def _is_valid_completed_match(match: MLMatch) -> bool:
    return match.winner_id in {match.player_1_id, match.player_2_id}


def build_feature_snapshots_report(
    db: Session,
    limit: int | None = None,
    reset: bool = False,
    overwrite: bool = False,
) -> FeatureBuildResult:
    if reset or overwrite:
        deleted = db.execute(delete(FeatureSnapshot)).rowcount or 0
        db.flush()
        logger.info("FeatureSnapshot precedenti cancellate: %s", deleted)

    existing_match_ids = set()
    if not (reset or overwrite):
        existing_match_ids = set(db.scalars(select(FeatureSnapshot.match_id)).all())

    stmt = select(MLMatch).order_by(MLMatch.match_date.asc(), MLMatch.id.asc())
    if limit is not None:
        stmt = stmt.limit(limit)

    result = FeatureBuildResult()
    state = FeatureEngineeringState()
    for match in db.scalars(stmt).all():
        result.matches_processed += 1

        if match.winner_id is None:
            result.skip("winner mancante")
            continue
        if not _is_valid_completed_match(match):
            result.skip("winner non coerente con player_1/player_2")
            logger.warning(
                "Match %s saltato: winner_id=%s non corrisponde a player_1_id=%s o player_2_id=%s",
                match.id,
                match.winner_id,
                match.player_1_id,
                match.player_2_id,
            )
            continue

        if match.id in existing_match_ids:
            result.skip("feature gia esistente")
        else:
            db.add(prepare_feature_snapshot_from_state(db, match, state))
            result.features_created += 1

        state.record_match(match)

        if result.matches_processed % 1000 == 0:
            logger.info(
                "Feature engineering: match=%s create=%s skip=%s",
                result.matches_processed,
                result.features_created,
                result.matches_skipped,
            )

    db.commit()
    logger.info(
        "Feature engineering completato: match=%s create=%s skip=%s",
        result.matches_processed,
        result.features_created,
        result.matches_skipped,
    )
    for reason, count in sorted(result.skip_reasons.items()):
        logger.info("Skip: %s = %s", reason, count)
    return result


def build_feature_snapshots(
    db: Session,
    limit: int | None = None,
    overwrite: bool = False,
) -> int:
    result = build_feature_snapshots_report(
        db=db,
        limit=limit,
        reset=overwrite,
        overwrite=overwrite,
    )
    return result.features_created
