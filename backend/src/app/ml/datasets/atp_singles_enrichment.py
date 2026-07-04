import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from backend.src.repository.base.repository_db import engine


logger = logging.getLogger(__name__)

ATP_MATCH_COLUMNS = [
    "atp_source_file",
    "atp_category",
    "atp_tourney_id",
    "atp_tourney_name",
    "atp_surface",
    "atp_draw_size",
    "atp_tourney_level",
    "atp_tourney_date",
    "atp_match_num",
    "atp_round",
    "atp_best_of",
    "atp_score",
    "atp_minutes",
    "winner_atp_id",
    "winner_name",
    "winner_hand",
    "winner_height",
    "winner_ioc",
    "winner_age",
    "winner_rank",
    "winner_rank_points",
    "loser_atp_id",
    "loser_name",
    "loser_hand",
    "loser_height",
    "loser_ioc",
    "loser_age",
    "loser_rank",
    "loser_rank_points",
    "winner_sets",
    "loser_sets",
]

MATCH_EXPORT_COLUMNS = [
    "match_id",
    "match_date",
    "atp_match_found",
    "atp_source_file",
    "atp_category",
    "atp_tourney_id",
    "atp_tourney_name",
    "atp_tourney_date",
    "atp_days_from_tourney_start",
    "atp_tournament_similarity",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
    "atp_best_of",
    "atp_score",
    "atp_minutes",
    "player_1_atp_id",
    "player_2_atp_id",
    "player_1_atp_name",
    "player_2_atp_name",
    "player_1_hand",
    "player_2_hand",
    "player_1_height",
    "player_2_height",
    "height_diff",
    "player_1_age",
    "player_2_age",
    "age_diff",
    "player_1_ioc",
    "player_2_ioc",
    "player_1_atp_rank",
    "player_2_atp_rank",
    "atp_rank_diff",
    "player_1_atp_rank_points",
    "player_2_atp_rank_points",
    "atp_rank_points_diff",
]


@dataclass(frozen=True)
class AtpSinglesBuildResult:
    atp_matches_csv: Path
    atp_match_mapping_csv: Path
    atp_player_mapping_csv: Path
    enriched_dataset_csv: Path | None
    atp_rows: int
    fixture_rows: int
    matched_rows: int
    enriched_rows: int


def normalise_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text_value = str(value).replace("&apos;", "'")
    text_value = (
        unicodedata.normalize("NFKD", text_value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
        .replace(".", " ")
    )
    text_value = re.sub(r"[^a-z0-9\s'-]", " ", text_value)
    return re.sub(r"\s+", " ", text_value).strip()


def short_player_name(value: object) -> str:
    parts = normalise_text(value).split()
    if len(parts) <= 1:
        return normalise_text(value)
    return f"{parts[0][0]} {parts[-1]}"


def set_score_from_atp_score(score: object) -> tuple[int, int] | None:
    if score is None or pd.isna(score):
        return None

    winner_sets = 0
    loser_sets = 0
    for token in str(score).split():
        clean_token = token.strip()
        if "-" not in clean_token:
            continue
        match = re.match(r"^(\d+)-(\d+)", clean_token)
        if not match:
            continue
        left_games = int(match.group(1))
        right_games = int(match.group(2))
        if left_games > right_games:
            winner_sets += 1
        elif right_games > left_games:
            loser_sets += 1

    if winner_sets == 0 and loser_sets == 0:
        return None
    return winner_sets, loser_sets


def normalise_fixture_result(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    match = re.search(r"(\d+)\s*-\s*(\d+)", str(value))
    if not match:
        return ""
    return f"{int(match.group(1))} - {int(match.group(2))}"


def tournament_similarity(left: object, right: object) -> float:
    left_tokens = set(normalise_text(left).split())
    right_tokens = set(normalise_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def atp_category_for_file(path: Path) -> str:
    if path.name.startswith("atp_matches_qual_chall_"):
        return "qual_chall"
    if path.name.startswith("atp_matches_futures_"):
        return "futures"
    return "tour_main"


def iter_atp_singles_files(atp_data_dir: Path) -> list[Path]:
    files = []
    for path in atp_data_dir.glob("atp_matches_*.csv"):
        if path.name.startswith("atp_matches_doubles_"):
            continue
        files.append(path)
    return sorted(files)


def load_atp_singles_matches(atp_data_dir: Path) -> pd.DataFrame:
    frames = []
    for path in iter_atp_singles_files(atp_data_dir):
        frame = pd.read_csv(path, low_memory=False)
        frame["atp_source_file"] = path.name
        frame["atp_category"] = atp_category_for_file(path)
        frames.append(frame)

    if not frames:
        return pd.DataFrame(columns=ATP_MATCH_COLUMNS)

    dataframe = pd.concat(frames, ignore_index=True)
    set_scores = dataframe["score"].map(set_score_from_atp_score)
    dataframe["winner_sets"] = set_scores.map(lambda value: value[0] if value else pd.NA)
    dataframe["loser_sets"] = set_scores.map(lambda value: value[1] if value else pd.NA)
    dataframe = dataframe.dropna(subset=["winner_sets", "loser_sets"]).copy()

    dataframe["atp_tourney_date"] = pd.to_datetime(
        dataframe["tourney_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    )
    dataframe["winner_short_name"] = dataframe["winner_name"].map(short_player_name)
    dataframe["loser_short_name"] = dataframe["loser_name"].map(short_player_name)

    dataframe = dataframe.rename(
        columns={
            "tourney_id": "atp_tourney_id",
            "tourney_name": "atp_tourney_name",
            "surface": "atp_surface",
            "draw_size": "atp_draw_size",
            "tourney_level": "atp_tourney_level",
            "match_num": "atp_match_num",
            "round": "atp_round",
            "best_of": "atp_best_of",
            "score": "atp_score",
            "minutes": "atp_minutes",
            "winner_id": "winner_atp_id",
            "winner_ht": "winner_height",
            "loser_id": "loser_atp_id",
            "loser_ht": "loser_height",
        }
    )

    return dataframe


def export_atp_matches_csv(
    atp_matches: pd.DataFrame,
    output_dir: Path,
    filename: str = "atp_singles_matches_normalized.csv",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename
    atp_matches[ATP_MATCH_COLUMNS].to_csv(output_path, index=False)
    return output_path


def _fixture_query() -> str:
    return """
        select
            f.event_key as match_id,
            f.event_date as match_date,
            f.event_first_player,
            f.first_player_key as player_1_id,
            f.event_second_player,
            f.second_player_key as player_2_id,
            f.event_winner,
            f.event_final_result,
            f.event_type_type,
            f.tournament_name,
            t.tournament_sourface as surface
        from fixture f
        left join tournament t on t.tournament_key = f.tournament_key
        where f.event_date is not null
          and f.first_player_key is not null
          and f.second_player_key is not null
          and f.event_winner in ('First Player', 'Second Player')
          and f.event_final_result is not null
          and f.event_final_result <> '-'
          and f.event_type_type in (
              'Atp Singles',
              'Challenger Men Singles',
              'Itf Men Singles'
          )
    """


def load_atp_candidate_fixtures() -> pd.DataFrame:
    with engine.connect() as connection:
        dataframe = pd.read_sql_query(text(_fixture_query()), connection)

    dataframe["match_date"] = pd.to_datetime(dataframe["match_date"], errors="coerce")
    dataframe["player_1_short_name"] = dataframe["event_first_player"].map(short_player_name)
    dataframe["player_2_short_name"] = dataframe["event_second_player"].map(short_player_name)
    dataframe["fixture_result"] = dataframe["event_final_result"].map(
        normalise_fixture_result
    )
    dataframe["target_player_1_win"] = (
        dataframe["event_winner"] == "First Player"
    ).astype(int)
    return dataframe.dropna(subset=["match_date"]).copy()


def orient_atp_matches_for_fixture_join(atp_matches: pd.DataFrame) -> pd.DataFrame:
    winner_as_player_1 = pd.DataFrame(
        {
            "player_1_short_name": atp_matches["winner_short_name"],
            "player_2_short_name": atp_matches["loser_short_name"],
            "fixture_result": (
                atp_matches["winner_sets"].astype("Int64").astype(str)
                + " - "
                + atp_matches["loser_sets"].astype("Int64").astype(str)
            ),
            "target_player_1_win": 1,
            "player_1_atp_id": atp_matches["winner_atp_id"],
            "player_2_atp_id": atp_matches["loser_atp_id"],
            "player_1_atp_name": atp_matches["winner_name"],
            "player_2_atp_name": atp_matches["loser_name"],
            "player_1_hand": atp_matches["winner_hand"],
            "player_2_hand": atp_matches["loser_hand"],
            "player_1_height": atp_matches["winner_height"],
            "player_2_height": atp_matches["loser_height"],
            "player_1_age": atp_matches["winner_age"],
            "player_2_age": atp_matches["loser_age"],
            "player_1_ioc": atp_matches["winner_ioc"],
            "player_2_ioc": atp_matches["loser_ioc"],
            "player_1_atp_rank": atp_matches["winner_rank"],
            "player_2_atp_rank": atp_matches["loser_rank"],
            "player_1_atp_rank_points": atp_matches["winner_rank_points"],
            "player_2_atp_rank_points": atp_matches["loser_rank_points"],
        }
    )
    loser_as_player_1 = pd.DataFrame(
        {
            "player_1_short_name": atp_matches["loser_short_name"],
            "player_2_short_name": atp_matches["winner_short_name"],
            "fixture_result": (
                atp_matches["loser_sets"].astype("Int64").astype(str)
                + " - "
                + atp_matches["winner_sets"].astype("Int64").astype(str)
            ),
            "target_player_1_win": 0,
            "player_1_atp_id": atp_matches["loser_atp_id"],
            "player_2_atp_id": atp_matches["winner_atp_id"],
            "player_1_atp_name": atp_matches["loser_name"],
            "player_2_atp_name": atp_matches["winner_name"],
            "player_1_hand": atp_matches["loser_hand"],
            "player_2_hand": atp_matches["winner_hand"],
            "player_1_height": atp_matches["loser_height"],
            "player_2_height": atp_matches["winner_height"],
            "player_1_age": atp_matches["loser_age"],
            "player_2_age": atp_matches["winner_age"],
            "player_1_ioc": atp_matches["loser_ioc"],
            "player_2_ioc": atp_matches["winner_ioc"],
            "player_1_atp_rank": atp_matches["loser_rank"],
            "player_2_atp_rank": atp_matches["winner_rank"],
            "player_1_atp_rank_points": atp_matches["loser_rank_points"],
            "player_2_atp_rank_points": atp_matches["winner_rank_points"],
        }
    )

    common_columns = [
        "atp_source_file",
        "atp_category",
        "atp_tourney_id",
        "atp_tourney_name",
        "atp_tourney_date",
        "atp_surface",
        "atp_tourney_level",
        "atp_round",
        "atp_best_of",
        "atp_score",
        "atp_minutes",
    ]
    for column in common_columns:
        winner_as_player_1[column] = atp_matches[column]
        loser_as_player_1[column] = atp_matches[column]

    return pd.concat([winner_as_player_1, loser_as_player_1], ignore_index=True)


def match_fixtures_to_atp(
    fixtures: pd.DataFrame,
    atp_matches: pd.DataFrame,
    max_days_from_tourney_start: int = 20,
) -> pd.DataFrame:
    oriented_atp = orient_atp_matches_for_fixture_join(atp_matches)
    merged = fixtures.merge(
        oriented_atp,
        on=[
            "player_1_short_name",
            "player_2_short_name",
            "fixture_result",
            "target_player_1_win",
        ],
        how="inner",
    )
    if merged.empty:
        return pd.DataFrame(columns=MATCH_EXPORT_COLUMNS)

    merged["atp_days_from_tourney_start"] = (
        merged["match_date"] - merged["atp_tourney_date"]
    ).dt.days
    merged = merged[
        (merged["atp_days_from_tourney_start"] >= 0)
        & (merged["atp_days_from_tourney_start"] <= max_days_from_tourney_start)
    ].copy()
    if merged.empty:
        return pd.DataFrame(columns=MATCH_EXPORT_COLUMNS)

    merged["atp_tournament_similarity"] = [
        tournament_similarity(left, right)
        for left, right in zip(merged["tournament_name"], merged["atp_tourney_name"])
    ]
    merged["atp_match_found"] = 1

    numeric_pairs = [
        ("player_1_height", "player_2_height", "height_diff"),
        ("player_1_age", "player_2_age", "age_diff"),
        ("player_1_atp_rank", "player_2_atp_rank", "atp_rank_diff"),
        (
            "player_1_atp_rank_points",
            "player_2_atp_rank_points",
            "atp_rank_points_diff",
        ),
    ]
    for left, right, diff in numeric_pairs:
        merged[left] = pd.to_numeric(merged[left], errors="coerce")
        merged[right] = pd.to_numeric(merged[right], errors="coerce")
        merged[diff] = merged[left] - merged[right]

    merged = merged.sort_values(
        [
            "match_id",
            "atp_tournament_similarity",
            "atp_days_from_tourney_start",
        ],
        ascending=[True, False, True],
    )
    merged = merged.drop_duplicates(subset=["match_id"], keep="first")
    return merged[MATCH_EXPORT_COLUMNS]


def build_player_mapping(match_mapping: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for side in ("1", "2"):
        rows.append(
            match_mapping[
                [
                    f"player_{side}_atp_id",
                    f"player_{side}_atp_name",
                    f"player_{side}_hand",
                    f"player_{side}_height",
                    f"player_{side}_ioc",
                    "match_id",
                ]
            ].rename(
                columns={
                    f"player_{side}_atp_id": "atp_player_id",
                    f"player_{side}_atp_name": "atp_player_name",
                    f"player_{side}_hand": "hand",
                    f"player_{side}_height": "height",
                    f"player_{side}_ioc": "ioc",
                }
            )
        )
    players = pd.concat(rows, ignore_index=True)
    players = players.dropna(subset=["atp_player_id"])
    grouped = (
        players.groupby(["atp_player_id", "atp_player_name", "hand", "height", "ioc"], dropna=False)
        .agg(matched_matches=("match_id", "nunique"))
        .reset_index()
        .sort_values(["matched_matches", "atp_player_name"], ascending=[False, True])
    )
    return grouped


def export_enriched_dataset(
    base_dataset_path: Path,
    match_mapping: pd.DataFrame,
    output_dir: Path,
    filename: str = "tennis_winner_dataset_atp_enriched.csv",
) -> Path | None:
    if not base_dataset_path.exists():
        logger.warning("Dataset base non trovato: %s", base_dataset_path)
        return None

    base_dataset = pd.read_csv(base_dataset_path, low_memory=False)
    match_mapping = match_mapping.copy()
    base_dataset["match_date"] = pd.to_datetime(
        base_dataset["match_date"],
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    match_mapping["match_date"] = pd.to_datetime(
        match_mapping["match_date"],
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    enriched = base_dataset.merge(match_mapping, on=["match_id", "match_date"], how="left")
    enriched["atp_match_found"] = enriched["atp_match_found"].fillna(0).astype(int)
    output_path = output_dir / filename
    enriched.to_csv(output_path, index=False)
    return output_path


def build_atp_singles_outputs(
    atp_data_dir: Path,
    output_dir: Path,
    base_dataset_filename: str = "tennis_winner_dataset.csv",
) -> AtpSinglesBuildResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Caricamento ATP singles da %s", atp_data_dir)
    atp_matches = load_atp_singles_matches(atp_data_dir)
    atp_matches_csv = export_atp_matches_csv(atp_matches, output_dir)
    logger.info("ATP singles normalizzati: %s righe", len(atp_matches))

    logger.info("Caricamento fixture ATP candidate dal database")
    fixtures = load_atp_candidate_fixtures()
    logger.info("Fixture candidate: %s righe", len(fixtures))

    logger.info("Matching fixture <-> ATP singles")
    match_mapping = match_fixtures_to_atp(fixtures, atp_matches)
    match_mapping_path = output_dir / "atp_singles_match_mapping.csv"
    match_mapping.to_csv(match_mapping_path, index=False)

    player_mapping = build_player_mapping(match_mapping)
    player_mapping_path = output_dir / "atp_singles_player_mapping.csv"
    player_mapping.to_csv(player_mapping_path, index=False)

    enriched_path = export_enriched_dataset(
        output_dir / base_dataset_filename,
        match_mapping,
        output_dir,
    )
    enriched_rows = 0
    if enriched_path:
        enriched_rows = sum(1 for _ in enriched_path.open("rb")) - 1

    return AtpSinglesBuildResult(
        atp_matches_csv=atp_matches_csv,
        atp_match_mapping_csv=match_mapping_path,
        atp_player_mapping_csv=player_mapping_path,
        enriched_dataset_csv=enriched_path,
        atp_rows=len(atp_matches),
        fixture_rows=len(fixtures),
        matched_rows=len(match_mapping),
        enriched_rows=enriched_rows,
    )
