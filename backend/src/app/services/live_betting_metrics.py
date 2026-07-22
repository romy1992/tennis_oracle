"""Live tipbook betting metrics (published ledger only).

Completely separate from ML training / backtest helpers in
``app.ml.training.value_bet_metrics`` and ``app.ml.datasets.odds_builder``.

Conventions (all stake/profit in the same unit as ``PublishedPrediction.unit_stake``):

- **Open**: match not settled (pending lifecycle).
- **Void**: settled as void (stake refunded; excluded from hit rate, ROI, yield).
- **Closed**: won or lost (stake at risk was realized).
- **Hit rate** = won / (won + lost). Voids and open excluded.
- **Stake totale** = sum of ``unit_stake`` over the tip population (including open/void).
- **Stake settled** = sum of ``unit_stake`` over won+lost only (ROI/yield denominator).
- **Profitto** = sum of realized P/L (won: stake*(odds-1); lost: -stake; void/open: 0).
- **ROI %** = profit / stake_settled * 100 (``None`` if stake_settled == 0).
- **Yield %** = same formula as ROI % under this product convention (stake-weighted).
- **Quota media** = arithmetic mean of published decimal odds on tips that have odds.
- **Max drawdown** = largest peak-to-trough decline on the cumulative equity curve
  built from closed bets in chronological order (voids/open skipped).
- **Serie +/-** = longest consecutive won / lost runs in that same closed sequence
  (voids/open do not break or extend a streak; they are skipped).
"""

from __future__ import annotations

from typing import Iterable, Literal, Sequence

OutcomeClosed = Literal["won", "lost"]


def hit_rate(won: int, lost: int) -> float | None:
    closed = won + lost
    if closed <= 0:
        return None
    return won / closed


def hit_rate_pct(won: int, lost: int) -> float | None:
    rate = hit_rate(won, lost)
    if rate is None:
        return None
    return rate * 100.0


def roi_pct(profit: float, stake_settled: float) -> float | None:
    if stake_settled <= 0:
        return None
    return (profit / stake_settled) * 100.0


def yield_pct(profit: float, stake_settled: float) -> float | None:
    """Stake-weighted yield; identical to ``roi_pct`` by product convention."""
    return roi_pct(profit, stake_settled)


def average(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def max_drawdown(profits_chronological: Iterable[float]) -> float:
    """Largest peak-to-trough drop on cumulative equity starting at 0.

    Returns a non-negative absolute drawdown in stake units (0 if never declined).
    """
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for profit in profits_chronological:
        equity += float(profit)
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > worst:
            worst = drawdown
    return worst


def longest_streaks(outcomes: Sequence[OutcomeClosed]) -> tuple[int, int]:
    """Return (max_winning_streak, max_losing_streak)."""
    max_win = 0
    max_loss = 0
    current_win = 0
    current_loss = 0
    for outcome in outcomes:
        if outcome == "won":
            current_win += 1
            current_loss = 0
            if current_win > max_win:
                max_win = current_win
        else:
            current_loss += 1
            current_win = 0
            if current_loss > max_loss:
                max_loss = current_loss
    return max_win, max_loss


def round_metric(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
