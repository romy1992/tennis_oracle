"""Offline baseline + what-if replay for Consiglio schedina (no prod changes).

1. Historical performance of persisted profiles (by profile / day / market)
2. Light what-if: short PLAY slips from unique picks already on those slips
3. Full-pool what-if (step A): rebuild ``build_candidate_pool(..., include_completed=True)``
   from historical ``Fixture`` / open ``NextFixture``, settle outcomes, then simulate
   2–3 fold PLAY-only strategies

Usage (repo root, with DB reachable via backend/.env):

  python -m backend.scripts.diag_betting_slip_baseline
  python -m backend.scripts.diag_betting_slip_baseline --days 60 --highlight-date 2026-08-15
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.datasets.odds_builder import has_real_odds
from backend.src.app.ml.model_versioning import (
    DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
    REPORTS_DIR,
    ModelVersion,
)
from backend.src.app.schemas.betting_slips import BettingSlipPickRead, BettingSlipRead
from backend.src.app.services.betting_slips import (
    DEFAULT_STAKE,
    CandidatePick,
    _load_outcome_context,
    _resolve_actual_winner,
    _resolve_betting_model_name,
    _resolve_match_lifecycle,
    _resolve_pick_actual_result,
    _resolve_pick_status,
    _slip_read,
    build_candidate_pool,
)
from backend.src.app.services.match_lifecycle import (
    match_lifecycle_label,
    resolve_slip_status_from_picks,
    slip_profit_units,
)
from backend.src.entity import Fixture
from backend.src.entity.betting_slip import BettingSlip


@dataclass
class CounterBucket:
    slips_won: int = 0
    slips_lost: int = 0
    slips_pending: int = 0
    slips_void: int = 0
    picks_won: int = 0
    picks_lost: int = 0
    picks_pending: int = 0
    picks_void: int = 0
    profit_units: float = 0.0
    stake_units: float = 0.0
    days_with_slip: int = 0

    def add_slip(self, status: str, profit: float, stake: float) -> None:
        if status == "won":
            self.slips_won += 1
            self.stake_units += stake
            self.profit_units += profit
        elif status == "lost":
            self.slips_lost += 1
            self.stake_units += stake
            self.profit_units += profit
        elif status == "void":
            self.slips_void += 1
        else:
            self.slips_pending += 1

    def add_pick(self, status: str) -> None:
        if status == "won":
            self.picks_won += 1
        elif status == "lost":
            self.picks_lost += 1
        elif status == "void":
            self.picks_void += 1
        else:
            self.picks_pending += 1

    def summary(self) -> dict[str, Any]:
        resolved_slips = self.slips_won + self.slips_lost
        resolved_picks = self.picks_won + self.picks_lost
        return {
            "days_with_slip": self.days_with_slip,
            "slips_won": self.slips_won,
            "slips_lost": self.slips_lost,
            "slips_pending": self.slips_pending,
            "slips_void": self.slips_void,
            "slip_win_rate_pct": _pct(self.slips_won, resolved_slips),
            "picks_won": self.picks_won,
            "picks_lost": self.picks_lost,
            "picks_pending": self.picks_pending,
            "picks_void": self.picks_void,
            "pick_hit_rate_pct": _pct(self.picks_won, resolved_picks),
            "profit_units": round(self.profit_units, 2),
            "stake_units": round(self.stake_units, 2),
            "roi_pct": (
                round((self.profit_units / self.stake_units) * 100.0, 1)
                if self.stake_units > 0
                else None
            ),
        }


def _pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 1)


def _effective_odds(picks: Iterable[BettingSlipPickRead]) -> float | None:
    active = [pick for pick in picks if pick.pick_status != "void" and pick.odds is not None]
    if not active:
        return None
    product = 1.0
    for pick in active:
        product *= float(pick.odds)
    return round(product, 4)


def _simulate_slip(
    picks: list[BettingSlipPickRead],
    *,
    stake: float,
) -> dict[str, Any]:
    statuses = [pick.pick_status for pick in picks]
    status = resolve_slip_status_from_picks(statuses)
    odds = _effective_odds(picks)
    profit = slip_profit_units(
        slip_status=status,
        stake=stake,
        effective_combined_odds=odds,
    )
    return {
        "status": status,
        "pick_count": len(picks),
        "active_pick_count": sum(1 for pick in picks if pick.pick_status != "void"),
        "effective_combined_odds": odds,
        "profit_units": round(profit, 2),
        "picks": [
            {
                "event_key": pick.event_key,
                "market": pick.market,
                "label": pick.predicted_winner_label,
                "decision": pick.value_decision,
                "confidence": pick.confidence,
                "odds": pick.odds,
                "status": pick.pick_status,
            }
            for pick in picks
        ],
    }


def _unique_day_picks(slips: list[BettingSlipRead]) -> dict[tuple[int, str], BettingSlipPickRead]:
    by_key: dict[tuple[int, str], BettingSlipPickRead] = {}
    for slip in slips:
        for pick in slip.picks:
            identity = (pick.event_key, pick.market or "match_winner")
            if identity not in by_key:
                by_key[identity] = pick
    return by_key


def _sort_key_confidence(pick: BettingSlipPickRead) -> float:
    return float(pick.confidence or 0.0)


def _sort_key_score(pick: BettingSlipPickRead) -> float:
    return float(pick.pick_score or 0.0)


def _build_strategy_slip(
    day_picks: dict[tuple[int, str], BettingSlipPickRead],
    *,
    max_picks: int,
    allowed_decisions: set[str],
    markets: set[str] | None,
    sort_key: Callable[[BettingSlipPickRead], float],
) -> list[BettingSlipPickRead]:
    candidates = [
        pick
        for pick in day_picks.values()
        if (pick.value_decision or "") in allowed_decisions
        and (markets is None or (pick.market or "match_winner") in markets)
        and pick.odds is not None
    ]
    candidates.sort(key=sort_key, reverse=True)

    selected: list[BettingSlipPickRead] = []
    used_events: set[int] = set()
    used_markets: set[str] = set()
    remaining = candidates[:]
    while len(selected) < max_picks and remaining:
        unseen = [pick for pick in remaining if (pick.market or "match_winner") not in used_markets]
        pool = unseen or remaining
        pool.sort(key=sort_key, reverse=True)
        next_pick = pool[0]
        remaining.remove(next_pick)
        if next_pick.event_key in used_events:
            continue
        selected.append(next_pick)
        used_events.add(next_pick.event_key)
        used_markets.add(next_pick.market or "match_winner")
    return selected


def _candidate_to_pick_read(
    candidate: CandidatePick,
    *,
    predictions: dict[int, Any],
    fixtures: dict[int, Any],
    next_fixtures: dict[int, Any],
) -> BettingSlipPickRead:
    stub = SimpleNamespace(
        event_key=candidate.event_key,
        market=candidate.market,
        predicted_winner=candidate.predicted_winner,
        odds=candidate.odds,
        player_1_name=candidate.player_1_name,
        player_2_name=candidate.player_2_name,
        void_odds=candidate.void_odds,
        model_prob=candidate.model_prob,
        expected_roi=candidate.expected_roi,
        min_edge_percent=candidate.min_edge_percent,
        suggested_min_edge_percent=candidate.suggested_min_edge_percent,
    )
    match_actual = _resolve_actual_winner(stub, predictions, fixtures)
    lifecycle, event_status = _resolve_match_lifecycle(
        candidate.event_key,
        fixtures=fixtures,
        next_fixtures=next_fixtures,
        actual_winner=match_actual,
    )
    actual_result, has_result = _resolve_pick_actual_result(
        stub, predictions=predictions, fixtures=fixtures
    )
    pick_status, is_correct = _resolve_pick_status(
        stub,
        actual_result,
        match_lifecycle_status=lifecycle,
        has_result=has_result,
    )
    void_reason = match_lifecycle_label(lifecycle) if pick_status == "void" else None
    return BettingSlipPickRead(
        event_key=candidate.event_key,
        market=candidate.market,
        event_date=candidate.event_date,
        event_time=candidate.event_time,
        tournament_name=candidate.tournament_name,
        surface=candidate.surface,
        player_1=candidate.player_1_name,
        player_2=candidate.player_2_name,
        predicted_winner=candidate.predicted_winner,
        predicted_winner_label=candidate.predicted_winner_label,
        model_prob=candidate.model_prob,
        market_prob=candidate.market_prob,
        edge=candidate.edge,
        odds=candidate.odds,
        void_odds=candidate.void_odds,
        edge_absolute=candidate.edge_absolute,
        edge_percent=candidate.edge_percent,
        expected_roi=candidate.expected_roi,
        suggested_min_edge_percent=candidate.suggested_min_edge_percent,
        min_edge_percent=candidate.min_edge_percent,
        value_decision=candidate.value_decision,
        value_label=candidate.value_label,
        confidence=candidate.confidence,
        pick_score=candidate.pick_score,
        pick_status=pick_status,
        actual_winner_label=None,
        is_correct=is_correct,
        match_lifecycle_status=lifecycle,
        match_lifecycle_label=match_lifecycle_label(lifecycle),
        event_status=event_status,
        void_reason=void_reason,
    )


def _run_strategies(
    day_picks: dict[tuple[int, str], BettingSlipPickRead],
    *,
    stake: float,
) -> tuple[dict[str, CounterBucket], dict[str, dict[str, Any]]]:
    buckets = {strategy["key"]: CounterBucket() for strategy in STRATEGIES}
    details: dict[str, dict[str, Any]] = {}
    for strategy in STRATEGIES:
        sort_fn = _sort_key_confidence if strategy["sort"] == "confidence" else _sort_key_score
        selected = _build_strategy_slip(
            day_picks,
            max_picks=int(strategy["max_picks"]),
            allowed_decisions=set(strategy["decisions"]),
            markets=strategy["markets"],
            sort_key=sort_fn,
        )
        if len(selected) < 2:
            continue
        simulated = _simulate_slip(selected, stake=stake)
        buckets[strategy["key"]].days_with_slip += 1
        buckets[strategy["key"]].add_slip(
            simulated["status"], float(simulated["profit_units"]), stake
        )
        for pick in selected:
            buckets[strategy["key"]].add_pick(pick.pick_status)
        details[strategy["key"]] = simulated
    return buckets, details


STRATEGIES: tuple[dict[str, Any], ...] = (
    {
        "key": "play_top2_confidence",
        "label": "What-if PLAY top2 confidence",
        "max_picks": 2,
        "decisions": {"PLAY"},
        "markets": None,
        "sort": "confidence",
    },
    {
        "key": "play_top3_confidence",
        "label": "What-if PLAY top3 confidence",
        "max_picks": 3,
        "decisions": {"PLAY"},
        "markets": None,
        "sort": "confidence",
    },
    {
        "key": "play_top2_score",
        "label": "What-if PLAY top2 score",
        "max_picks": 2,
        "decisions": {"PLAY"},
        "markets": None,
        "sort": "score",
    },
    {
        "key": "play_top3_score",
        "label": "What-if PLAY top3 score",
        "max_picks": 3,
        "decisions": {"PLAY"},
        "markets": None,
        "sort": "score",
    },
    {
        "key": "play_mw_top2_confidence",
        "label": "What-if PLAY Match-only top2",
        "max_picks": 2,
        "decisions": {"PLAY"},
        "markets": {"match_winner"},
        "sort": "confidence",
    },
    {
        "key": "play_mw_top3_confidence",
        "label": "What-if PLAY Match-only top3",
        "max_picks": 3,
        "decisions": {"PLAY"},
        "markets": {"match_winner"},
        "sort": "confidence",
    },
)


def _fmt_row(label: str, bucket: CounterBucket, *, show_days: bool = False) -> str:
    s = bucket.summary()
    win = s["slip_win_rate_pct"]
    hit = s["pick_hit_rate_pct"]
    roi = s["roi_pct"]
    days_part = f"days {s['days_with_slip']:>2}  " if show_days else ""
    return (
        f"{label:<40} "
        f"{days_part}"
        f"W/L {s['slips_won']:>3}/{s['slips_lost']:<3} "
        f"win% {win if win is not None else 'n.d.':>6}  "
        f"pick% {hit if hit is not None else 'n.d.':>6}  "
        f"ROI {roi if roi is not None else 'n.d.':>7}  "
        f"P/L {s['profit_units']:>+7.2f}"
    )


def _merge_strategy_day(
    totals: dict[str, CounterBucket],
    day_buckets: dict[str, CounterBucket],
) -> None:
    for key, day_bucket in day_buckets.items():
        total = totals[key]
        total.days_with_slip += day_bucket.days_with_slip
        total.slips_won += day_bucket.slips_won
        total.slips_lost += day_bucket.slips_lost
        total.slips_pending += day_bucket.slips_pending
        total.slips_void += day_bucket.slips_void
        total.picks_won += day_bucket.picks_won
        total.picks_lost += day_bucket.picks_lost
        total.picks_pending += day_bucket.picks_pending
        total.picks_void += day_bucket.picks_void
        total.profit_units += day_bucket.profit_units
        total.stake_units += day_bucket.stake_units


def run_report(
    *,
    days: int,
    model_version: ModelVersion,
    model_name: str | None,
    highlight_date: date | None,
    stake: float,
    output_path: Path,
) -> dict[str, Any]:
    today = date.today()
    from_date = today - timedelta(days=max(days - 1, 0))
    to_date = today

    with SessionLocal() as db:
        resolved_model_name, model_warning = _resolve_betting_model_name(
            model_version, model_name
        )
        slips = list(
            db.scalars(
                select(BettingSlip)
                .options(selectinload(BettingSlip.picks))
                .where(
                    BettingSlip.model_version == model_version,
                    BettingSlip.model_name == resolved_model_name,
                    BettingSlip.slip_date >= from_date,
                    BettingSlip.slip_date <= to_date,
                )
                .order_by(BettingSlip.slip_date.asc(), BettingSlip.id.asc())
            ).all()
        )

        event_keys = [pick.event_key for slip in slips for pick in slip.picks]
        predictions, fixtures, next_fixtures = _load_outcome_context(
            db,
            event_keys,
            model_version,
            resolved_model_name,
        )

        slips_by_date: dict[date, list[BettingSlipRead]] = defaultdict(list)
        for slip in slips:
            slip_read = _slip_read(
                slip,
                predictions=predictions,
                fixtures=fixtures,
                next_fixtures=next_fixtures,
                stake=stake,
            )
            slips_by_date[slip.slip_date].append(slip_read)

        fixture_dates = set(
            db.scalars(
                select(Fixture.event_date)
                .where(
                    Fixture.event_date >= from_date,
                    Fixture.event_date <= to_date,
                    has_real_odds(Fixture.odds),
                )
                .distinct()
            ).all()
        )
        replay_dates = sorted(set(slips_by_date) | {d for d in fixture_dates if d is not None})

        overall = CounterBucket()
        by_profile: dict[str, CounterBucket] = defaultdict(CounterBucket)
        by_day: dict[str, CounterBucket] = defaultdict(CounterBucket)
        by_market: dict[str, CounterBucket] = defaultdict(CounterBucket)
        profile_labels: dict[str, str] = {}

        for slip_date, day_slips in sorted(slips_by_date.items()):
            day_key = slip_date.isoformat()
            for slip in day_slips:
                profit = slip_profit_units(
                    slip_status=slip.slip_status,
                    stake=stake,
                    effective_combined_odds=slip.effective_combined_odds,
                )
                overall.add_slip(slip.slip_status, profit, stake)
                by_day[day_key].add_slip(slip.slip_status, profit, stake)
                by_profile[slip.slip_key].add_slip(slip.slip_status, profit, stake)
                profile_labels[slip.slip_key] = slip.label
                for pick in slip.picks:
                    overall.add_pick(pick.pick_status)
                    by_day[day_key].add_pick(pick.pick_status)
                    by_profile[slip.slip_key].add_pick(pick.pick_status)
                    by_market[pick.market or "match_winner"].add_pick(pick.pick_status)

        light_totals = {strategy["key"]: CounterBucket() for strategy in STRATEGIES}
        light_highlight: dict[str, Any] = {}
        for slip_date, day_slips in sorted(slips_by_date.items()):
            day_key = slip_date.isoformat()
            day_buckets, day_details = _run_strategies(
                _unique_day_picks(day_slips), stake=stake
            )
            _merge_strategy_day(light_totals, day_buckets)
            if slip_date == (highlight_date or (today - timedelta(days=1))):
                light_highlight = day_details

        full_totals = {strategy["key"]: CounterBucket() for strategy in STRATEGIES}
        full_highlight: dict[str, Any] = {}
        full_pool_day_stats: dict[str, Any] = {}
        highlight = highlight_date or (today - timedelta(days=1))

        for slip_date in replay_dates:
            day_key = slip_date.isoformat()
            candidates = build_candidate_pool(
                db,
                slip_date=slip_date,
                model_version=model_version,
                model_name=resolved_model_name,
                include_completed=True,
            )
            if not candidates:
                continue
            cand_keys = [candidate.event_key for candidate in candidates]
            cand_predictions, cand_fixtures, cand_next = _load_outcome_context(
                db,
                cand_keys,
                model_version,
                resolved_model_name,
            )
            settled = {
                (candidate.event_key, candidate.market): _candidate_to_pick_read(
                    candidate,
                    predictions=cand_predictions,
                    fixtures=cand_fixtures,
                    next_fixtures=cand_next,
                )
                for candidate in candidates
            }
            play_count = sum(
                1 for pick in settled.values() if pick.value_decision == "PLAY"
            )
            full_pool_day_stats[day_key] = {
                "candidates": len(candidates),
                "play_candidates": play_count,
                "by_market": {
                    market: sum(1 for c in candidates if c.market == market)
                    for market in sorted({c.market for c in candidates})
                },
            }
            day_buckets, day_details = _run_strategies(settled, stake=stake)
            _merge_strategy_day(full_totals, day_buckets)
            if slip_date == highlight:
                full_highlight = day_details

    highlight_key = highlight.isoformat()
    report: dict[str, Any] = {
        "generated_at": date.today().isoformat(),
        "window": {
            "from_date": from_date.isoformat(),
            "to_date": to_date.isoformat(),
            "days": days,
        },
        "model_version": model_version,
        "model_name": resolved_model_name,
        "model_warning": model_warning,
        "stake": stake,
        "highlight_date": highlight_key,
        "baseline_overall": overall.summary(),
        "baseline_by_profile": {
            key: {
                "label": profile_labels.get(key, key),
                **bucket.summary(),
            }
            for key, bucket in sorted(by_profile.items())
        },
        "baseline_by_day": {
            key: bucket.summary() for key, bucket in sorted(by_day.items())
        },
        "baseline_by_market_picks": {
            key: bucket.summary() for key, bucket in sorted(by_market.items())
        },
        "what_if_from_slip_picks": {
            strategy["key"]: {
                "label": strategy["label"],
                **light_totals[strategy["key"]].summary(),
                "highlight_day": light_highlight.get(strategy["key"]),
            }
            for strategy in STRATEGIES
        },
        "what_if_full_candidate_pool": {
            strategy["key"]: {
                "label": strategy["label"],
                **full_totals[strategy["key"]].summary(),
                "highlight_day": full_highlight.get(strategy["key"]),
            }
            for strategy in STRATEGIES
        },
        "full_pool_day_stats": full_pool_day_stats,
        "highlight_day_baseline": by_day.get(highlight_key, CounterBucket()).summary(),
        "note": (
            "Full-pool what-if uses build_candidate_pool(include_completed=True), "
            "falling back to Fixture when NextFixture no longer holds the day. "
            "Light what-if still uses unique picks already stored on persisted slips."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("=" * 108)
    print(
        f"Betting slip baseline  {from_date} -> {to_date}  "
        f"model={model_version}/{resolved_model_name}"
    )
    if model_warning:
        print(f"WARNING: {model_warning}")
    print("=" * 108)
    print("\nOVERALL (persisted profiles)")
    print(_fmt_row("all profiles", overall))
    print(f"\nHIGHLIGHT DAY {highlight_key}")
    print(_fmt_row(highlight_key, by_day.get(highlight_key, CounterBucket())))
    print("\nBY PROFILE")
    for key, bucket in sorted(by_profile.items()):
        label = f"{key} ({profile_labels.get(key, '')})"
        print(_fmt_row(label[:40], bucket))
    print("\nBY MARKET (pick hit only)")
    for key, bucket in sorted(by_market.items()):
        s = bucket.summary()
        print(
            f"{key:<40} "
            f"W/L {s['picks_won']:>3}/{s['picks_lost']:<3} "
            f"hit% {s['pick_hit_rate_pct'] if s['pick_hit_rate_pct'] is not None else 'n.d.':>6}"
        )
    print("\nWHAT-IF LIGHT (from persisted slip picks)")
    for strategy in STRATEGIES:
        print(_fmt_row(strategy["label"][:40], light_totals[strategy["key"]], show_days=True))
    print("\nWHAT-IF FULL POOL (include_completed + Fixture fallback)")
    for strategy in STRATEGIES:
        print(_fmt_row(strategy["label"][:40], full_totals[strategy["key"]], show_days=True))
        detail = full_highlight.get(strategy["key"])
        if detail:
            print(
                f"  |- {highlight_key}: {detail['status']} "
                f"odds={detail['effective_combined_odds']} "
                f"legs={detail['active_pick_count']} "
                f"P/L={detail['profit_units']:+.2f}"
            )
    highlight_pool = full_pool_day_stats.get(highlight_key)
    if highlight_pool:
        print(
            f"\nFULL POOL {highlight_key}: "
            f"{highlight_pool['candidates']} candidates, "
            f"{highlight_pool['play_candidates']} PLAY, "
            f"markets={highlight_pool['by_market']}"
        )
    print(f"\nJSON report: {output_path}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=60, help="Lookback window including today")
    parser.add_argument(
        "--model-version",
        default=DEFAULT_ACTIVE_MATCH_WINNER_VERSION,
        help="Match-winner model version used when slips were generated",
    )
    parser.add_argument("--model-name", default=None, help="Optional model artifact name")
    parser.add_argument(
        "--highlight-date",
        default=None,
        help="ISO date to spotlight (default: yesterday)",
    )
    parser.add_argument("--stake", type=float, default=DEFAULT_STAKE)
    parser.add_argument(
        "--output",
        default=str(REPORTS_DIR / "betting_slip_baseline_whatif.json"),
        help="JSON report path",
    )
    args = parser.parse_args()
    highlight = date.fromisoformat(args.highlight_date) if args.highlight_date else None
    run_report(
        days=args.days,
        model_version=args.model_version,  # type: ignore[arg-type]
        model_name=args.model_name,
        highlight_date=highlight,
        stake=args.stake,
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
