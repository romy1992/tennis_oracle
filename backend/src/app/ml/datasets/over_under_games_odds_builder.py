"""Estrazione quote Over/Under sul TOTALE GAME IN PARTITA dal payload odds grezzo.

Mercato provider: ``"Over/Under by Games in Match"``. Da NON confondere col
mercato generico ``"Over/Under"``, che sui dati reali e' invece Over/Under sul
TOTALE SET (linea fissa "2.5") — verificato empiricamente il 2026-08-13, vedi
``backend/scripts/diag_over_under_games_market.py``.

Struttura REALE confermata empiricamente sul DB di produzione (2026-08-13),
un livello di annidamento IN PIU' rispetto a ``Home/Away``
(mercato -> selezione -> LINEA -> bookmaker, non mercato -> selezione ->
bookmaker come in ``odds_builder.match_winner_rows_from_record``)::

    {
      "Over/Under by Games in Match": {
        "Over/Under by Games in Match Over": {
          "20.5": {"Betfair": "1.82", "Superbet": "1.85"},
          "21.5": {"Superbet": "1.92"},
          ...
        },
        "Over/Under by Games in Match Under": {
          "20.5": {"Betfair": "1.95", "Superbet": "1.88"},
          ...
        }
      }
    }

Le chiavi "selezione" sono verbose (ripetono il nome del mercato + Over/Under,
non solo "Over"/"Under" come in Home/Away con Home/Away): confermato
empiricamente, non e' un typo.

A differenza di Home/Away, bookmaker diversi spesso pubblicano LINEE diverse
(la propria "linea principale"): non tutti i bookmaker offrono tutte le linee
per lo stesso match. Le linee sono espresse sia a mezzo punto ("20.5") sia
intere ("20", "21", ...): quest'ultime corrispondono a un push/no-bet raro nel
mondo reale ma vanno comunque gestite nella normalizzazione della chiave.

Copertura sul totale fixture con odds (114117 righe, 2026-08-13): 26.75%
(30523 match) hanno ALMENO una linea con quote complete Over+Under da un
bookmaker comune. Linea piu' diffusa: 20.5 (84.0% dei match con questo
mercato, 25639 match; media ~2.9 bookmaker per (match, linea) osservata).
Scelta come linea di riferimento di default per il primo modello.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.odds_builder import (
    FixtureOddsRecord,
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

OVER_UNDER_GAMES_MARKET = "Over/Under by Games in Match"
OVER_SELECTION = "Over/Under by Games in Match Over"
UNDER_SELECTION = "Over/Under by Games in Match Under"
DEFAULT_LINE = 20.5
OVER_UNDER_ODDS_DATASET_FILENAME = "tennis_over_under_games_odds.csv"

# Analogo a odds_builder.ODDS_FEATURE_COLUMNS ma per il mercato O/U games:
# colonne aggiuntive da usare come feature ML (oltre che come benchmark).
OVER_UNDER_ODDS_FEATURE_COLUMNS = [
    "avg_over_odds",
    "avg_under_odds",
    "avg_market_prob_over",
    "avg_market_prob_under",
    "avg_bookmaker_margin_ou_games",
    "odds_bookmaker_count_ou_games",
]


def line_key(line: float) -> str:
    """Formatta la linea come chiave stringa del payload.

    Il provider usa sia il formato a mezzo punto ("20.5") sia quello intero
    ("20", "21", ...): va replicato esattamente com'e' nel JSON, altrimenti
    il lookup fallisce silenziosamente (dict.get su chiave inesistente)."""
    if float(line).is_integer():
        return str(int(line))
    return str(line)


def _over_under_market(payload: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    clean_payload = normalized_odds_payload(payload)
    market = clean_payload.get(OVER_UNDER_GAMES_MARKET) if isinstance(clean_payload, dict) else None
    if not isinstance(market, dict):
        return None, None
    over = market.get(OVER_SELECTION)
    under = market.get(UNDER_SELECTION)
    return (over if isinstance(over, dict) else None), (under if isinstance(under, dict) else None)


def over_under_games_bookmakers(payload: Any, line: float = DEFAULT_LINE) -> list[str]:
    over, under = _over_under_market(payload)
    if over is None or under is None:
        return []
    key = line_key(line)
    over_line = over.get(key)
    under_line = under.get(key)
    if not isinstance(over_line, dict) or not isinstance(under_line, dict):
        return []
    return sorted(set(over_line).intersection(under_line))


def over_under_games_rows_from_record(
    record: FixtureOddsRecord,
    line: float = DEFAULT_LINE,
) -> list[dict[str, Any]]:
    payload = normalized_odds_payload(record.odds, match_id=record.match_id)
    if not isinstance(payload, dict):
        return []
    if is_live_or_in_play(record.event_live) or odds_payload_has_live_flag(payload):
        return []

    over, under = _over_under_market(payload)
    if over is None or under is None:
        return []

    key = line_key(line)
    over_line = over.get(key)
    under_line = under.get(key)
    if not isinstance(over_line, dict) or not isinstance(under_line, dict):
        return []

    rows: list[dict[str, Any]] = []
    for bookmaker in sorted(set(over_line).intersection(under_line)):
        over_odds = decimal_odd(over_line.get(bookmaker))
        under_odds = decimal_odd(under_line.get(bookmaker))
        if over_odds is None or under_odds is None:
            continue

        implied_over = implied_probability(over_odds)
        implied_under = implied_probability(under_odds)
        market_prob_over, market_prob_under = no_vig_market_probabilities(over_odds, under_odds)
        rows.append(
            {
                "match_id": record.match_id,
                "match_date": _date_to_iso(record.match_date),
                "line": line,
                "bookmaker": str(bookmaker),
                "over_odds": over_odds,
                "under_odds": under_odds,
                "implied_prob_over_raw": implied_over,
                "implied_prob_under_raw": implied_under,
                "bookmaker_margin": implied_over + implied_under - 1.0,
                "market_prob_over": market_prob_over,
                "market_prob_under": market_prob_under,
            }
        )
    return rows


@dataclass(frozen=True)
class OverUnderGamesOddsAverage:
    avg_over_odds: float
    avg_under_odds: float
    odds_bookmaker_count: int


def average_over_under_games_odds_from_record(
    record: FixtureOddsRecord,
    line: float = DEFAULT_LINE,
) -> OverUnderGamesOddsAverage | None:
    rows = over_under_games_rows_from_record(record, line=line)
    if not rows:
        return None
    bookmakers = {row["bookmaker"] for row in rows}
    return OverUnderGamesOddsAverage(
        avg_over_odds=sum(row["over_odds"] for row in rows) / len(rows),
        avg_under_odds=sum(row["under_odds"] for row in rows) / len(rows),
        odds_bookmaker_count=len(bookmakers),
    )


def over_under_games_feature_row(
    *,
    event_key: int,
    match_date: Any,
    odds: Any,
    line: float = DEFAULT_LINE,
) -> dict[str, Any] | None:
    """Le 6 feature O/U games aggregate per UNA fixture (inferenza real-time,
    stesso ruolo di ``predictor.odds_feature_row`` per Home/Away): ``None`` se
    il mercato/linea non e' disponibile per questa fixture (nessuna quota).
    """
    rows = over_under_games_rows_from_record(
        FixtureOddsRecord(
            match_id=event_key,
            match_date=match_date,
            player_1_id=None,
            player_2_id=None,
            player_1_name=None,
            player_2_name=None,
            odds=odds,
        ),
        line=line,
    )
    if not rows:
        return None
    bookmakers = {row["bookmaker"] for row in rows}
    return {
        "avg_over_odds": sum(row["over_odds"] for row in rows) / len(rows),
        "avg_under_odds": sum(row["under_odds"] for row in rows) / len(rows),
        "avg_market_prob_over": sum(row["market_prob_over"] for row in rows) / len(rows),
        "avg_market_prob_under": sum(row["market_prob_under"] for row in rows) / len(rows),
        "avg_bookmaker_margin_ou_games": sum(row["bookmaker_margin"] for row in rows) / len(rows),
        "odds_bookmaker_count_ou_games": len(bookmakers),
    }


def _odds_columns() -> list[str]:
    return [
        "match_id",
        "match_date",
        "line",
        "bookmaker",
        "over_odds",
        "under_odds",
        "implied_prob_over_raw",
        "implied_prob_under_raw",
        "bookmaker_margin",
        "market_prob_over",
        "market_prob_under",
    ]


def odds_records_to_dataframe(
    records: Iterable[FixtureOddsRecord],
    line: float = DEFAULT_LINE,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in records:
        rows.extend(over_under_games_rows_from_record(record, line=line))
    return pd.DataFrame(rows, columns=_odds_columns())


def aggregate_match_over_under_odds(odds_dataframe: pd.DataFrame) -> pd.DataFrame:
    if odds_dataframe.empty:
        return pd.DataFrame(
            columns=[
                "match_id",
                "match_date",
                "avg_over_odds",
                "avg_under_odds",
                "avg_market_prob_over",
                "avg_market_prob_under",
                "avg_bookmaker_margin_ou_games",
                "odds_bookmaker_count_ou_games",
            ]
        )

    clean = odds_dataframe.copy()
    clean["match_date"] = _series_date_to_iso(clean["match_date"])
    grouped = (
        clean.groupby(["match_id", "match_date"], dropna=False)
        .agg(
            avg_over_odds=("over_odds", "mean"),
            avg_under_odds=("under_odds", "mean"),
            avg_market_prob_over=("market_prob_over", "mean"),
            avg_market_prob_under=("market_prob_under", "mean"),
            avg_bookmaker_margin_ou_games=("bookmaker_margin", "mean"),
            odds_bookmaker_count_ou_games=("bookmaker", "nunique"),
        )
        .reset_index()
    )
    return grouped


def attach_over_under_odds_to_dataset(
    dataset: pd.DataFrame,
    odds_dataframe: pd.DataFrame,
) -> pd.DataFrame:
    output = dataset.copy()
    if "match_id" not in output.columns or "match_date" not in output.columns:
        return output

    output["match_date"] = _series_date_to_iso(output["match_date"])
    aggregated = aggregate_match_over_under_odds(odds_dataframe)
    merged = output.merge(aggregated, on=["match_id", "match_date"], how="left", validate="one_to_one")
    return merged


def load_fixture_over_under_odds_records(db: Session) -> list[FixtureOddsRecord]:
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


def build_over_under_odds_dataframe(db: Session, *, line: float = DEFAULT_LINE) -> pd.DataFrame:
    """Dataframe aggregato (una riga per match) pronto per un merge
    (``how="left"`` su ``["match_id", "match_date"]``) sui dataset v3/v4
    esistenti — stesso pattern di ``odds_builder`` / ``score_parser``."""
    records = load_fixture_over_under_odds_records(db)
    raw_odds = odds_records_to_dataframe(records, line=line)
    return aggregate_match_over_under_odds(raw_odds)


def inspect_over_under_lines(records: Iterable[FixtureOddsRecord]) -> dict[str, int]:
    """Numero di match (con quote Over+Under complete da un bookmaker comune)
    per ciascuna linea disponibile. Usato per scegliere/validare la linea di
    riferimento (vedi ``backend/scripts/diag_over_under_games_market.py`` per
    l'analisi completa gia' eseguita sul DB di produzione)."""
    line_counts: dict[str, int] = {}
    for record in records:
        payload = normalized_odds_payload(record.odds, match_id=record.match_id)
        if not isinstance(payload, dict):
            continue
        if is_live_or_in_play(record.event_live) or odds_payload_has_live_flag(payload):
            continue
        over, under = _over_under_market(payload)
        if over is None or under is None:
            continue
        for key, over_bookmakers in over.items():
            if not isinstance(over_bookmakers, dict) or not over_bookmakers:
                continue
            under_bookmakers = under.get(key)
            if not isinstance(under_bookmakers, dict):
                continue
            common = set(over_bookmakers).intersection(under_bookmakers)
            usable = any(
                decimal_odd(over_bookmakers.get(bookmaker)) is not None
                and decimal_odd(under_bookmakers.get(bookmaker)) is not None
                for bookmaker in common
            )
            if usable:
                line_counts[str(key)] = line_counts.get(str(key), 0) + 1
    return dict(sorted(line_counts.items(), key=lambda item: item[1], reverse=True))


def format_over_under_lines_summary(line_counts: dict[str, int], total_matches: int) -> str:
    lines = [f"Match totali con odds: {total_matches}", "Copertura per linea (num match, %):"]
    for key, count in list(line_counts.items())[:20]:
        pct = round(count / total_matches * 100, 2) if total_matches else 0.0
        lines.append(f"  linea={key:>6}: {count} ({pct}%)")
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    logging_configured = False
    try:
        import logging

        logging.basicConfig(level=logging.INFO)
        logging_configured = True
    except Exception:  # noqa: BLE001 — logging setup non critico per il report
        pass

    with SessionLocal() as db:
        records = load_fixture_over_under_odds_records(db)
    line_counts = inspect_over_under_lines(records)
    print(format_over_under_lines_summary(line_counts, total_matches=len(records)))
    if logging_configured:
        pass


if __name__ == "__main__":
    main()



