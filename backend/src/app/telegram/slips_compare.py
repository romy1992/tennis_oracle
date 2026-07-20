from __future__ import annotations

from typing import Any


def slip_pick_signature(pick: dict[str, Any]) -> tuple[Any, ...]:
    return (
        pick.get("event_key"),
        pick.get("predicted_winner") or pick.get("predicted_winner_label"),
    )


def betting_slips_signature(slips: list[dict[str, Any]] | None) -> tuple[tuple[Any, ...], ...]:
    """Stable signature of slip contents (matches + predicted winners)."""
    items: list[tuple[Any, ...]] = []
    for slip in slips or []:
        picks = tuple(slip_pick_signature(pick) for pick in (slip.get("picks") or []))
        items.append((slip.get("slip_key") or slip.get("label"), picks))
    return tuple(sorted(items, key=lambda item: str(item[0] or "")))


def betting_slips_equivalent(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    left_slips = (left or {}).get("slips") or []
    right_slips = (right or {}).get("slips") or []
    if not left_slips and not right_slips:
        return True
    return betting_slips_signature(left_slips) == betting_slips_signature(right_slips)


def select_distinct_model_payloads(
    payloads: list[dict[str, Any]],
    *,
    preferred_model_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Keep one payload when all model slips match; otherwise keep every non-empty
    payload whose content differs from those already selected.
    """
    non_empty = [payload for payload in payloads if payload.get("slips")]
    if not non_empty:
        return []

    preferred = None
    if preferred_model_name:
        for payload in non_empty:
            if payload.get("model_name") == preferred_model_name:
                preferred = payload
                break
    preferred = preferred or non_empty[0]

    if all(betting_slips_equivalent(preferred, other) for other in non_empty):
        return [preferred]

    selected: list[dict[str, Any]] = []
    for payload in non_empty:
        if any(betting_slips_equivalent(payload, existing) for existing in selected):
            continue
        selected.append(payload)
    return selected


def fixtures_signature(items: list[dict[str, Any]] | None) -> tuple[tuple[Any, ...], ...]:
    rows: list[tuple[Any, ...]] = []
    for item in items or []:
        prediction = item.get("prediction") or {}
        rows.append(
            (
                item.get("event_key"),
                prediction.get("predicted_winner"),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row[0] is None, row[0])))


def fixtures_equivalent(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> bool:
    if not left and not right:
        return True
    return fixtures_signature(left) == fixtures_signature(right)


def select_distinct_fixture_models(
    model_items: list[tuple[str, list[dict[str, Any]]]],
    *,
    preferred_model_name: str | None = None,
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Keep one model list when predictions match; otherwise keep differing lists."""
    non_empty = [(name, items) for name, items in model_items if items]
    if not non_empty:
        return []

    preferred = None
    if preferred_model_name:
        for name, items in non_empty:
            if name == preferred_model_name:
                preferred = (name, items)
                break
    preferred = preferred or non_empty[0]

    if all(fixtures_equivalent(preferred[1], other[1]) for other in non_empty):
        return [preferred]

    selected: list[tuple[str, list[dict[str, Any]]]] = []
    for entry in non_empty:
        if any(fixtures_equivalent(entry[1], existing[1]) for existing in selected):
            continue
        selected.append(entry)
    return selected
