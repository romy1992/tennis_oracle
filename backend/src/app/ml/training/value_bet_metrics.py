"""Value bet backtest metrics using model edge vs market probability."""

from typing import Any

import pandas as pd

from backend.src.app.ml.datasets.odds_builder import profit_for_unit_stake, roi, yield_rate

DEFAULT_EDGE_THRESHOLD = 0.03
TARGET_COLUMN = "target_player_1_win"


def market_probability_column(dataframe: pd.DataFrame) -> str | None:
    if "market_prob_player_1" in dataframe.columns:
        return "market_prob_player_1"
    if "avg_market_prob_player_1" in dataframe.columns:
        return "avg_market_prob_player_1"
    return None


def compute_value_bet_metrics(
    test_dataframe: pd.DataFrame,
    model_probabilities: pd.Series | list[float],
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
) -> dict[str, Any]:
    probabilities = pd.Series(model_probabilities, index=test_dataframe.index, dtype=float)
    market_column = market_probability_column(test_dataframe)
    odds_column = "avg_player_1_odds" if "avg_player_1_odds" in test_dataframe.columns else None

    if market_column is None or odds_column is None or TARGET_COLUMN not in test_dataframe.columns:
        return _empty_value_bet_metrics(len(test_dataframe), edge_threshold)

    frame = test_dataframe[[TARGET_COLUMN, market_column, odds_column]].copy()
    frame["model_prob_player_1"] = probabilities
    frame[TARGET_COLUMN] = pd.to_numeric(frame[TARGET_COLUMN], errors="coerce")
    frame[market_column] = pd.to_numeric(frame[market_column], errors="coerce")
    frame[odds_column] = pd.to_numeric(frame[odds_column], errors="coerce")
    frame = frame.dropna(subset=[TARGET_COLUMN, market_column, odds_column, "model_prob_player_1"])
    if frame.empty:
        return _empty_value_bet_metrics(len(test_dataframe), edge_threshold)

    frame["edge_player_1"] = frame["model_prob_player_1"] - frame[market_column]
    bets = frame[frame["edge_player_1"] >= edge_threshold].copy()
    if bets.empty:
        return {
            "edge_threshold": edge_threshold,
            "bets_count": 0,
            "hit_rate": 0.0,
            "total_profit": 0.0,
            "roi": 0.0,
            "yield": 0.0,
            "odds_coverage_rows": int(len(frame)),
            "odds_coverage_pct": _coverage_pct(len(frame), len(test_dataframe)),
        }

    results = bets[TARGET_COLUMN].astype(int) == 1
    profits = [
        profit_for_unit_stake(float(odd), bool(won))
        for odd, won in zip(bets[odds_column], results)
    ]
    return {
        "edge_threshold": edge_threshold,
        "bets_count": int(len(bets)),
        "hit_rate": round(float(results.mean()), 6),
        "total_profit": round(float(sum(profits)), 6),
        "roi": round(float(roi(profits)), 6),
        "yield": round(float(yield_rate(profits)), 6),
        "odds_coverage_rows": int(len(frame)),
        "odds_coverage_pct": _coverage_pct(len(frame), len(test_dataframe)),
    }


def compute_match_winner_play_metrics(
    test_dataframe: pd.DataFrame,
    model_probabilities: pd.Series | list[float],
    *,
    min_edge_percent: float,
) -> dict[str, Any]:
    """Backtest the same predicted-side PLAY rule used by the live service."""
    probabilities = pd.Series(model_probabilities, index=test_dataframe.index, dtype=float)
    required_columns = {TARGET_COLUMN, "avg_player_1_odds", "avg_player_2_odds"}
    if not required_columns.issubset(test_dataframe.columns):
        return _empty_match_winner_play_metrics(len(test_dataframe), min_edge_percent)

    frame = test_dataframe[list(required_columns)].copy()
    frame["model_prob_player_1"] = probabilities
    for column in required_columns | {"model_prob_player_1"}:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=list(required_columns) + ["model_prob_player_1"])
    frame = frame.loc[
        frame["model_prob_player_1"].between(0.0, 1.0)
        & (frame["avg_player_1_odds"] > 1.0)
        & (frame["avg_player_2_odds"] > 1.0)
    ].copy()
    if frame.empty:
        return _empty_match_winner_play_metrics(len(test_dataframe), min_edge_percent)

    predicts_player_1 = frame["model_prob_player_1"] >= 0.5
    frame["selected_probability"] = frame["model_prob_player_1"].where(
        predicts_player_1,
        1.0 - frame["model_prob_player_1"],
    )
    frame["selected_odds"] = frame["avg_player_1_odds"].where(
        predicts_player_1,
        frame["avg_player_2_odds"],
    )
    frame["edge_percent"] = (
        frame["selected_odds"] * frame["selected_probability"] - 1.0
    ) * 100.0
    bets = frame.loc[frame["edge_percent"] >= min_edge_percent].copy()
    if bets.empty:
        return _empty_match_winner_play_metrics(
            len(test_dataframe),
            min_edge_percent,
            odds_coverage_rows=len(frame),
        )

    bet_predicts_player_1 = bets["model_prob_player_1"] >= 0.5
    results = (bets[TARGET_COLUMN].astype(int) == 1).where(
        bet_predicts_player_1,
        bets[TARGET_COLUMN].astype(int) == 0,
    )
    profits = [
        profit_for_unit_stake(float(odd), bool(won))
        for odd, won in zip(bets["selected_odds"], results)
    ]
    return {
        "min_edge_percent": min_edge_percent,
        "bets_count": int(len(bets)),
        "hit_rate": round(float(results.mean()), 6),
        "total_profit": round(float(sum(profits)), 6),
        "roi": round(float(roi(profits)), 6),
        "yield": round(float(yield_rate(profits)), 6),
        "avg_odds": round(float(bets["selected_odds"].mean()), 6),
        "avg_edge_percent": round(float(bets["edge_percent"].mean()), 6),
        "odds_coverage_rows": int(len(frame)),
        "odds_coverage_pct": _coverage_pct(len(frame), len(test_dataframe)),
    }


def _coverage_pct(covered_rows: int, total_rows: int) -> float:
    if total_rows <= 0:
        return 0.0
    return round((covered_rows / total_rows) * 100, 6)


def _empty_value_bet_metrics(
    total_rows: int,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
) -> dict[str, Any]:
    return {
        "edge_threshold": edge_threshold,
        "bets_count": 0,
        "hit_rate": 0.0,
        "total_profit": 0.0,
        "roi": 0.0,
        "yield": 0.0,
        "odds_coverage_rows": 0,
        "odds_coverage_pct": _coverage_pct(0, total_rows),
    }


def _empty_match_winner_play_metrics(
    total_rows: int,
    min_edge_percent: float,
    *,
    odds_coverage_rows: int = 0,
) -> dict[str, Any]:
    return {
        "min_edge_percent": min_edge_percent,
        "bets_count": 0,
        "hit_rate": 0.0,
        "total_profit": 0.0,
        "roi": 0.0,
        "yield": 0.0,
        "avg_odds": None,
        "avg_edge_percent": None,
        "odds_coverage_rows": odds_coverage_rows,
        "odds_coverage_pct": _coverage_pct(odds_coverage_rows, total_rows),
    }
