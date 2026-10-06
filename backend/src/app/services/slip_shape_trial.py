"""Frozen slip-shape trial: calibration gate, then a short coupon replay.

The window, model and stake are fixed so the page always shows the same
comparison. Nothing here writes slips or changes the public model.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.score_parser import parse_fixture_score, target_over_line
from backend.src.app.ml.training.calibration import (
    CalibrationMethod,
    apply_calibrator,
    fit_calibrator,
)
from backend.src.app.services.match_lifecycle import (
    classify_match_lifecycle,
    resolve_slip_status_from_picks,
    settle_simulated_bet,
    slip_profit_units,
)
from backend.src.entity.betting_slip import BettingSlip, BettingSlipPick
from backend.src.entity.fixture import Fixture

WINDOW_FROM = date(2026, 8, 7)
WINDOW_TO = date(2026, 10, 5)
SPLIT_DATE = date(2026, 9, 1)
# Days from this date on are the confirmation sample. The odds band is not refit here.
# Handoff for the next session: docs/PROVA_SCHEDINE.md
FORWARD_FROM = date(2026, 10, 6)
MODEL_VERSION = "v4"
MODEL_NAME = "voting_ensemble"
STAKE = 10.0
MIN_SAMPLES = 30
COMPLETED_WINNERS = ("First Player", "Second Player")
ODDS_BANDS = ("<1.30", "1.30-1.50", "1.50-1.80", "1.80-2.20", ">=2.20")
EDGE_BANDS = ("<0", "0-2", "2-5", ">=5")


@dataclass(frozen=True)
class TrialPick:
    slip_id: int
    slip_date: date
    slip_key: str
    event_key: int
    market: str
    model_prob: float | None
    odds: float | None
    outcome: str


def _round(value: float | None, digits: int = 1) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _rate(won: int, lost: int) -> float | None:
    settled = won + lost
    if settled == 0:
        return None
    return _round(100.0 * won / settled)


def _roi(profit: float, stake: float) -> float | None:
    if stake <= 0:
        return None
    return _round(100.0 * profit / stake)


def odds_band(odds: float) -> str:
    if odds < 1.30:
        return "<1.30"
    if odds < 1.50:
        return "1.30-1.50"
    if odds < 1.80:
        return "1.50-1.80"
    if odds < 2.20:
        return "1.80-2.20"
    return ">=2.20"


def edge_band(edge_percent: float) -> str:
    if edge_percent < 0:
        return "<0"
    if edge_percent < 2:
        return "0-2"
    if edge_percent < 5:
        return "2-5"
    return ">=5"


def edge_percent(odds: float, probability: float) -> float:
    return (odds * probability - 1.0) * 100.0


def _normalize_probability(value: float | None) -> float | None:
    if value is None:
        return None
    probability = float(value)
    if probability > 1.0:
        probability /= 100.0
    if probability <= 0.0 or probability >= 1.0:
        return None
    return probability


def _empty_money() -> dict[str, float | int]:
    return {"won": 0, "lost": 0, "pending": 0, "profit": 0.0, "stake": 0.0}


def _add_single(bucket: dict[str, float | int], outcome: str, odds: float | None) -> None:
    if outcome == "won" and odds is not None:
        bucket["won"] += 1
        bucket["profit"] += STAKE * (odds - 1.0)
        bucket["stake"] += STAKE
    elif outcome == "lost":
        bucket["lost"] += 1
        bucket["profit"] -= STAKE
        bucket["stake"] += STAKE
    elif outcome == "pending":
        bucket["pending"] += 1


def _single_slice(label: str, bucket: dict[str, float | int]) -> dict:
    won = int(bucket["won"])
    lost = int(bucket["lost"])
    profit = float(bucket["profit"])
    stake = float(bucket["stake"])
    return {
        "label": label,
        "won": won,
        "lost": lost,
        "pending": int(bucket["pending"]),
        "hit_rate_pct": _rate(won, lost),
        "profit_units": _round(profit) or 0.0,
        "stake_units": _round(stake) or 0.0,
        "roi_pct": _roi(profit, stake),
    }


def _slip_profit(outcomes: list[str], odds: list[float]) -> tuple[str, float]:
    status = resolve_slip_status_from_picks(outcomes)
    product = 1.0
    for price in odds:
        product *= price
    combined = round(product, 4) if odds else None
    profit = slip_profit_units(
        slip_status=status,
        stake=STAKE,
        effective_combined_odds=combined,
    )
    return status, profit


def _official_slips(picks: list[TrialPick]) -> dict:
    grouped: dict[int, list[TrialPick]] = defaultdict(list)
    for pick in picks:
        grouped[pick.slip_id].append(pick)
    slips_won = slips_lost = slips_pending = 0
    picks_won = picks_lost = 0
    profit = stake = 0.0
    for slip_picks in grouped.values():
        outcomes: list[str] = []
        active_odds: list[float] = []
        for pick in slip_picks:
            outcomes.append(pick.outcome)
            if pick.outcome == "won":
                picks_won += 1
            elif pick.outcome == "lost":
                picks_lost += 1
            if pick.outcome != "void" and pick.odds is not None:
                active_odds.append(pick.odds)
        status, slip_profit = _slip_profit(outcomes, active_odds)
        if status == "won":
            slips_won += 1
            profit += slip_profit
            stake += STAKE
        elif status == "lost":
            slips_lost += 1
            profit += slip_profit
            stake += STAKE
        elif status == "pending":
            slips_pending += 1
    return {
        "label": "Generiche",
        "slips_won": slips_won,
        "slips_lost": slips_lost,
        "slips_pending": slips_pending,
        "slip_win_rate_pct": _rate(slips_won, slips_lost),
        "picks_won": picks_won,
        "picks_lost": picks_lost,
        "pick_hit_rate_pct": _rate(picks_won, picks_lost),
        "profit_units": _round(profit) or 0.0,
        "stake_units": _round(stake) or 0.0,
        "roi_pct": _roi(profit, stake),
    }


def _allowed_keys(sample: list[_ScoredPick], checks: list[dict]) -> set[tuple[date, int]] | None:
    """Events kept by a rule that passed both halves.

    Edge rules use the probability calibrated on the other half, same as the gate.
    ``None`` means no rule passed and the short slip is shape-only.
    """
    passing = [check for check in checks if check["passed"]]
    if not passing:
        return None
    august = [row for row in sample if row.slip_date < SPLIT_DATE]
    september = [row for row in sample if row.slip_date >= SPLIT_DATE]
    allowed: set[tuple[date, int]] = set()
    for check in passing:
        if check["dimension"] == "odds":
            for row in sample:
                if odds_band(row.odds) == check["band"]:
                    allowed.add((row.slip_date, row.event_key))
            continue
        for train, test in ((september, august), (august, september)):
            probabilities = _held_out_probabilities(check["method"], train, test)  # type: ignore[arg-type]
            if probabilities is None:
                continue
            for row, probability in zip(test, probabilities):
                if edge_band(edge_percent(row.odds, float(probability))) == check["band"]:
                    allowed.add((row.slip_date, row.event_key))
    return allowed


def _short_slips(
    picks: list[TrialPick],
    *,
    allowed: set[tuple[date, int]] | None,
) -> dict:
    """At most two match-winner legs per day.

    With a passing selection rule, a day can keep one or two matching picks.
    Without one, the replay is only the shape: the two highest probabilities.
    """
    filtered = allowed is not None
    by_day: dict[date, dict[int, TrialPick]] = defaultdict(dict)
    for pick in picks:
        if pick.market != "match_winner":
            continue
        if pick.outcome == "void" or pick.odds is None:
            continue
        probability = _normalize_probability(pick.model_prob)
        if probability is None:
            continue
        if allowed is not None and (pick.slip_date, pick.event_key) not in allowed:
            continue
        current = by_day[pick.slip_date].get(pick.event_key)
        if current is None or (pick.model_prob or 0) > (current.model_prob or 0):
            by_day[pick.slip_date][pick.event_key] = pick

    slips_won = slips_lost = slips_pending = 0
    picks_won = picks_lost = 0
    profit = stake = 0.0
    minimum_legs = 1 if filtered else 2
    for day_picks in by_day.values():
        ranked = sorted(
            day_picks.values(),
            key=lambda pick: _normalize_probability(pick.model_prob) or 0.0,
            reverse=True,
        )
        chosen = ranked[:2]
        if len(chosen) < minimum_legs:
            continue
        outcomes = [pick.outcome for pick in chosen]
        active_odds = [float(pick.odds) for pick in chosen if pick.odds is not None and pick.outcome != "void"]
        for pick in chosen:
            if pick.outcome == "won":
                picks_won += 1
            elif pick.outcome == "lost":
                picks_lost += 1
        status, slip_profit = _slip_profit(outcomes, active_odds)
        if status == "won":
            slips_won += 1
            profit += slip_profit
            stake += STAKE
        elif status == "lost":
            slips_lost += 1
            profit += slip_profit
            stake += STAKE
        elif status == "pending":
            slips_pending += 1
    return {
        "label": "Forma corta",
        "slips_won": slips_won,
        "slips_lost": slips_lost,
        "slips_pending": slips_pending,
        "slip_win_rate_pct": _rate(slips_won, slips_lost),
        "picks_won": picks_won,
        "picks_lost": picks_lost,
        "pick_hit_rate_pct": _rate(picks_won, picks_lost),
        "profit_units": _round(profit) or 0.0,
        "stake_units": _round(stake) or 0.0,
        "roi_pct": _roi(profit, stake),
    }


def _unique_market(picks: list[TrialPick], market: str) -> list[TrialPick]:
    chosen: dict[int, TrialPick] = {}
    for pick in picks:
        if pick.market != market:
            continue
        current = chosen.get(pick.event_key)
        if current is None or pick.slip_date < current.slip_date:
            chosen[pick.event_key] = pick
    return list(chosen.values())


def _singles(picks: list[TrialPick], market: str, label: str) -> dict:
    bucket = _empty_money()
    for pick in _unique_market(picks, market):
        _add_single(bucket, pick.outcome, pick.odds)
    return _single_slice(label, bucket)


@dataclass(frozen=True)
class _ScoredPick:
    slip_date: date
    event_key: int
    odds: float
    won: bool
    probability: float


def _match_winner_sample(picks: list[TrialPick]) -> list[_ScoredPick]:
    sample: list[_ScoredPick] = []
    for pick in _unique_market(picks, "match_winner"):
        if pick.outcome not in {"won", "lost"} or pick.odds is None:
            continue
        probability = _normalize_probability(pick.model_prob)
        if probability is None:
            continue
        sample.append(
            _ScoredPick(
                slip_date=pick.slip_date,
                event_key=pick.event_key,
                odds=float(pick.odds),
                won=pick.outcome == "won",
                probability=probability,
            )
        )
    return sample


def _slice_picks(rows: list[tuple[float, bool]]) -> dict[str, float | int | None]:
    bucket = _empty_money()
    for odds, won in rows:
        _add_single(bucket, "won" if won else "lost", odds)
    won = int(bucket["won"])
    lost = int(bucket["lost"])
    profit = float(bucket["profit"])
    stake = float(bucket["stake"])
    return {
        "settled": won + lost,
        "roi_pct": _roi(profit, stake),
    }


def _held_out_probabilities(
    method: CalibrationMethod,
    train: list[_ScoredPick],
    test: list[_ScoredPick],
) -> np.ndarray | None:
    if not test:
        return np.asarray([], dtype=float)
    test_prob = np.asarray([row.probability for row in test], dtype=float)
    if method == "raw":
        return test_prob
    if len(train) < 2:
        return None
    train_y = np.asarray([1 if row.won else 0 for row in train], dtype=int)
    train_p = np.asarray([row.probability for row in train], dtype=float)
    calibrator = fit_calibrator(method, train_y, train_p)
    if calibrator is None:
        return None
    return np.asarray(apply_calibrator(method, calibrator, test_prob), dtype=float)


def _direction_slice(
    method: CalibrationMethod,
    dimension: str,
    band: str,
    train: list[_ScoredPick],
    test: list[_ScoredPick],
) -> dict[str, float | int | None]:
    if dimension == "odds":
        rows = [(row.odds, row.won) for row in test if odds_band(row.odds) == band]
        return _slice_picks(rows)
    probabilities = _held_out_probabilities(method, train, test)
    if probabilities is None:
        return {"settled": 0, "roi_pct": None}
    rows = []
    for row, probability in zip(test, probabilities):
        if edge_band(edge_percent(row.odds, float(probability))) == band:
            rows.append((row.odds, row.won))
    return _slice_picks(rows)


def _selection_checks(sample: list[_ScoredPick], *, min_samples: int) -> list[dict]:
    august = [row for row in sample if row.slip_date < SPLIT_DATE]
    september = [row for row in sample if row.slip_date >= SPLIT_DATE]
    specs: list[tuple[str, str, str]] = [("raw", "odds", band) for band in ODDS_BANDS]
    for method in ("raw", "platt", "isotonic"):
        specs.extend((method, "edge", band) for band in EDGE_BANDS)

    checks: list[dict] = []
    for method, dimension, band in specs:
        august_slice = _direction_slice(method, dimension, band, september, august)  # type: ignore[arg-type]
        september_slice = _direction_slice(method, dimension, band, august, september)  # type: ignore[arg-type]
        august_n = int(august_slice["settled"] or 0)
        september_n = int(september_slice["settled"] or 0)
        august_roi = august_slice["roi_pct"]
        september_roi = september_slice["roi_pct"]
        passed = (
            august_n >= min_samples
            and september_n >= min_samples
            and august_roi is not None
            and september_roi is not None
            and float(august_roi) > 0
            and float(september_roi) > 0
        )
        checks.append(
            {
                "method": method,
                "dimension": dimension,
                "band": band,
                "august_settled": august_n,
                "august_roi_pct": august_roi,
                "september_settled": september_n,
                "september_roi_pct": september_roi,
                "passed": passed,
            }
        )
    return checks


def _rule_label(check: dict) -> str:
    if check["dimension"] == "odds":
        return f"quota {check['band']}"
    method = {"raw": "grezza", "platt": "Platt", "isotonic": "isotonica"}[check["method"]]
    return f"edge {check['band']} ({method})"


def _conclusion(passing: list[str]) -> str:
    if not passing:
        return (
            "Nessuna fascia di quota o di edge resta in ROI positivo sia ad agosto "
            "sia a settembre, nemmeno dopo Platt o isotonica. La selezione non cambia "
            "e il modello non si riaddestra. Sotto c'è solo la forma corta: due match "
            "winner per probabilità, senza over/under e senza primo set nella stessa multipla."
        )
    names = ", ".join(passing)
    return (
        "Queste regole restano in ROI positivo su entrambe le metà del periodo: "
        f"{names}. La forma corta usa solo quelle, al massimo due match winner al giorno. "
        "Il ROI di quel replay è sullo stesso periodo che ha scelto la regola, non è una conferma nuova."
    )


def _short_slip_rule(passing: list[str]) -> str:
    if not passing:
        return (
            "Due match winner al giorno, i più probabili, senza filtro di quota o di edge. "
            "Over/under e primo set restano fuori."
        )
    return (
        "Solo match winner che rientrano in "
        + " oppure ".join(passing)
        + ", al massimo due al giorno, ordinati per probabilità. "
        "Over/under e primo set restano fuori."
    )


def evaluate_forward_trial(
    picks: list[TrialPick],
    *,
    passed_odds_bands: set[str],
    min_samples: int = MIN_SAMPLES,
    as_of: date | None = None,
) -> dict:
    """Apply the frozen odds bands to slips on or after ``FORWARD_FROM``.

    The band is an input from the selection window. This function does not
    look for a new one.
    """
    window_to = as_of or date.today()
    if window_to < FORWARD_FROM:
        window_to = FORWARD_FROM
    in_window = [pick for pick in picks if FORWARD_FROM <= pick.slip_date <= window_to]
    if not passed_odds_bands:
        short = _short_slips(in_window, allowed=set())
        settled = 0
        return {
            "window_from": FORWARD_FROM,
            "window_to": window_to,
            "ready": False,
            "settled_slips": settled,
            "slips_needed": min_samples,
            "rule": "",
            "note": (
                "Nel periodo congelato non è passata nessuna fascia di quota. "
                "Non c'è una regola da misurare sui giorni nuovi."
            ),
            "short_slips": short,
        }
    allowed = {
        (pick.slip_date, pick.event_key)
        for pick in in_window
        if pick.market == "match_winner" and pick.odds is not None and odds_band(pick.odds) in passed_odds_bands
    }
    short = _short_slips(in_window, allowed=allowed)
    settled = int(short["slips_won"]) + int(short["slips_lost"])
    ready = settled >= min_samples
    rule = "quota " + ", ".join(sorted(passed_odds_bands))
    if ready:
        note = (
            f"Ci sono {settled} schedine corte chiuse dal {FORWARD_FROM.isoformat()}. "
            "Si legge questo ROI. La fascia non si ricalcola e il consiglio ufficiale non si tocca "
            "finché questa lettura non è stata discussa."
        )
    else:
        note = (
            f"Regola ferma: {rule}. Schedine corte chiuse {settled} su {min_samples}. "
            "Prima di quel numero non si cambia soglia, profilo o modello."
        )
    return {
        "window_from": FORWARD_FROM,
        "window_to": window_to,
        "ready": ready,
        "settled_slips": settled,
        "slips_needed": min_samples,
        "rule": rule,
        "note": note,
        "short_slips": short,
    }


def evaluate_slip_shape_trial(picks: list[TrialPick], *, min_samples: int = MIN_SAMPLES) -> dict:
    sample = _match_winner_sample(picks)
    checks = _selection_checks(sample, min_samples=min_samples)
    passing = [_rule_label(check) for check in checks if check["passed"]]
    short_slip_rule = _short_slip_rule(passing)
    return {
        "window_from": WINDOW_FROM,
        "window_to": WINDOW_TO,
        "split_date": SPLIT_DATE,
        "model_version": MODEL_VERSION,
        "model_name": MODEL_NAME,
        "stake": STAKE,
        "min_samples": min_samples,
        "selection_passed": bool(passing),
        "passing_rules": passing,
        "conclusion": _conclusion(passing),
        "short_slip_rule": short_slip_rule,
        "official_slips": _official_slips(picks),
        "short_slips": _short_slips(picks, allowed=_allowed_keys(sample, checks)),
        "match_winner_singles": _singles(picks, "match_winner", "Match winner, singole"),
        "first_set_singles": _singles(picks, "first_set_winner", "Primo set, singole"),
        "over_under_singles": _singles(picks, "over_under_games", "Over/under, singole"),
        "checks": checks,
    }


def _ou_side_line(selection: str | None) -> tuple[str, float] | None:
    if not selection:
        return None
    parts = selection.split()
    if len(parts) != 2 or parts[0] not in {"Over", "Under"}:
        return None
    try:
        return parts[0], float(parts[1])
    except ValueError:
        return None


def _market_result(
    market: str,
    predicted: str | None,
    fixture: Fixture | SimpleNamespace | None,
) -> tuple[str | None, bool]:
    if market == "match_winner":
        winner = fixture.event_winner if fixture is not None else None
        if winner in COMPLETED_WINNERS:
            return winner, True
        return None, False
    if fixture is None:
        return None, False
    parsed = parse_fixture_score(
        match_id=fixture.event_key,
        scores=fixture.scores,
        event_game_result=fixture.event_game_result,
    )
    if not parsed.is_valid_for_training:
        return None, False
    if market == "first_set_winner":
        if parsed.first_set_winner == "player_1":
            return "First Player", True
        if parsed.first_set_winner == "player_2":
            return "Second Player", True
        return None, False
    parsed_sel = _ou_side_line(predicted)
    line = parsed_sel[1] if parsed_sel else 20.5
    flag = target_over_line(parsed.total_games, line)
    if flag is None:
        return None, False
    return ("Over" if flag == 1 else "Under"), True


def _predicted_side(market: str, predicted: str | None) -> str | None:
    if market == "over_under_games":
        parsed = _ou_side_line(predicted)
        return parsed[0] if parsed else predicted
    return predicted


def settle_stored_pick(
    *,
    market: str,
    predicted_winner: str | None,
    odds: float | None,
    fixture: Fixture | SimpleNamespace | None,
) -> str:
    actual_match = fixture.event_winner if fixture is not None and fixture.event_winner in COMPLETED_WINNERS else None
    if fixture is None:
        lifecycle = "upcoming"
    else:
        lifecycle = classify_match_lifecycle(
            event_status=fixture.event_status,
            event_winner=actual_match,
            event_final_result=fixture.event_final_result,
            event_live=fixture.event_live,
            is_completed=fixture.event_winner in COMPLETED_WINNERS,
        )
    actual, has_result = _market_result(market, predicted_winner, fixture)
    settlement = settle_simulated_bet(
        lifecycle=lifecycle,
        predicted_winner=_predicted_side(market, predicted_winner),
        actual_winner=actual,
        market_odds=odds,
        stake_units=STAKE,
        has_result=has_result,
        postponed_as_void=True,
    )
    return settlement.outcome


def load_trial_picks(db: Session, *, date_from: date, date_to: date) -> list[TrialPick]:
    rows = db.execute(
        select(
            BettingSlip.id,
            BettingSlip.slip_date,
            BettingSlip.slip_key,
            BettingSlipPick.event_key,
            BettingSlipPick.market,
            BettingSlipPick.predicted_winner,
            BettingSlipPick.model_prob,
            BettingSlipPick.odds,
            Fixture.event_key,
            Fixture.event_status,
            Fixture.event_winner,
            Fixture.event_final_result,
            Fixture.event_live,
            Fixture.scores,
            Fixture.event_game_result,
        )
        .join(BettingSlipPick, BettingSlipPick.betting_slip_id == BettingSlip.id)
        .outerjoin(Fixture, Fixture.event_key == BettingSlipPick.event_key)
        .where(
            BettingSlip.model_version == MODEL_VERSION,
            BettingSlip.model_name == MODEL_NAME,
            BettingSlip.strategy_family == "generic",
            BettingSlip.slip_date >= date_from,
            BettingSlip.slip_date <= date_to,
        )
    ).all()
    picks: list[TrialPick] = []
    for (
        slip_id,
        slip_date,
        slip_key,
        event_key,
        market,
        predicted,
        model_prob,
        odds,
        fixture_event_key,
        event_status,
        event_winner,
        event_final_result,
        event_live,
        scores,
        event_game_result,
    ) in rows:
        fixture = None
        if fixture_event_key is not None:
            fixture = SimpleNamespace(
                event_key=fixture_event_key,
                event_status=event_status,
                event_winner=event_winner,
                event_final_result=event_final_result,
                event_live=event_live,
                scores=scores,
                event_game_result=event_game_result,
            )
        picks.append(
            TrialPick(
                slip_id=int(slip_id),
                slip_date=slip_date,
                slip_key=str(slip_key),
                event_key=int(event_key),
                market=str(market),
                model_prob=None if model_prob is None else float(model_prob),
                odds=None if odds is None else float(odds),
                outcome=settle_stored_pick(
                    market=str(market),
                    predicted_winner=predicted,
                    odds=None if odds is None else float(odds),
                    fixture=fixture,
                ),
            )
        )
    return picks


def build_slip_shape_trial(db: Session, *, as_of: date | None = None) -> dict:
    as_of = as_of or date.today()
    report = evaluate_slip_shape_trial(load_trial_picks(db, date_from=WINDOW_FROM, date_to=WINDOW_TO))
    passed_odds_bands = {
        check["band"]
        for check in report["checks"]
        if check["passed"] and check["dimension"] == "odds"
    }
    forward_picks = (
        load_trial_picks(db, date_from=FORWARD_FROM, date_to=as_of) if as_of >= FORWARD_FROM else []
    )
    report["forward"] = evaluate_forward_trial(
        forward_picks,
        passed_odds_bands=passed_odds_bands,
        min_samples=MIN_SAMPLES,
        as_of=as_of,
    )
    return report
