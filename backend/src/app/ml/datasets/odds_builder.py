from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.src.entity import Fixture


MATCH_WINNER_MARKET = "Home/Away"
HOME_SELECTION = "Home"
AWAY_SELECTION = "Away"
ODDS_DATASET_FILENAME = "tennis_match_winner_odds.csv"
DATASET_WITH_ODDS_FILENAME = "tennis_winner_dataset_with_odds.csv"
ATP_ENRICHED_DATASET_FILENAME = "tennis_winner_dataset_atp_enriched.csv"
BASE_DATASET_FILENAME = "tennis_winner_dataset.csv"


@dataclass(frozen=True)
class FixtureOddsRecord:
    match_id: int
    match_date: date | str | None
    player_1_id: int | None
    player_2_id: int | None
    player_1_name: str | None
    player_2_name: str | None
    odds: Any
    event_live: Any = None


@dataclass(frozen=True)
class MatchWinnerOddsAverage:
    avg_player_1_odds: float
    avg_player_2_odds: float
    odds_bookmaker_count: int


@dataclass(frozen=True)
class OddsBuildSummary:
    fixture_total_rows: int
    fixture_rows_with_odds: int
    exported_rows: int
    unique_matches: int
    unique_bookmakers: int
    markets_available: dict[str, int]
    bookmakers_available: dict[str, int]
    usable_match_winner_rows: int
    usable_match_winner_pct: float
    top_bookmakers: dict[str, int]
    date_min: str | None
    date_max: str | None
    null_counts: dict[str, int]
    with_odds_dataset_rows: int
    source_dataset_path: Path | None


@dataclass(frozen=True)
class OddsBuildResult:
    odds_csv_path: Path
    with_odds_dataset_path: Path | None
    odds_dataframe: pd.DataFrame
    with_odds_dataframe: pd.DataFrame | None
    summary: OddsBuildSummary


def decimal_odd(value: Any) -> float | None:
    if value is None:
        return None
    try:
        odd = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    if odd <= 1:
        return None
    return odd


def implied_probability(odd: float) -> float:
    return 1.0 / odd


def bookmaker_margin(player_1_odd: float, player_2_odd: float) -> float:
    return implied_probability(player_1_odd) + implied_probability(player_2_odd) - 1.0


def no_vig_market_probabilities(player_1_odd: float, player_2_odd: float) -> tuple[float, float]:
    implied_1 = implied_probability(player_1_odd)
    implied_2 = implied_probability(player_2_odd)
    total = implied_1 + implied_2
    if total <= 0:
        raise ValueError("Implied probability total must be positive.")
    return implied_1 / total, implied_2 / total


def profit_for_unit_stake(odd: float, won: bool) -> float:
    return odd - 1.0 if won else -1.0


def roi(profits: Iterable[float], stakes: Iterable[float] | None = None) -> float:
    profit_values = list(profits)
    stake_values = list(stakes) if stakes is not None else [1.0] * len(profit_values)
    total_stake = sum(stake_values)
    if total_stake == 0:
        return 0.0
    return sum(profit_values) / total_stake


def yield_rate(profits: Iterable[float], stakes: Iterable[float] | None = None) -> float:
    return roi(profits, stakes)


def hit_rate(results: Iterable[bool]) -> float:
    result_values = list(results)
    if not result_values:
        return 0.0
    return sum(1 for result in result_values if result) / len(result_values)


def bet_count(profits: Iterable[float]) -> int:
    return len(list(profits))


def is_live_or_in_play(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text not in {"", "0", "false", "no", "none", "prematch", "pre-match"}


def odds_payload_has_live_flag(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            clean_key = str(key).strip().lower().replace("_", "-")
            if clean_key in {"live", "in-play", "inplay", "is-live"} and is_live_or_in_play(value):
                return True
            if odds_payload_has_live_flag(value):
                return True
    elif isinstance(payload, list):
        return any(odds_payload_has_live_flag(item) for item in payload)
    return False


def normalized_odds_payload(payload: Any, match_id: int | str | None = None) -> Any:
    if not isinstance(payload, dict):
        return payload

    if MATCH_WINNER_MARKET in payload:
        return payload

    if match_id is not None:
        nested = payload.get(str(match_id)) or payload.get(match_id)
        if isinstance(nested, dict):
            return nested

    if len(payload) == 1:
        nested = next(iter(payload.values()))
        if isinstance(nested, dict):
            return nested

    return payload


def odds_markets(payload: Any) -> list[str]:
    clean_payload = normalized_odds_payload(payload)
    if not isinstance(clean_payload, dict):
        return []
    return [str(market) for market in clean_payload.keys()]


def match_winner_bookmakers(payload: Any) -> list[str]:
    clean_payload = normalized_odds_payload(payload)
    market = clean_payload.get(MATCH_WINNER_MARKET) if isinstance(clean_payload, dict) else None
    if not isinstance(market, dict):
        return []
    home = market.get(HOME_SELECTION)
    away = market.get(AWAY_SELECTION)
    if not isinstance(home, dict) or not isinstance(away, dict):
        return []
    return sorted(set(home).intersection(away))


def match_winner_rows_from_record(record: FixtureOddsRecord) -> list[dict[str, Any]]:
    payload = normalized_odds_payload(record.odds, match_id=record.match_id)
    if not isinstance(payload, dict):
        return []
    if is_live_or_in_play(record.event_live) or odds_payload_has_live_flag(payload):
        return []

    market = payload.get(MATCH_WINNER_MARKET)
    if not isinstance(market, dict):
        return []

    home = market.get(HOME_SELECTION)
    away = market.get(AWAY_SELECTION)
    if not isinstance(home, dict) or not isinstance(away, dict):
        return []

    rows: list[dict[str, Any]] = []
    for bookmaker in sorted(set(home).intersection(away)):
        player_1_odds = decimal_odd(home.get(bookmaker))
        player_2_odds = decimal_odd(away.get(bookmaker))
        if player_1_odds is None or player_2_odds is None:
            continue

        implied_1 = implied_probability(player_1_odds)
        implied_2 = implied_probability(player_2_odds)
        market_prob_1, market_prob_2 = no_vig_market_probabilities(player_1_odds, player_2_odds)
        rows.append(
            {
                "match_id": record.match_id,
                "match_date": _date_to_iso(record.match_date),
                "player_1_id": record.player_1_id,
                "player_2_id": record.player_2_id,
                "player_1_name": record.player_1_name,
                "player_2_name": record.player_2_name,
                "bookmaker": str(bookmaker),
                "player_1_odds": player_1_odds,
                "player_2_odds": player_2_odds,
                "implied_prob_player_1_raw": implied_1,
                "implied_prob_player_2_raw": implied_2,
                "bookmaker_margin": implied_1 + implied_2 - 1.0,
                "market_prob_player_1": market_prob_1,
                "market_prob_player_2": market_prob_2,
            }
        )
    return rows


def average_match_winner_odds_from_record(
    record: FixtureOddsRecord,
) -> MatchWinnerOddsAverage | None:
    rows = match_winner_rows_from_record(record)
    if not rows:
        return None

    bookmakers = {row["bookmaker"] for row in rows}
    return MatchWinnerOddsAverage(
        avg_player_1_odds=sum(row["player_1_odds"] for row in rows) / len(rows),
        avg_player_2_odds=sum(row["player_2_odds"] for row in rows) / len(rows),
        odds_bookmaker_count=len(bookmakers),
    )


def odds_records_to_dataframe(records: Iterable[FixtureOddsRecord]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(match_winner_rows_from_record(record))
    return pd.DataFrame(rows, columns=_odds_columns())


def aggregate_match_odds(odds_dataframe: pd.DataFrame) -> pd.DataFrame:
    if odds_dataframe.empty:
        return pd.DataFrame(
            columns=[
                "match_id",
                "match_date",
                "avg_player_1_odds",
                "avg_player_2_odds",
                "avg_market_prob_player_1",
                "avg_market_prob_player_2",
                "avg_bookmaker_margin",
                "odds_bookmaker_count",
            ]
        )

    clean = odds_dataframe.copy()
    clean["match_date"] = _series_date_to_iso(clean["match_date"])
    grouped = (
        clean.groupby(["match_id", "match_date"], dropna=False)
        .agg(
            avg_player_1_odds=("player_1_odds", "mean"),
            avg_player_2_odds=("player_2_odds", "mean"),
            avg_market_prob_player_1=("market_prob_player_1", "mean"),
            avg_market_prob_player_2=("market_prob_player_2", "mean"),
            avg_bookmaker_margin=("bookmaker_margin", "mean"),
            odds_bookmaker_count=("bookmaker", "nunique"),
        )
        .reset_index()
    )
    return grouped


def attach_odds_to_dataset(dataset: pd.DataFrame, odds_dataframe: pd.DataFrame) -> pd.DataFrame:
    output = dataset.copy()
    if "match_id" not in output.columns or "match_date" not in output.columns:
        return output

    output["match_date"] = _series_date_to_iso(output["match_date"])
    aggregated = aggregate_match_odds(odds_dataframe)
    merged = output.merge(aggregated, on=["match_id", "match_date"], how="left", validate="one_to_one")
    merged["market_prob_player_1"] = merged["avg_market_prob_player_1"]
    merged["market_prob_player_2"] = merged["avg_market_prob_player_2"]

    if "target_player_1_win" in merged.columns:
        target = pd.to_numeric(merged["target_player_1_win"], errors="coerce")
        merged["market_edge_baseline_player_1"] = target - merged["market_prob_player_1"]
        merged["player_1_profit_if_bet"] = merged.apply(
            lambda row: profit_for_unit_stake(row["avg_player_1_odds"], row["target_player_1_win"] == 1)
            if pd.notna(row.get("avg_player_1_odds")) and pd.notna(row.get("target_player_1_win"))
            else pd.NA,
            axis=1,
        )
        merged["player_2_profit_if_bet"] = merged.apply(
            lambda row: profit_for_unit_stake(row["avg_player_2_odds"], row["target_player_1_win"] == 0)
            if pd.notna(row.get("avg_player_2_odds")) and pd.notna(row.get("target_player_1_win"))
            else pd.NA,
            axis=1,
        )
    else:
        merged["market_edge_baseline_player_1"] = pd.NA
        merged["player_1_profit_if_bet"] = pd.NA
        merged["player_2_profit_if_bet"] = pd.NA

    return merged


def inspect_odds_payloads(records: Iterable[FixtureOddsRecord]) -> tuple[dict[str, int], dict[str, int], int]:
    market_counts: dict[str, int] = {}
    bookmaker_counts: dict[str, int] = {}
    usable_rows = 0

    for record in records:
        payload = normalized_odds_payload(record.odds, match_id=record.match_id)
        if not isinstance(payload, dict):
            continue
        for market in odds_markets(payload):
            market_counts[market] = market_counts.get(market, 0) + 1
        usable_bookmakers = 0
        for bookmaker in match_winner_bookmakers(payload):
            market = payload[MATCH_WINNER_MARKET]
            home = market[HOME_SELECTION]
            away = market[AWAY_SELECTION]
            if decimal_odd(home.get(bookmaker)) is None or decimal_odd(away.get(bookmaker)) is None:
                continue
            bookmaker_counts[str(bookmaker)] = bookmaker_counts.get(str(bookmaker), 0) + 1
            usable_bookmakers += 1
        usable_rows += int(usable_bookmakers > 0)

    return market_counts, bookmaker_counts, usable_rows


def load_fixture_odds_records(db: Session) -> list[FixtureOddsRecord]:
    rows = db.execute(
        select(
            Fixture.event_key,
            Fixture.event_date,
            Fixture.first_player_key,
            Fixture.second_player_key,
            Fixture.event_first_player,
            Fixture.event_second_player,
            Fixture.odds,
            Fixture.event_live,
        ).where(Fixture.odds.is_not(None))
    ).all()
    return [
        FixtureOddsRecord(
            match_id=row.event_key,
            match_date=row.event_date,
            player_1_id=row.first_player_key,
            player_2_id=row.second_player_key,
            player_1_name=row.event_first_player,
            player_2_name=row.event_second_player,
            odds=row.odds,
            event_live=row.event_live,
        )
        for row in rows
    ]


def build_and_export_odds_dataset(
    db: Session,
    output_dir: str | Path,
    odds_filename: str = ODDS_DATASET_FILENAME,
    with_odds_filename: str = DATASET_WITH_ODDS_FILENAME,
    dataset_version: str = "v1",
) -> OddsBuildResult:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    fixture_total_rows = int(db.scalar(select(func.count()).select_from(Fixture)) or 0)
    fixture_rows_with_odds = int(
        db.scalar(select(func.count()).select_from(Fixture).where(Fixture.odds.is_not(None))) or 0
    )
    records = load_fixture_odds_records(db)
    markets_available, bookmakers_available, usable_match_winner_rows = inspect_odds_payloads(records)
    odds_dataframe = odds_records_to_dataframe(records)

    odds_csv_path = output_path / odds_filename
    odds_dataframe.to_csv(odds_csv_path, index=False)

    source_dataset_path = select_source_dataset_path(output_path, version=dataset_version)
    with_odds_dataframe: pd.DataFrame | None = None
    with_odds_dataset_path: Path | None = None
    if source_dataset_path is not None:
        dataset = pd.read_csv(source_dataset_path, low_memory=False)
        with_odds_dataframe = attach_odds_to_dataset(dataset, odds_dataframe)
        with_odds_dataset_path = output_path / with_odds_filename
        with_odds_dataframe.to_csv(with_odds_dataset_path, index=False)

    date_min, date_max = _date_range(odds_dataframe)
    summary = OddsBuildSummary(
        fixture_total_rows=fixture_total_rows,
        fixture_rows_with_odds=fixture_rows_with_odds,
        exported_rows=int(len(odds_dataframe)),
        unique_matches=int(odds_dataframe["match_id"].nunique()) if not odds_dataframe.empty else 0,
        unique_bookmakers=int(odds_dataframe["bookmaker"].nunique()) if not odds_dataframe.empty else 0,
        markets_available=dict(sorted(markets_available.items(), key=lambda item: item[1], reverse=True)),
        bookmakers_available=dict(sorted(bookmakers_available.items(), key=lambda item: item[1], reverse=True)),
        usable_match_winner_rows=usable_match_winner_rows,
        usable_match_winner_pct=round(
            (usable_match_winner_rows / fixture_rows_with_odds) * 100,
            2,
        )
        if fixture_rows_with_odds
        else 0.0,
        top_bookmakers=dict(
            sorted(bookmakers_available.items(), key=lambda item: item[1], reverse=True)[:10]
        ),
        date_min=date_min,
        date_max=date_max,
        null_counts={column: int(count) for column, count in odds_dataframe.isna().sum().items()},
        with_odds_dataset_rows=int(len(with_odds_dataframe)) if with_odds_dataframe is not None else 0,
        source_dataset_path=source_dataset_path,
    )

    return OddsBuildResult(
        odds_csv_path=odds_csv_path,
        with_odds_dataset_path=with_odds_dataset_path,
        odds_dataframe=odds_dataframe,
        with_odds_dataframe=with_odds_dataframe,
        summary=summary,
    )


def select_source_dataset_path(
    output_dir: str | Path,
    version: str = "v1",
) -> Path | None:
    output_path = Path(output_dir)
    if version == "v2":
        candidates = (
            "tennis_winner_dataset_atp_enriched_v2.csv",
            "tennis_winner_dataset_v2.csv",
        )
    else:
        candidates = (ATP_ENRICHED_DATASET_FILENAME, BASE_DATASET_FILENAME)

    for filename in candidates:
        candidate = output_path / filename
        if candidate.exists():
            return candidate
    return None


def format_odds_summary(summary: OddsBuildSummary) -> str:
    lines = [
        f"Righe fixture totali: {summary.fixture_total_rows}",
        f"Righe fixture con odds non null: {summary.fixture_rows_with_odds}",
        f"Righe odds esportate: {summary.exported_rows}",
        f"Match unici coperti: {summary.unique_matches}",
        f"Bookmaker unici: {summary.unique_bookmakers}",
        f"Percentuale odds utilizzabili match winner: {summary.usable_match_winner_pct}%",
        f"Range date: {summary.date_min or '-'} / {summary.date_max or '-'}",
        f"Righe dataset con odds: {summary.with_odds_dataset_rows}",
    ]
    if summary.source_dataset_path:
        lines.append(f"Dataset sorgente: {summary.source_dataset_path}")
    lines.append(f"Top bookmaker per copertura: {summary.top_bookmakers}")
    lines.append(f"Mercati disponibili: {dict(list(summary.markets_available.items())[:20])}")
    lines.append(f"Bookmaker disponibili: {dict(list(summary.bookmakers_available.items())[:20])}")
    lines.append(f"Null per colonna: {summary.null_counts}")
    return "\n".join(lines)


def _odds_columns() -> list[str]:
    return [
        "match_id",
        "match_date",
        "player_1_id",
        "player_2_id",
        "player_1_name",
        "player_2_name",
        "bookmaker",
        "player_1_odds",
        "player_2_odds",
        "implied_prob_player_1_raw",
        "implied_prob_player_2_raw",
        "bookmaker_margin",
        "market_prob_player_1",
        "market_prob_player_2",
    ]


def _date_to_iso(value: date | datetime | str | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.date().isoformat()


def _series_date_to_iso(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date.astype("string")


def _date_range(dataframe: pd.DataFrame) -> tuple[str | None, str | None]:
    if dataframe.empty or "match_date" not in dataframe.columns:
        return None, None
    dates = pd.to_datetime(dataframe["match_date"], errors="coerce")
    if dates.dropna().empty:
        return None, None
    return dates.min().date().isoformat(), dates.max().date().isoformat()
