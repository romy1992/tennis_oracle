"""Slip-shape trial: selection gate and short coupon, without a database."""

from datetime import date, timedelta

from backend.src.app.services.slip_shape_trial import (
    TrialPick,
    evaluate_forward_trial,
    evaluate_slip_shape_trial,
)


def _pick(
    *,
    slip_id: int,
    slip_date: date,
    event_key: int,
    market: str = "match_winner",
    model_prob: float = 0.6,
    odds: float = 1.6,
    outcome: str = "won",
    slip_key: str = "play_safe",
) -> TrialPick:
    return TrialPick(
        slip_id=slip_id,
        slip_date=slip_date,
        slip_key=slip_key,
        event_key=event_key,
        market=market,
        model_prob=model_prob,
        odds=odds,
        outcome=outcome,
    )


def _band_sample(day: date, *, won: bool, count: int, start_event: int) -> list[TrialPick]:
    return [
        _pick(
            slip_id=start_event + offset,
            slip_date=day,
            event_key=start_event + offset,
            odds=1.6,
            model_prob=0.7,
            outcome="won" if won else "lost",
        )
        for offset in range(count)
    ]


def test_odds_band_must_win_on_both_halves():
    picks = _band_sample(date(2026, 8, 10), won=True, count=4, start_event=1)
    picks += _band_sample(date(2026, 9, 10), won=False, count=4, start_event=100)
    report = evaluate_slip_shape_trial(picks, min_samples=4)
    odds_check = next(
        row for row in report["checks"] if row["dimension"] == "odds" and row["band"] == "1.50-1.80"
    )
    assert odds_check["passed"] is False
    assert report["selection_passed"] is False
    assert "Nessuna fascia" in report["conclusion"]


def test_odds_band_passes_when_both_halves_are_positive():
    picks = _band_sample(date(2026, 8, 10), won=True, count=4, start_event=1)
    picks += _band_sample(date(2026, 9, 10), won=True, count=4, start_event=100)
    picks.append(
        _pick(
            slip_id=999,
            slip_date=date(2026, 8, 10),
            event_key=999,
            odds=1.05,
            model_prob=0.99,
            outcome="lost",
        )
    )
    report = evaluate_slip_shape_trial(picks, min_samples=4)
    assert "quota 1.50-1.80" in report["passing_rules"]
    assert report["selection_passed"] is True
    assert report["short_slips"]["slips_lost"] == 0
    assert report["short_slips"]["slips_won"] == 2


def test_short_slip_keeps_two_highest_probabilities_and_drops_other_markets():
    day = date(2026, 8, 20)
    picks = [
        _pick(slip_id=1, slip_date=day, event_key=1, model_prob=0.91, odds=1.5, outcome="won"),
        _pick(slip_id=1, slip_date=day, event_key=2, model_prob=0.8, odds=1.4, outcome="lost"),
        _pick(slip_id=1, slip_date=day, event_key=3, model_prob=0.55, odds=2.2, outcome="won"),
        _pick(
            slip_id=1,
            slip_date=day,
            event_key=4,
            market="over_under_games",
            model_prob=0.99,
            odds=1.9,
            outcome="won",
        ),
        _pick(
            slip_id=2,
            slip_date=day,
            event_key=1,
            model_prob=0.5,
            odds=1.5,
            outcome="lost",
            slip_key="mixed_safe",
        ),
    ]
    report = evaluate_slip_shape_trial(picks, min_samples=30)
    short = report["short_slips"]
    assert short["slips_won"] == 0
    assert short["slips_lost"] == 1
    assert short["picks_won"] == 1
    assert short["picks_lost"] == 1
    assert short["roi_pct"] == -100.0
    assert report["over_under_singles"]["won"] == 1


def test_short_slip_pays_the_product_of_the_two_odds():
    day = date(2026, 9, 2)
    picks = [
        _pick(slip_id=1, slip_date=day, event_key=1, model_prob=0.9, odds=1.5, outcome="won"),
        _pick(slip_id=1, slip_date=day, event_key=2, model_prob=0.8, odds=1.4, outcome="won"),
    ]
    report = evaluate_slip_shape_trial(picks, min_samples=30)
    # stake 10 at combined 2.10 → profit 11
    assert report["short_slips"]["profit_units"] == 11.0
    assert report["short_slips"]["roi_pct"] == 110.0


def test_forward_trial_ignores_the_band_that_did_not_pass_and_waits_for_thirty_slips():
    picks = [
        _pick(slip_id=1, slip_date=date(2026, 10, 6), event_key=1, odds=1.6, outcome="won"),
        _pick(slip_id=2, slip_date=date(2026, 10, 7), event_key=2, odds=1.2, model_prob=0.99, outcome="lost"),
        _pick(slip_id=3, slip_date=date(2026, 10, 4), event_key=3, odds=1.6, outcome="won"),
    ]
    report = evaluate_forward_trial(
        picks,
        passed_odds_bands={"1.50-1.80"},
        min_samples=30,
        as_of=date(2026, 10, 10),
    )
    assert report["ready"] is False
    assert report["settled_slips"] == 1
    assert report["short_slips"]["slips_lost"] == 0
    assert "30" in report["note"]


def test_forward_trial_is_ready_after_thirty_closed_slips():
    start = date(2026, 10, 6)
    picks = [
        _pick(
            slip_id=index,
            slip_date=start + timedelta(days=index),
            event_key=index,
            odds=1.6,
            outcome="won",
        )
        for index in range(30)
    ]
    report = evaluate_forward_trial(
        picks,
        passed_odds_bands={"1.50-1.80"},
        min_samples=30,
        as_of=start + timedelta(days=40),
    )
    assert report["ready"] is True
    assert report["settled_slips"] == 30


def test_pending_leg_stays_out_of_roi():
    day = date(2026, 8, 12)
    picks = [
        _pick(slip_id=1, slip_date=day, event_key=1, model_prob=0.9, odds=1.5, outcome="won"),
        _pick(slip_id=1, slip_date=day, event_key=2, model_prob=0.8, odds=1.4, outcome="pending"),
    ]
    report = evaluate_slip_shape_trial(picks, min_samples=30)
    assert report["short_slips"]["slips_pending"] == 1
    assert report["short_slips"]["roi_pct"] is None
