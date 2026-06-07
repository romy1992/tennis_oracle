from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from src.app.models import FeatureSnapshot, MLMatch, RankingSnapshot


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


def build_feature_snapshots(
    db: Session,
    limit: int | None = None,
    overwrite: bool = False,
) -> int:
    stmt = (
        select(MLMatch)
        .where(_completed_match_filter())
        .order_by(MLMatch.match_date.asc(), MLMatch.id.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    created = 0
    for match in db.scalars(stmt).all():
        existing = db.scalars(
            select(FeatureSnapshot).where(FeatureSnapshot.match_id == match.id)
        ).first()
        if existing and not overwrite:
            continue
        if existing:
            db.delete(existing)
            db.flush()

        db.add(prepare_feature_snapshot_row(db, match))
        created += 1

    db.commit()
    return created
