from __future__ import annotations

from typing import Any

# Display / expansion order for /partite multi-market rows.
MARKET_ROW_ORDER = ("match_winner", "first_set_winner", "over_under_games")


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
    elif lifecycle in {"cancelled", "abandoned", "unknown", "walkover", "retired"} and (
        prediction.get("actual_winner") not in {"First Player", "Second Player"}
    ):
        enriched["pick_status"] = "void"
    else:
        enriched["pick_status"] = "pending"

    if not enriched.get("market"):
        enriched["market"] = "match_winner"
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


def _player_label_for_selection(item: dict[str, Any], selection: str) -> str:
    if selection == "First Player":
        return str(item.get("event_first_player") or item.get("player_1") or selection)
    if selection == "Second Player":
        return str(item.get("event_second_player") or item.get("player_2") or selection)
    return selection


def _row_from_extra_market(
    item: dict[str, Any],
    extra: dict[str, Any],
    *,
    min_edge_percent: float,
) -> dict[str, Any] | None:
    """Build one /partite display row from a published extra-market tip."""
    selection = extra.get("selection")
    probability = extra.get("probability")
    if not selection or probability is None:
        return None

    odds = extra.get("odds")
    void_odds = extra.get("void_odds")
    if void_odds is None and float(probability) > 0:
        void_odds = 1.0 / float(probability)

    row = dict(item)
    row.pop("extra_markets", None)
    row["market"] = str(extra.get("market") or "")
    row["predicted_winner_label"] = _player_label_for_selection(item, str(selection))
    row["market_odds"] = float(odds) if odds is not None else None
    if void_odds is not None:
        row["void_odds"] = round(float(void_odds), 4)
    row["prediction"] = {
        "predicted_winner": selection,
        "confidence": float(probability),
        "predicted_winner_odds": float(odds) if odds is not None else None,
        "prob_player_1_win": (
            float(probability)
            if selection == "First Player"
            else (1.0 - float(probability) if selection == "Second Player" else None)
        ),
    }
    # Upcoming extra-market tips have no settlement in this payload.
    row["pick_status"] = "pending"
    row["value_decision"] = None
    if odds is not None and void_odds is not None:
        row["value_decision"] = classify_single_bet_value(
            float(odds), float(void_odds), min_edge_percent,
        )
    return row


def expand_fixtures_by_market(
    items: list[dict[str, Any]],
    *,
    min_edge_percent: float = 2.0,
) -> list[dict[str, Any]]:
    """One row per market tip: match winner + published first-set / O/U.

    Keeps fixture order; within a fixture emits Match, then 1° set, then O/U
    when each tip exists. Fixtures without any tip are still emitted once as
    match-winner placeholders (prediction missing → \"Da generare\").
    """
    order_index = {name: index for index, name in enumerate(MARKET_ROW_ORDER)}
    expanded: list[dict[str, Any]] = []
    for item in items:
        market_rows: list[dict[str, Any]] = []

        match_row = dict(item)
        match_row.pop("extra_markets", None)
        match_row["market"] = "match_winner"
        if match_row.get("prediction") or not item.get("extra_markets"):
            market_rows.append(match_row)

        extras = list(item.get("extra_markets") or [])
        extras_sorted = sorted(
            extras,
            key=lambda entry: order_index.get(str(entry.get("market") or ""), 99),
        )
        for extra in extras_sorted:
            row = _row_from_extra_market(
                item,
                extra if isinstance(extra, dict) else {},
                min_edge_percent=min_edge_percent,
            )
            if row is not None:
                market_rows.append(row)

        if not market_rows:
            fallback = dict(item)
            fallback.pop("extra_markets", None)
            fallback["market"] = "match_winner"
            market_rows.append(fallback)
        expanded.extend(market_rows)
    return expanded
