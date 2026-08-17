"""Script diagnostico ad hoc: ispeziona la forma reale del payload odds per il
mercato "Over/Under by Games in Match" (totale game in partita), da NON
confondere con il mercato generico "Over/Under" (che sui dati reali risulta
essere invece Over/Under SET, linea fissa "2.5").

Uso: python -m backend.scripts.diag_over_under_games_market
"""

from __future__ import annotations

from collections import Counter

from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.datasets.odds_builder import has_real_odds, normalized_odds_payload
from backend.src.entity import Fixture
from sqlalchemy import select

OVER_UNDER_GAMES_MARKET = "Over/Under by Games in Match"
OVER_SELECTION = "Over/Under by Games in Match Over"
UNDER_SELECTION = "Over/Under by Games in Match Under"


def main() -> None:
    with SessionLocal() as db:
        rows = db.execute(
            select(Fixture.event_key, Fixture.odds).where(has_real_odds(Fixture.odds))
        ).all()

    total_with_odds = len(rows)
    matches_with_market = 0
    line_match_counter: Counter[str] = Counter()  # per quanti MATCH compare ciascuna linea (Over side)
    line_bookmaker_counter: Counter[str] = Counter()  # per quante righe bookmaker-linea in totale
    both_sides_line_match_counter: Counter[str] = Counter()  # linee con ALMENO 1 bookmaker comune Over+Under
    bookmakers_per_line_samples: list[int] = []

    for row in rows:
        payload = normalized_odds_payload(row.odds, match_id=row.event_key)
        if not isinstance(payload, dict):
            continue
        market = payload.get(OVER_UNDER_GAMES_MARKET)
        if not isinstance(market, dict):
            continue
        over = market.get(OVER_SELECTION)
        under = market.get(UNDER_SELECTION)
        if not isinstance(over, dict) or not isinstance(under, dict):
            continue
        matches_with_market += 1

        lines_seen_this_match: set[str] = set()
        for line_key, bookmakers in over.items():
            if not isinstance(bookmakers, dict) or not bookmakers:
                continue
            lines_seen_this_match.add(str(line_key))
            line_bookmaker_counter[str(line_key)] += len(bookmakers)
            bookmakers_per_line_samples.append(len(bookmakers))

        for line_key in lines_seen_this_match:
            line_match_counter[line_key] += 1
            under_bookmakers = under.get(line_key)
            over_bookmakers = over.get(line_key)
            if isinstance(under_bookmakers, dict) and isinstance(over_bookmakers, dict):
                common = set(over_bookmakers).intersection(under_bookmakers)
                if common:
                    both_sides_line_match_counter[line_key] += 1

    print(f"Righe fixture con odds non-null: {total_with_odds}")
    print(f"Match con mercato Over/Under-by-games presente (entrambi i lati): {matches_with_market}")
    print(
        f"Copertura sul totale odds: "
        f"{round(matches_with_market / total_with_odds * 100, 2) if total_with_odds else 0}%"
    )
    print()
    print("--- Top 20 linee per NUMERO DI MATCH in cui compaiono (>=1 bookmaker Over) ---")
    for line, count in line_match_counter.most_common(20):
        pct = round(count / matches_with_market * 100, 2) if matches_with_market else 0.0
        both_sides = both_sides_line_match_counter.get(line, 0)
        both_pct = round(both_sides / matches_with_market * 100, 2) if matches_with_market else 0.0
        print(
            f"  linea={line!r:>8} match_con_over={count:>7} ({pct}%)  "
            f"match_con_over_e_under_stesso_bookmaker={both_sides:>7} ({both_pct}%)"
        )
    print()
    avg_bookmakers = (
        sum(bookmakers_per_line_samples) / len(bookmakers_per_line_samples)
        if bookmakers_per_line_samples
        else 0.0
    )
    print(f"Media bookmaker per (match, linea) osservata: {round(avg_bookmakers, 3)}")
    print(f"Numero totale (match,linea) osservate: {len(bookmakers_per_line_samples)}")


if __name__ == "__main__":
    main()



