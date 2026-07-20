from __future__ import annotations

from typing import Any


def classify_single_bet_value(
    market_odds: float,
    void_odds: float,
    min_edge_percent: float,
) -> str:
    play_threshold = void_odds * (1.0 + (min_edge_percent / 100.0))
    if market_odds >= play_threshold:
        return "PLAY"
    if market_odds < void_odds:
        return "NO BET"
    return "BORDERLINE"


def model_prob_for_winner(predicted_winner: str | None, prob_player_1_win: float | None) -> float | None:
    if predicted_winner == "First Player":
        return prob_player_1_win
    if predicted_winner == "Second Player" and prob_player_1_win is not None:
        return 1.0 - float(prob_player_1_win)
    return None


def enrich_fixture_value(
    item: dict[str, Any],
    *,
    min_edge_percent: float,
    smva_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach void_odds / value_decision using SMVA row or prediction fallback."""
    enriched = dict(item)
    prediction = enriched.get("prediction") or {}

    void_odds = None
    market_odds = None
    decision = None

    if smva_item:
        void_odds = smva_item.get("void_odds")
        market_odds = smva_item.get("market_odds")
        if void_odds is not None and market_odds is not None:
            decision = classify_single_bet_value(
                float(market_odds),
                float(void_odds),
                min_edge_percent,
            )

    if decision is None:
        model_prob = model_prob_for_winner(
            prediction.get("predicted_winner"),
            prediction.get("prob_player_1_win"),
        )
        market_odds = prediction.get("predicted_winner_odds")
        if model_prob is not None and model_prob > 0 and market_odds is not None:
            void_odds = 1.0 / float(model_prob)
            decision = classify_single_bet_value(
                float(market_odds),
                void_odds,
                min_edge_percent,
            )

    if void_odds is not None:
        enriched["void_odds"] = round(float(void_odds), 4)
    if decision is not None:
        enriched["value_decision"] = decision
    if market_odds is not None:
        enriched["market_odds"] = float(market_odds)

    is_correct = prediction.get("is_correct")
    lifecycle = item.get("match_lifecycle_status")
    if is_correct is True:
        enriched["pick_status"] = "won"
    elif is_correct is False:
        enriched["pick_status"] = "lost"
    elif lifecycle in {"cancelled", "abandoned", "unknown_problem", "walkover", "retired"} and (
        prediction.get("actual_winner") not in {"First Player", "Second Player"}
    ):
        enriched["pick_status"] = "void"
    else:
        enriched["pick_status"] = "pending"

    return enriched


def enrich_fixtures_with_value(
    items: list[dict[str, Any]],
    *,
    min_edge_percent: float,
    smva_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_match = {
        item.get("match_id"): item
        for item in (smva_items or [])
        if item.get("match_id") is not None
    }
    return [
        enrich_fixture_value(
            item,
            min_edge_percent=min_edge_percent,
            smva_item=by_match.get(item.get("event_key")),
        )
        for item in items
    ]
