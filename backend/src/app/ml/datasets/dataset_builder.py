from dataclasses import dataclass
from datetime import date, timedelta
from itertools import groupby
from pathlib import Path

import pandas as pd
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from backend.src.entity import Fixture, Tournament
from backend.src.app.models import FeatureSnapshot
from backend.src.app.ml.datasets.elo_builder import EloTracker, INITIAL_ELO
from backend.src.app.ml.datasets.ranking_history import (
    HistoricalRankingLookup,
    WTA_RANKING_FALLBACK_NOTE,
    build_historical_ranking_lookup,
)
from backend.src.app.ml.model_versioning import (
    ATP_DATA_DIR,
    DATASET_VERSIONS,
    MATCH_MAPPING_PATH,
    PROCESSED_DATA_DIR,
)


TARGET_COLUMN = "target_player_1_win"
MISSING_RANK_VALUE = 9999
DEFAULT_ELO_VALUE = 1500.0
DEFAULT_WIN_RATE_VALUE = 0.5
MISSING_DAYS_SINCE_LAST_MATCH = 9999

MINIMUM_DATASET_COLUMNS = [
    "match_id",
    "match_date",
    "surface",
    "player_1_id",
    "player_2_id",
    "player_1_rank",
    "player_2_rank",
    "rank_diff",
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "player_1_surface_last_10_win_rate",
    "player_2_surface_last_10_win_rate",
    "player_1_matches_last_14_days",
    "player_2_matches_last_14_days",
    "player_1_days_since_last_match",
    "player_2_days_since_last_match",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "h2h_surface_player_1_wins",
    "h2h_surface_player_2_wins",
    TARGET_COLUMN,
]
ELO_DATASET_COLUMNS = [
    "player_1_elo",
    "player_2_elo",
    "elo_diff",
    "player_1_surface_elo",
    "player_2_surface_elo",
    "surface_elo_diff",
]
RANK_POINTS_COLUMNS = [
    "player_1_rank_points",
    "player_2_rank_points",
    "rank_points_diff",
]
DATASET_COLUMNS = [
    "match_id",
    "match_date",
    "surface",
    "player_1_id",
    "player_2_id",
    "player_1_rank",
    "player_2_rank",
    "rank_diff",
    *ELO_DATASET_COLUMNS,
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "player_1_surface_last_10_win_rate",
    "player_2_surface_last_10_win_rate",
    "player_1_matches_last_14_days",
    "player_2_matches_last_14_days",
    "player_1_days_since_last_match",
    "player_2_days_since_last_match",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "h2h_surface_player_1_wins",
    "h2h_surface_player_2_wins",
    TARGET_COLUMN,
]
V2_DATASET_COLUMNS = [
    "match_id",
    "match_date",
    "surface",
    "player_1_id",
    "player_2_id",
    "player_1_rank",
    "player_2_rank",
    "rank_diff",
    *RANK_POINTS_COLUMNS,
    *ELO_DATASET_COLUMNS,
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "player_1_surface_last_10_win_rate",
    "player_2_surface_last_10_win_rate",
    "player_1_matches_last_14_days",
    "player_2_matches_last_14_days",
    "player_1_days_since_last_match",
    "player_2_days_since_last_match",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "h2h_surface_player_1_wins",
    "h2h_surface_player_2_wins",
    TARGET_COLUMN,
]
EXCLUDED_FEATURE_COLUMNS = {
    "id",
    "match_id",
    "player_1_id",
    "player_2_id",
    "feature_date",
    "match_date",
    "created_at",
    TARGET_COLUMN,
}


@dataclass(frozen=True)
class DatasetBuildResult:
    csv_path: Path
    dataframe: pd.DataFrame
    summary: "DatasetSummary"


@dataclass(frozen=True)
class DatasetSummary:
    total_rows: int
    total_columns: int
    target_percentages: dict[int, float]
    null_counts: dict[str, int]
    date_min: date | None
    date_max: date | None


@dataclass(frozen=True)
class V2DatasetSummary(DatasetSummary):
    elo_min: float | None
    elo_max: float | None
    non_default_elo_pct: float
    non_default_rank_pct: float
    ranking_fallback_note: str


@dataclass(frozen=True)
class LegacyMatchRow:
    match_id: int
    match_date: date
    surface: str | None
    player_1_id: int
    player_2_id: int
    target_player_1_win: int


@dataclass(frozen=True)
class PlayerHistoryItem:
    match_date: date
    surface: str
    won: bool


def _normalise_surface(surface: str | None) -> str:
    if not surface:
        return "unknown"
    clean_surface = surface.strip()
    if not clean_surface or clean_surface.startswith("-"):
        return "unknown"

    surface_map = {
        "clay": "Clay",
        "hard": "Hard",
        "grass": "Grass",
    }
    return surface_map.get(clean_surface.lower(), clean_surface)


def _h2h_key(player_1_id: int, player_2_id: int) -> tuple[int, int]:
    return tuple(sorted((player_1_id, player_2_id)))


def _surface_h2h_key(
    player_1_id: int,
    player_2_id: int,
    surface: str,
) -> tuple[int, int, str]:
    player_low, player_high = _h2h_key(player_1_id, player_2_id)
    return player_low, player_high, surface


def _win_rate_last_n(
    history: list[PlayerHistoryItem],
    n: int,
    surface: str | None = None,
) -> float | None:
    matches = [
        match
        for match in reversed(history)
        if surface is None or match.surface == surface
    ][:n]
    if not matches:
        return None
    return sum(1 for match in matches if match.won) / len(matches)


def _matches_last_14_days(
    history: list[PlayerHistoryItem],
    match_date: date,
) -> int:
    start_date = match_date - timedelta(days=14)
    return sum(
        1
        for match in history
        if start_date <= match.match_date < match_date
    )


def _days_since_last_match(
    history: list[PlayerHistoryItem],
    match_date: date,
) -> int | None:
    if not history:
        return None
    return (match_date - history[-1].match_date).days


def load_legacy_match_rows(db: Session) -> list[LegacyMatchRow]:
    stmt = (
        select(
            Fixture.event_key.label("match_id"),
            Fixture.event_date.label("match_date"),
            Tournament.tournament_sourface.label("surface"),
            Fixture.first_player_key.label("player_1_id"),
            Fixture.second_player_key.label("player_2_id"),
            Fixture.event_winner.label("event_winner"),
        )
        .select_from(Fixture)
        .join(Tournament, Tournament.tournament_key == Fixture.tournament_key, isouter=True)
        .where(
            and_(
                Fixture.event_date.is_not(None),
                Fixture.first_player_key.is_not(None),
                Fixture.second_player_key.is_not(None),
                Fixture.event_winner.in_(["First Player", "Second Player"]),
                Fixture.event_final_result.is_not(None),
                Fixture.event_final_result != "-",
                Fixture.event_type_type.ilike("%singles%"),
                ~Fixture.event_type_type.ilike("%doubles%"),
                ~Fixture.event_type_type.ilike("%teams%"),
            )
        )
        .order_by(Fixture.event_date.asc(), Fixture.event_key.asc())
    )

    rows = []
    for row in db.execute(stmt).all():
        rows.append(
            LegacyMatchRow(
                match_id=row.match_id,
                match_date=row.match_date,
                surface=_normalise_surface(row.surface),
                player_1_id=row.player_1_id,
                player_2_id=row.player_2_id,
                target_player_1_win=1 if row.event_winner == "First Player" else 0,
            )
        )
    return rows


def legacy_match_rows_to_dataframe(matches: list[LegacyMatchRow]) -> pd.DataFrame:
    player_history: dict[int, list[PlayerHistoryItem]] = {}
    h2h: dict[tuple[int, int], dict[int, int]] = {}
    surface_h2h: dict[tuple[int, int, str], dict[int, int]] = {}
    dataset_rows = []

    for match_date, date_matches_iter in groupby(matches, key=lambda match: match.match_date):
        date_matches = list(date_matches_iter)

        # Build features before recording this date, avoiding same-day result leakage.
        for match in date_matches:
            player_1_history = player_history.get(match.player_1_id, [])
            player_2_history = player_history.get(match.player_2_id, [])
            h2h_wins = h2h.get(_h2h_key(match.player_1_id, match.player_2_id), {})
            surface_wins = surface_h2h.get(
                _surface_h2h_key(match.player_1_id, match.player_2_id, match.surface),
                {},
            )

            dataset_rows.append(
                {
                    "match_id": match.match_id,
                    "match_date": match.match_date,
                    "surface": match.surface,
                    "player_1_id": match.player_1_id,
                    "player_2_id": match.player_2_id,
                    "player_1_rank": None,
                    "player_2_rank": None,
                    "rank_diff": None,
                    "player_1_elo": None,
                    "player_2_elo": None,
                    "elo_diff": None,
                    "player_1_surface_elo": None,
                    "player_2_surface_elo": None,
                    "surface_elo_diff": None,
                    "player_1_last_5_win_rate": _win_rate_last_n(player_1_history, 5),
                    "player_2_last_5_win_rate": _win_rate_last_n(player_2_history, 5),
                    "player_1_last_10_win_rate": _win_rate_last_n(player_1_history, 10),
                    "player_2_last_10_win_rate": _win_rate_last_n(player_2_history, 10),
                    "player_1_surface_last_10_win_rate": _win_rate_last_n(
                        player_1_history,
                        10,
                        surface=match.surface,
                    ),
                    "player_2_surface_last_10_win_rate": _win_rate_last_n(
                        player_2_history,
                        10,
                        surface=match.surface,
                    ),
                    "player_1_matches_last_14_days": _matches_last_14_days(
                        player_1_history,
                        match_date,
                    ),
                    "player_2_matches_last_14_days": _matches_last_14_days(
                        player_2_history,
                        match_date,
                    ),
                    "player_1_days_since_last_match": _days_since_last_match(
                        player_1_history,
                        match_date,
                    ),
                    "player_2_days_since_last_match": _days_since_last_match(
                        player_2_history,
                        match_date,
                    ),
                    "h2h_player_1_wins": h2h_wins.get(match.player_1_id, 0),
                    "h2h_player_2_wins": h2h_wins.get(match.player_2_id, 0),
                    "h2h_surface_player_1_wins": surface_wins.get(match.player_1_id, 0),
                    "h2h_surface_player_2_wins": surface_wins.get(match.player_2_id, 0),
                    "target_player_1_win": match.target_player_1_win,
                }
            )

        for match in date_matches:
            player_1_won = match.target_player_1_win == 1
            player_2_won = not player_1_won
            player_history.setdefault(match.player_1_id, []).append(
                PlayerHistoryItem(
                    match_date=match.match_date,
                    surface=match.surface,
                    won=player_1_won,
                )
            )
            player_history.setdefault(match.player_2_id, []).append(
                PlayerHistoryItem(
                    match_date=match.match_date,
                    surface=match.surface,
                    won=player_2_won,
                )
            )

            pair_key = _h2h_key(match.player_1_id, match.player_2_id)
            h2h.setdefault(pair_key, {})
            h2h[pair_key][match.player_1_id] = h2h[pair_key].get(match.player_1_id, 0)
            h2h[pair_key][match.player_2_id] = h2h[pair_key].get(match.player_2_id, 0)
            h2h[pair_key][match.player_1_id if player_1_won else match.player_2_id] += 1

            surface_key = _surface_h2h_key(
                match.player_1_id,
                match.player_2_id,
                match.surface,
            )
            surface_h2h.setdefault(surface_key, {})
            surface_h2h[surface_key][match.player_1_id] = surface_h2h[surface_key].get(
                match.player_1_id,
                0,
            )
            surface_h2h[surface_key][match.player_2_id] = surface_h2h[surface_key].get(
                match.player_2_id,
                0,
            )
            surface_h2h[surface_key][
                match.player_1_id if player_1_won else match.player_2_id
            ] += 1

    return pd.DataFrame(dataset_rows)


def legacy_match_rows_to_dataframe_v2(
    matches: list[LegacyMatchRow],
    ranking_lookup: HistoricalRankingLookup | None = None,
    elo_tracker: EloTracker | None = None,
) -> pd.DataFrame:
    player_history: dict[int, list[PlayerHistoryItem]] = {}
    h2h: dict[tuple[int, int], dict[int, int]] = {}
    surface_h2h: dict[tuple[int, int, str], dict[int, int]] = {}
    tracker = elo_tracker or EloTracker()
    rankings = ranking_lookup or HistoricalRankingLookup(pd.DataFrame(), {})
    dataset_rows = []

    for match_date, date_matches_iter in groupby(matches, key=lambda match: match.match_date):
        date_matches = list(date_matches_iter)

        for match in date_matches:
            player_1_history = player_history.get(match.player_1_id, [])
            player_2_history = player_history.get(match.player_2_id, [])
            h2h_wins = h2h.get(_h2h_key(match.player_1_id, match.player_2_id), {})
            surface_wins = surface_h2h.get(
                _surface_h2h_key(match.player_1_id, match.player_2_id, match.surface),
                {},
            )
            elo_features = tracker.pre_match_features(
                match.player_1_id,
                match.player_2_id,
                match.surface,
            )
            rank_features = rankings.pre_match_features(
                match.player_1_id,
                match.player_2_id,
                match.match_date,
            )

            dataset_rows.append(
                {
                    "match_id": match.match_id,
                    "match_date": match.match_date,
                    "surface": match.surface,
                    "player_1_id": match.player_1_id,
                    "player_2_id": match.player_2_id,
                    "player_1_rank": rank_features.player_1_rank,
                    "player_2_rank": rank_features.player_2_rank,
                    "rank_diff": rank_features.rank_diff,
                    "player_1_rank_points": rank_features.player_1_rank_points,
                    "player_2_rank_points": rank_features.player_2_rank_points,
                    "rank_points_diff": rank_features.rank_points_diff,
                    "player_1_elo": elo_features.player_1_elo,
                    "player_2_elo": elo_features.player_2_elo,
                    "elo_diff": elo_features.elo_diff,
                    "player_1_surface_elo": elo_features.player_1_surface_elo,
                    "player_2_surface_elo": elo_features.player_2_surface_elo,
                    "surface_elo_diff": elo_features.surface_elo_diff,
                    "player_1_last_5_win_rate": _win_rate_last_n(player_1_history, 5),
                    "player_2_last_5_win_rate": _win_rate_last_n(player_2_history, 5),
                    "player_1_last_10_win_rate": _win_rate_last_n(player_1_history, 10),
                    "player_2_last_10_win_rate": _win_rate_last_n(player_2_history, 10),
                    "player_1_surface_last_10_win_rate": _win_rate_last_n(
                        player_1_history,
                        10,
                        surface=match.surface,
                    ),
                    "player_2_surface_last_10_win_rate": _win_rate_last_n(
                        player_2_history,
                        10,
                        surface=match.surface,
                    ),
                    "player_1_matches_last_14_days": _matches_last_14_days(
                        player_1_history,
                        match_date,
                    ),
                    "player_2_matches_last_14_days": _matches_last_14_days(
                        player_2_history,
                        match_date,
                    ),
                    "player_1_days_since_last_match": _days_since_last_match(
                        player_1_history,
                        match_date,
                    ),
                    "player_2_days_since_last_match": _days_since_last_match(
                        player_2_history,
                        match_date,
                    ),
                    "h2h_player_1_wins": h2h_wins.get(match.player_1_id, 0),
                    "h2h_player_2_wins": h2h_wins.get(match.player_2_id, 0),
                    "h2h_surface_player_1_wins": surface_wins.get(match.player_1_id, 0),
                    "h2h_surface_player_2_wins": surface_wins.get(match.player_2_id, 0),
                    "target_player_1_win": match.target_player_1_win,
                }
            )

        for match in date_matches:
            player_1_won = match.target_player_1_win == 1
            player_2_won = not player_1_won
            player_history.setdefault(match.player_1_id, []).append(
                PlayerHistoryItem(
                    match_date=match.match_date,
                    surface=match.surface,
                    won=player_1_won,
                )
            )
            player_history.setdefault(match.player_2_id, []).append(
                PlayerHistoryItem(
                    match_date=match.match_date,
                    surface=match.surface,
                    won=player_2_won,
                )
            )

            pair_key = _h2h_key(match.player_1_id, match.player_2_id)
            h2h.setdefault(pair_key, {})
            h2h[pair_key][match.player_1_id] = h2h[pair_key].get(match.player_1_id, 0)
            h2h[pair_key][match.player_2_id] = h2h[pair_key].get(match.player_2_id, 0)
            h2h[pair_key][match.player_1_id if player_1_won else match.player_2_id] += 1

            surface_key = _surface_h2h_key(
                match.player_1_id,
                match.player_2_id,
                match.surface,
            )
            surface_h2h.setdefault(surface_key, {})
            surface_h2h[surface_key][match.player_1_id] = surface_h2h[surface_key].get(
                match.player_1_id,
                0,
            )
            surface_h2h[surface_key][match.player_2_id] = surface_h2h[surface_key].get(
                match.player_2_id,
                0,
            )
            surface_h2h[surface_key][
                match.player_1_id if player_1_won else match.player_2_id
            ] += 1

            tracker.record_match(
                match.player_1_id,
                match.player_2_id,
                match.surface,
                player_1_won,
            )

    return pd.DataFrame(dataset_rows)


def load_feature_snapshots(db: Session) -> list[FeatureSnapshot]:
    return load_valid_feature_snapshots(db)


def load_valid_feature_snapshots(db: Session) -> list[FeatureSnapshot]:
    stmt = select(FeatureSnapshot).order_by(
        FeatureSnapshot.feature_date.asc(),
        FeatureSnapshot.match_id.asc(),
    ).where(
        and_(
            FeatureSnapshot.match_id.is_not(None),
            FeatureSnapshot.player_1_id.is_not(None),
            FeatureSnapshot.player_2_id.is_not(None),
            FeatureSnapshot.feature_date.is_not(None),
            FeatureSnapshot.target_player_1_win.in_([0, 1]),
        )
    )
    return list(db.scalars(stmt).all())


def feature_snapshots_to_dataframe(snapshots: list[FeatureSnapshot]) -> pd.DataFrame:
    rows = [
        {
            column.name: getattr(snapshot, column.name)
            for column in FeatureSnapshot.__table__.columns
        }
        for snapshot in snapshots
    ]
    return pd.DataFrame(rows)


def _coerce_numeric(dataframe: pd.DataFrame, columns: list[str]) -> None:
    for column in columns:
        dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")


def clean_dataset_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    dataframe = dataframe.copy()
    if dataframe.empty:
        return pd.DataFrame(columns=DATASET_COLUMNS)

    dataframe = dataframe.rename(columns={"feature_date": "match_date"})
    for column in DATASET_COLUMNS:
        if column not in dataframe.columns:
            dataframe[column] = pd.NA

    dataframe = dataframe[dataframe[TARGET_COLUMN].isin([0, 1])].copy()
    dataframe["match_date"] = pd.to_datetime(dataframe["match_date"], errors="coerce")
    dataframe = dataframe.dropna(
        subset=["match_id", "match_date", "player_1_id", "player_2_id", TARGET_COLUMN]
    )

    id_columns = ["match_id", "player_1_id", "player_2_id", TARGET_COLUMN]
    rank_columns = ["player_1_rank", "player_2_rank"]
    win_rate_columns = [
        "player_1_last_5_win_rate",
        "player_2_last_5_win_rate",
        "player_1_last_10_win_rate",
        "player_2_last_10_win_rate",
        "player_1_surface_last_10_win_rate",
        "player_2_surface_last_10_win_rate",
    ]
    count_columns = [
        "player_1_matches_last_14_days",
        "player_2_matches_last_14_days",
        "h2h_player_1_wins",
        "h2h_player_2_wins",
        "h2h_surface_player_1_wins",
        "h2h_surface_player_2_wins",
    ]
    days_columns = [
        "player_1_days_since_last_match",
        "player_2_days_since_last_match",
    ]

    _coerce_numeric(
        dataframe,
        [
            *id_columns,
            *rank_columns,
            "rank_diff",
            *ELO_DATASET_COLUMNS,
            *win_rate_columns,
            *count_columns,
            *days_columns,
        ],
    )

    dataframe["surface"] = dataframe["surface"].fillna("unknown").astype(str)

    dataframe[rank_columns] = dataframe[rank_columns].fillna(MISSING_RANK_VALUE)
    dataframe["rank_diff"] = dataframe["player_1_rank"] - dataframe["player_2_rank"]

    elo_value_columns = [
        "player_1_elo",
        "player_2_elo",
        "player_1_surface_elo",
        "player_2_surface_elo",
    ]
    dataframe[elo_value_columns] = dataframe[elo_value_columns].fillna(DEFAULT_ELO_VALUE)
    dataframe["elo_diff"] = dataframe["player_1_elo"] - dataframe["player_2_elo"]
    dataframe["surface_elo_diff"] = (
        dataframe["player_1_surface_elo"] - dataframe["player_2_surface_elo"]
    )

    dataframe[win_rate_columns] = dataframe[win_rate_columns].fillna(
        DEFAULT_WIN_RATE_VALUE
    )
    dataframe[win_rate_columns] = dataframe[win_rate_columns].clip(lower=0.0, upper=1.0)
    dataframe[count_columns] = dataframe[count_columns].fillna(0)
    dataframe[days_columns] = dataframe[days_columns].fillna(
        MISSING_DAYS_SINCE_LAST_MATCH
    )

    int_columns = [*id_columns, *rank_columns, *count_columns, *days_columns]
    dataframe[int_columns] = dataframe[int_columns].astype("int64")

    dataframe["match_date"] = dataframe["match_date"].dt.date
    dataframe = dataframe.sort_values(["match_date", "match_id"]).reset_index(drop=True)
    return dataframe[DATASET_COLUMNS]


def clean_dataset_dataframe_v2(dataframe: pd.DataFrame) -> pd.DataFrame:
    cleaned = clean_dataset_dataframe(dataframe)
    if cleaned.empty:
        return pd.DataFrame(columns=V2_DATASET_COLUMNS)

    for column in RANK_POINTS_COLUMNS:
        if column not in cleaned.columns:
            cleaned[column] = pd.NA

    rank_points_columns = ["player_1_rank_points", "player_2_rank_points"]
    cleaned[rank_points_columns] = cleaned[rank_points_columns].fillna(0)
    cleaned["rank_points_diff"] = (
        cleaned["player_1_rank_points"] - cleaned["player_2_rank_points"]
    )
    cleaned[rank_points_columns + ["rank_points_diff"]] = cleaned[
        rank_points_columns + ["rank_points_diff"]
    ].astype("int64")
    return cleaned[V2_DATASET_COLUMNS]


def build_dataset_dataframe_v2(
    db: Session,
    rankings_dir: str | Path = ATP_DATA_DIR,
    match_mapping_path: str | Path = MATCH_MAPPING_PATH,
    base_dataset_path: str | Path | None = None,
) -> pd.DataFrame:
    resolved_base_path = Path(base_dataset_path) if base_dataset_path is not None else PROCESSED_DATA_DIR / DATASET_VERSIONS["v1"].base_dataset
    if not resolved_base_path.exists():
        resolved_base_path = PROCESSED_DATA_DIR / "tennis_winner_dataset_v2.csv"
    ranking_lookup = build_historical_ranking_lookup(
        rankings_dir,
        match_mapping_path,
        base_dataset_path=resolved_base_path if resolved_base_path.exists() else None,
    )
    raw_dataframe = legacy_match_rows_to_dataframe_v2(
        load_legacy_match_rows(db),
        ranking_lookup=ranking_lookup,
    )
    return clean_dataset_dataframe_v2(raw_dataframe)


def summarize_v2_dataset(dataframe: pd.DataFrame) -> V2DatasetSummary:
    base_summary = summarize_dataset(dataframe)
    if dataframe.empty:
        return V2DatasetSummary(
            total_rows=base_summary.total_rows,
            total_columns=len(V2_DATASET_COLUMNS),
            target_percentages=base_summary.target_percentages,
            null_counts=base_summary.null_counts,
            date_min=base_summary.date_min,
            date_max=base_summary.date_max,
            elo_min=None,
            elo_max=None,
            non_default_elo_pct=0.0,
            non_default_rank_pct=0.0,
            ranking_fallback_note=WTA_RANKING_FALLBACK_NOTE,
        )

    elo_values = pd.concat(
        [
            pd.to_numeric(dataframe["player_1_elo"], errors="coerce"),
            pd.to_numeric(dataframe["player_2_elo"], errors="coerce"),
        ],
        ignore_index=True,
    )
    rank_values = pd.concat(
        [
            pd.to_numeric(dataframe["player_1_rank"], errors="coerce"),
            pd.to_numeric(dataframe["player_2_rank"], errors="coerce"),
        ],
        ignore_index=True,
    )
    non_default_elo = (
        (elo_values != DEFAULT_ELO_VALUE).sum() / len(elo_values) * 100 if len(elo_values) else 0.0
    )
    non_default_rank = (
        (rank_values != MISSING_RANK_VALUE).sum() / len(rank_values) * 100 if len(rank_values) else 0.0
    )
    return V2DatasetSummary(
        total_rows=base_summary.total_rows,
        total_columns=len(V2_DATASET_COLUMNS),
        target_percentages=base_summary.target_percentages,
        null_counts=base_summary.null_counts,
        date_min=base_summary.date_min,
        date_max=base_summary.date_max,
        elo_min=float(elo_values.min()) if not elo_values.empty else None,
        elo_max=float(elo_values.max()) if not elo_values.empty else None,
        non_default_elo_pct=round(float(non_default_elo), 2),
        non_default_rank_pct=round(float(non_default_rank), 2),
        ranking_fallback_note=WTA_RANKING_FALLBACK_NOTE,
    )


def format_v2_dataset_summary(summary: V2DatasetSummary) -> str:
    base = format_dataset_summary(summary)
    return "\n".join(
        [
            base,
            f"Elo min/max: {summary.elo_min} / {summary.elo_max}",
            f"Righe con Elo non-default: {summary.non_default_elo_pct:.2f}%",
            f"Righe con rank ATP storico: {summary.non_default_rank_pct:.2f}%",
            f"Nota ranking: {summary.ranking_fallback_note}",
        ]
    )


def build_dataset_dataframe(db: Session) -> pd.DataFrame:
    return clean_dataset_dataframe(
        legacy_match_rows_to_dataframe(load_legacy_match_rows(db))
    )


def summarize_dataset(dataframe: pd.DataFrame) -> DatasetSummary:
    if dataframe.empty:
        return DatasetSummary(
            total_rows=0,
            total_columns=len(dataframe.columns),
            target_percentages={1: 0.0, 0: 0.0},
            null_counts=dataframe.isna().sum().astype(int).to_dict(),
            date_min=None,
            date_max=None,
        )

    target_percentages = (
        dataframe[TARGET_COLUMN]
        .value_counts(normalize=True)
        .reindex([1, 0], fill_value=0.0)
        .mul(100)
        .round(2)
        .to_dict()
    )
    match_dates = pd.to_datetime(dataframe["match_date"], errors="coerce")
    return DatasetSummary(
        total_rows=len(dataframe),
        total_columns=len(dataframe.columns),
        target_percentages={
            int(key): float(value) for key, value in target_percentages.items()
        },
        null_counts=dataframe.isna().sum().astype(int).to_dict(),
        date_min=match_dates.min().date() if not match_dates.isna().all() else None,
        date_max=match_dates.max().date() if not match_dates.isna().all() else None,
    )


def format_dataset_summary(summary: DatasetSummary) -> str:
    null_lines = "\n".join(
        f"  - {column}: {count}" for column, count in summary.null_counts.items()
    )
    date_range = (
        f"{summary.date_min} -> {summary.date_max}"
        if summary.date_min and summary.date_max
        else "n/a"
    )
    return "\n".join(
        [
            f"Righe totali: {summary.total_rows}",
            f"Colonne totali: {summary.total_columns}",
            "Target:",
            f"  - 1: {summary.target_percentages.get(1, 0.0):.2f}%",
            f"  - 0: {summary.target_percentages.get(0, 0.0):.2f}%",
            "Valori null per colonna:",
            null_lines or "  - nessuna colonna",
            f"Range date dataset: {date_range}",
        ]
    )


def split_features_target(
    dataframe: pd.DataFrame,
    target_column: str = TARGET_COLUMN,
) -> tuple[pd.DataFrame, pd.Series]:
    if target_column not in dataframe.columns:
        raise ValueError(f"Target column '{target_column}' not found in dataframe.")
    feature_columns = [
        column
        for column in dataframe.columns
        if column not in EXCLUDED_FEATURE_COLUMNS
    ]
    return dataframe[feature_columns], dataframe[target_column]


def export_dataset_csv(
    dataframe: pd.DataFrame,
    output_dir: str | Path = "backend/data/processed",
    filename: str = "tennis_features.csv",
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / filename
    dataframe.to_csv(csv_path, index=False)
    return csv_path


def build_and_export_dataset(
    db: Session,
    output_dir: str | Path = "backend/data/processed",
    filename: str = "tennis_features.csv",
) -> Path:
    return build_and_export_dataset_report(
        db=db,
        output_dir=output_dir,
        filename=filename,
    ).csv_path


def build_and_export_dataset_report(
    db: Session,
    output_dir: str | Path = "backend/data/processed",
    filename: str = "tennis_winner_dataset.csv",
) -> DatasetBuildResult:
    dataframe = build_dataset_dataframe(db)
    csv_path = export_dataset_csv(dataframe, output_dir=output_dir, filename=filename)
    return DatasetBuildResult(
        csv_path=csv_path,
        dataframe=dataframe,
        summary=summarize_dataset(dataframe),
    )


def build_and_export_dataset_report_v2(
    db: Session,
    output_dir: str | Path = "backend/data/processed",
    filename: str = "tennis_winner_dataset_v2.csv",
    rankings_dir: str | Path = ATP_DATA_DIR,
    match_mapping_path: str | Path = MATCH_MAPPING_PATH,
) -> DatasetBuildResult:
    dataframe = build_dataset_dataframe_v2(
        db,
        rankings_dir=rankings_dir,
        match_mapping_path=match_mapping_path,
    )
    csv_path = export_dataset_csv(dataframe, output_dir=output_dir, filename=filename)
    return DatasetBuildResult(
        csv_path=csv_path,
        dataframe=dataframe,
        summary=summarize_v2_dataset(dataframe),
    )
