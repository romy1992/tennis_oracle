"""Unit tests for live tipbook metrics (known numeric cases)."""

from __future__ import annotations

from backend.src.app.services.live_betting_metrics import (
    average,
    hit_rate,
    hit_rate_pct,
    longest_streaks,
    max_drawdown,
    roi_pct,
    yield_pct,
)


def test_hit_rate_known_case():
    # 3 won, 1 lost → 75%
    assert hit_rate(3, 1) == 0.75
    assert hit_rate_pct(3, 1) == 75.0
    assert hit_rate(0, 0) is None
    assert hit_rate_pct(0, 2) == 0.0


def test_roi_and_yield_identical_stake_weighted():
    # Bets: +0.80, -1.0, +1.20 on unit stakes → profit +1.0 on stake 3 → 33.333...%
    profit = 0.80 - 1.0 + 1.20
    stake = 3.0
    expected = (profit / stake) * 100.0
    assert roi_pct(profit, stake) == expected
    assert yield_pct(profit, stake) == expected
    assert roi_pct(1.0, 0.0) is None


def test_variable_stake_roi():
    # stake 2 @ 2.0 win → +2; stake 1 lose → -1; profit +1 on settled stake 3 → 33.333...%
    profit = 2.0 - 1.0
    stake_settled = 2.0 + 1.0
    assert round(roi_pct(profit, stake_settled) or 0.0, 6) == round(100.0 / 3.0, 6)


def test_max_drawdown_known_equity_curve():
    # Equity: 0 → +1 → +0 → +2 → -1  (profits: +1, -1, +2, -3)
    # peaks: 1, 1, 2, 2; trough after last = -1; drawdown from peak 2 to -1 = 3
    assert max_drawdown([1.0, -1.0, 2.0, -3.0]) == 3.0
    assert max_drawdown([]) == 0.0
    assert max_drawdown([0.5, 0.5, 0.5]) == 0.0


def test_longest_streaks_known_sequence():
    # W W L W W W L L → max win 3, max loss 2
    max_win, max_loss = longest_streaks(
        ["won", "won", "lost", "won", "won", "won", "lost", "lost"]
    )
    assert max_win == 3
    assert max_loss == 2
    assert longest_streaks([]) == (0, 0)


def test_average_odds():
    assert average([1.5, 2.5]) == 2.0
    assert average([]) is None
