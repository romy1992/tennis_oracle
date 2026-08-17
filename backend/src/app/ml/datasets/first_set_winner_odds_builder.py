"""Estrazione quote Vincitore 1° set dal payload odds grezzo.

Mercato provider: ``"Home/Away (1st Set)"``, stessa forma di ``Home/Away``
(match winner): selezione ``Home`` / ``Away`` → bookmaker → quota decimale.
Nessuna linea extra (a differenza di Over/Under by Games).

Copertura empirica (2026-08-14): 107/107 next_fixture con odds hanno il
mercato; 101/107 con entrambe le side usabili. Sugli ultimi 3000 fixture
storici: 2993 match. Non e' un mercato raro come l'O/U games pre-2025.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.odds_builder import (
    AWAY_SELECTION,
    FixtureOddsRecord,
    HOME_SELECTION,
    _date_to_iso,
    _series_date_to_iso,
    decimal_odd,
    has_real_odds,
    implied_probability,
    is_live_or_in_play,
    no_vig_market_probabilities,
    normalized_odds_payload,
    odds_payload_has_live_flag,
)
from backend.src.entity import Fixture

FIRST_SET_WINNER_MARKET = "Home/Away (1st Set)"

FIRST_SET_ODDS_FEATURE_COLUMNS = [
    "avg_first_set_player_1_odds",
    "avg_first_set_player_2_odds",
    "avg_first_set_market_prob_player_1",
    "avg_first_set_market_prob_player_2",
    "avg_first_set_bookmaker_margin",
    "first_set_odds_bookmaker_count",
]


def _first_set_market(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    clean_payload = normalized_odds_payload(payload)
    market = clean_payload.get(FIRST_SET_WINNER_MARKET) if isinstance(clean_payload, dict) else None
    if not isinstance(market, dict):
        return None, None
    home = market.get(HOME_SELECTION)
    away = market.get(AWAY_SELECTION)
    return (home if isinstance(home, dict) else None), (away if isinstance(away, dict) else None)


def first_set_winner_bookmakers(payload: Any) -> list[str]:
    home, away = _first_set_market(payload)
    if home is None or away is None:
        return []
    return sorted(set(home).intersection(away))


def first_set_winner_rows_from_record(record: FixtureOddsRecord) -> list[dict[str, Any]]:
    payload = normalized_odds_payload(record.odds, match_id=record.match_id)
    if not isinstance(payload, dict):
        return []
    if is_live_or_in_play(record.event_live) or odds_payload_has_live_flag(payload):
        return []

    home, away = _first_set_market(payload)
    if home is None or away is None:
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


@dataclass(frozen=True)
class FirstSetWinnerOddsAverage:
    avg_player_1_odds: float
    avg_player_2_odds: float
    odds_bookmaker_count: int


def average_first_set_winner_odds_from_record(
    record: FixtureOddsRecord,
) -> FirstSetWinnerOddsAverage | None:
    rows = first_set_winner_rows_from_record(record)
    if not rows:
        return None
    bookmakers = {row["bookmaker"] for row in rows}
    return FirstSetWinnerOddsAverage(
        avg_player_1_odds=sum(row["player_1_odds"] for row in rows) / len(rows),
        avg_player_2_odds=sum(row["player_2_odds"] for row in rows) / len(rows),
        odds_bookmaker_count=len(bookmakers),
    )


def first_set_winner_feature_row(
    *,
    event_key: int,
    match_date: Any,
    odds: Any,
) -> dict[str, Any] | None:
    """Le 6 feature quote 1° set aggregate per UNA fixture (inferenza)."""
    rows = first_set_winner_rows_from_record(
        FixtureOddsRecord(
            match_id=event_key,
            match_date=match_date,
            player_1_id=None,
            player_2_id=None,
            player_1_name=None,
            player_2_name=None,
            odds=odds,
        )
    )
    if not rows:
        return None
    bookmakers = {row["bookmaker"] for row in rows}
    return {
        "avg_first_set_player_1_odds": sum(row["player_1_odds"] for row in rows) / len(rows),
        "avg_first_set_player_2_odds": sum(row["player_2_odds"] for row in rows) / len(rows),
        "avg_first_set_market_prob_player_1": sum(row["market_prob_player_1"] for row in rows) / len(rows),
        "avg_first_set_market_prob_player_2": sum(row["market_prob_player_2"] for row in rows) / len(rows),
        "avg_first_set_bookmaker_margin": sum(row["bookmaker_margin"] for row in rows) / len(rows),
        "first_set_odds_bookmaker_count": len(bookmakers),
    }


def _odds_columns() -> list[str]:
    return [
        "match_id",
        "match_date",
        "bookmaker",
        "player_1_odds",
        "player_2_odds",
        "implied_prob_player_1_raw",
        "implied_prob_player_2_raw",
        "bookmaker_margin",
        "market_prob_player_1",
        "market_prob_player_2",
    ]


def odds_records_to_dataframe(records: Iterable[FixtureOddsRecord]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(first_set_winner_rows_from_record(record))
    return pd.DataFrame(rows, columns=_odds_columns())


def aggregate_match_first_set_odds(odds_dataframe: pd.DataFrame) -> pd.DataFrame:
    empty_columns = ["match_id", "match_date", *FIRST_SET_ODDS_FEATURE_COLUMNS]
    if odds_dataframe.empty:
        return pd.DataFrame(columns=empty_columns)

    clean = odds_dataframe.copy()
    clean["match_date"] = _series_date_to_iso(clean["match_date"])
    grouped = (
        clean.groupby(["match_id", "match_date"], dropna=False)
        .agg(
            avg_first_set_player_1_odds=("player_1_odds", "mean"),
            avg_first_set_player_2_odds=("player_2_odds", "mean"),
            avg_first_set_market_prob_player_1=("market_prob_player_1", "mean"),
            avg_first_set_market_prob_player_2=("market_prob_player_2", "mean"),
            avg_first_set_bookmaker_margin=("bookmaker_margin", "mean"),
            first_set_odds_bookmaker_count=("bookmaker", "nunique"),
        )
        .reset_index()
    )
    return grouped


def load_fixture_first_set_odds_records(db: Session) -> list[FixtureOddsRecord]:
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
        ).where(has_real_odds(Fixture.odds))
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


def build_first_set_odds_dataframe(db: Session) -> pd.DataFrame:
    """Dataframe aggregato (una riga per match) per merge su match_id/match_date."""
    records = load_fixture_first_set_odds_records(db)
    return aggregate_match_first_set_odds(odds_records_to_dataframe(records))
