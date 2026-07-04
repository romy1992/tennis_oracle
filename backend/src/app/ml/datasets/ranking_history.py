"""Historical ATP ranking lookup for pre-match features.

Anti-leakage rule:
- Use the latest ATP ranking row where ranking_date <= match_date.
- ATP rankings are weekly (typically Monday); on ranking day the published
  rank is treated as the official pre-match rank for that week.

WTA fallback:
- No historical WTA dump is available in this pipeline.
- Unmapped or WTA players receive MISSING_RANK_VALUE and missing rank points.
"""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

MISSING_RANK_VALUE = 9999
MISSING_RANK_POINTS = 0
WTA_RANKING_FALLBACK_NOTE = (
    "WTA historical rankings are not available; missing rank sentinel is used "
    "instead of fixture standing snapshots to avoid leakage."
)


@dataclass(frozen=True)
class PreMatchRankFeatures:
    player_1_rank: int
    player_2_rank: int
    rank_diff: int
    player_1_rank_points: int
    player_2_rank_points: int
    rank_points_diff: int


@dataclass(frozen=True)
class RankingSnapshot:
    ranking_date: date
    rank: int
    points: int | None


def ranking_date_to_date(value: int | str) -> date:
    text = str(int(value))
    return datetime.strptime(text, "%Y%m%d").date()


def load_atp_rankings(rankings_dir: str | Path) -> pd.DataFrame:
    rankings_path = Path(rankings_dir)
    frames: list[pd.DataFrame] = []
    for csv_path in sorted(rankings_path.glob("atp_rankings_*.csv")):
        frame = pd.read_csv(csv_path, low_memory=False)
        frame["ranking_date"] = pd.to_numeric(frame["ranking_date"], errors="coerce")
        frame["rank"] = pd.to_numeric(frame["rank"], errors="coerce")
        frame["player"] = pd.to_numeric(frame["player"], errors="coerce")
        if "points" in frame.columns:
            frame["points"] = pd.to_numeric(frame["points"], errors="coerce")
        else:
            frame["points"] = pd.NA
        frames.append(frame[["ranking_date", "rank", "player", "points"]])

    if not frames:
        return pd.DataFrame(columns=["ranking_date", "rank", "player", "points"])

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["ranking_date", "rank", "player"])
    combined["ranking_date"] = combined["ranking_date"].astype(int)
    combined["rank"] = combined["rank"].astype(int)
    combined["player"] = combined["player"].astype(int)
    return combined.sort_values(["player", "ranking_date", "rank"]).reset_index(drop=True)


def build_player_key_to_atp_id_mapping(
    match_mapping_path: str | Path,
    base_dataset_path: str | Path | None = None,
) -> dict[int, int]:
    path = Path(match_mapping_path)
    if not path.exists():
        return {}

    mapping = pd.read_csv(path, low_memory=False)
    required_atp_columns = {"match_id", "match_date", "player_1_atp_id", "player_2_atp_id"}
    if not required_atp_columns.issubset(mapping.columns):
        return {}

    if {"player_1_id", "player_2_id"}.issubset(mapping.columns):
        source = mapping
    else:
        base_path = Path(base_dataset_path) if base_dataset_path is not None else None
        if base_path is None or not base_path.exists():
            return {}
        base = pd.read_csv(
            base_path,
            usecols=["match_id", "match_date", "player_1_id", "player_2_id"],
            low_memory=False,
        )
        mapping["match_date"] = pd.to_datetime(mapping["match_date"], errors="coerce").dt.date.astype(str)
        base["match_date"] = pd.to_datetime(base["match_date"], errors="coerce").dt.date.astype(str)
        source = base.merge(
            mapping[["match_id", "match_date", "player_1_atp_id", "player_2_atp_id"]],
            on=["match_id", "match_date"],
            how="inner",
        )

    player_to_atp: dict[int, int] = {}
    for side in ("1", "2"):
        player_col = f"player_{side}_id"
        atp_col = f"player_{side}_atp_id"
        pairs = source[[player_col, atp_col]].dropna()
        for player_key, atp_id in pairs.itertuples(index=False):
            player_to_atp[int(player_key)] = int(atp_id)
    return player_to_atp


class HistoricalRankingLookup:
    def __init__(
        self,
        rankings: pd.DataFrame,
        player_key_to_atp_id: dict[int, int] | None = None,
    ) -> None:
        self.player_key_to_atp_id = player_key_to_atp_id or {}
        self._by_atp_id: dict[int, list[RankingSnapshot]] = {}
        if rankings.empty:
            return

        for atp_id, group in rankings.groupby("player"):
            snapshots = sorted(
                [
                    RankingSnapshot(
                        ranking_date=ranking_date_to_date(row.ranking_date),
                        rank=int(row.rank),
                        points=int(row.points) if pd.notna(row.points) else None,
                    )
                    for row in group.itertuples(index=False)
                ],
                key=lambda snapshot: snapshot.ranking_date,
            )
            self._by_atp_id[int(atp_id)] = snapshots

    def lookup_atp_player(self, atp_player_id: int, match_date: date) -> tuple[int, int]:
        snapshots = self._by_atp_id.get(atp_player_id, [])
        selected: RankingSnapshot | None = None
        for snapshot in snapshots:
            if snapshot.ranking_date <= match_date:
                selected = snapshot
            else:
                break
        if selected is None:
            return MISSING_RANK_VALUE, MISSING_RANK_POINTS
        points = selected.points if selected.points is not None else MISSING_RANK_POINTS
        return selected.rank, points

    def lookup_player_key(self, player_key: int, match_date: date) -> tuple[int, int]:
        atp_player_id = self.player_key_to_atp_id.get(player_key)
        if atp_player_id is None:
            return MISSING_RANK_VALUE, MISSING_RANK_POINTS
        return self.lookup_atp_player(atp_player_id, match_date)

    def pre_match_features(
        self,
        player_1_id: int,
        player_2_id: int,
        match_date: date,
    ) -> PreMatchRankFeatures:
        player_1_rank, player_1_points = self.lookup_player_key(player_1_id, match_date)
        player_2_rank, player_2_points = self.lookup_player_key(player_2_id, match_date)
        return PreMatchRankFeatures(
            player_1_rank=player_1_rank,
            player_2_rank=player_2_rank,
            rank_diff=player_1_rank - player_2_rank,
            player_1_rank_points=player_1_points,
            player_2_rank_points=player_2_points,
            rank_points_diff=player_1_points - player_2_points,
        )


def build_historical_ranking_lookup(
    rankings_dir: str | Path,
    match_mapping_path: str | Path,
    base_dataset_path: str | Path | None = None,
) -> HistoricalRankingLookup:
    rankings = load_atp_rankings(rankings_dir)
    player_mapping = build_player_key_to_atp_id_mapping(match_mapping_path, base_dataset_path)
    return HistoricalRankingLookup(rankings, player_mapping)
