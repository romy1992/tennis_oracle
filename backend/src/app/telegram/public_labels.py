from __future__ import annotations

from typing import Any


SERIES_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def format_accuracy_pct(accuracy_pct: float | None) -> str:
    if accuracy_pct is None:
        return "n.d."
    return f"{float(accuracy_pct):.1f}%"


def public_model_label(
    *,
    accuracy_pct: float | None,
    series_index: int | None = None,
) -> str:
    """User-facing label without technical model names."""
    accuracy = format_accuracy_pct(accuracy_pct)
    if series_index is None:
        return f"Predizione (accuratezza {accuracy})"
    letter = SERIES_LETTERS[series_index] if 0 <= series_index < len(SERIES_LETTERS) else str(series_index + 1)
    return f"Serie {letter} · accuratezza {accuracy}"


def accuracy_by_model_name(prediction_summary: dict[str, Any] | None) -> dict[str, float | None]:
    result: dict[str, float | None] = {}
    for row in (prediction_summary or {}).get("breakdown") or []:
        name = row.get("model_name")
        if not name:
            continue
        accuracy = row.get("accuracy_pct")
        result[str(name)] = float(accuracy) if accuracy is not None else None
    return result


def build_public_labels(
    model_names: list[str],
    *,
    accuracy_by_model: dict[str, float | None],
    force_series_letters: bool = False,
) -> dict[str, str]:
    """
    Map internal model_name -> public label.
    When multiple models are shown, use Serie A/B ordered by accuracy desc.
    """
    unique = [name for name in model_names if name]
    if not unique:
        return {}

    ranked = sorted(
        unique,
        key=lambda name: (
            accuracy_by_model.get(name) is None,
            -(accuracy_by_model.get(name) or 0.0),
            name,
        ),
    )
    use_letters = force_series_letters or len(ranked) > 1
    labels: dict[str, str] = {}
    for index, name in enumerate(ranked):
        labels[name] = public_model_label(
            accuracy_pct=accuracy_by_model.get(name),
            series_index=index if use_letters else None,
        )
    return labels


def slip_row_for_model(
    slip_stats_payload: dict[str, Any] | None,
    *,
    model_version: str,
    model_name: str,
) -> dict[str, Any] | None:
    for row in (slip_stats_payload or {}).get("rows") or []:
        if row.get("model_version") == model_version and row.get("model_name") == model_name:
            return row
    return None


def prediction_row_for_model(
    prediction_summary: dict[str, Any] | None,
    *,
    model_version: str,
    model_name: str,
) -> dict[str, Any] | None:
    for row in (prediction_summary or {}).get("breakdown") or []:
        if row.get("model_version") == model_version and row.get("model_name") == model_name:
            return row
    return None


def build_stats_series(
    *,
    model_names: list[str],
    model_version: str,
    prediction_summary: dict[str, Any] | None,
    slip_stats: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    accuracy_map = accuracy_by_model_name(prediction_summary)
    labels = build_public_labels(model_names, accuracy_by_model=accuracy_map, force_series_letters=True)
    ranked = sorted(
        [name for name in model_names if name],
        key=lambda name: (
            accuracy_map.get(name) is None,
            -(accuracy_map.get(name) or 0.0),
            name,
        ),
    )
    series: list[dict[str, Any]] = []
    for name in ranked:
        prediction = prediction_row_for_model(
            prediction_summary,
            model_version=model_version,
            model_name=name,
        ) or {}
        slip = slip_row_for_model(
            slip_stats,
            model_version=model_version,
            model_name=name,
        ) or {}
        series.append(
            {
                "model_name": name,
                "label": labels.get(name) or public_model_label(accuracy_pct=None, series_index=len(series)),
                "prediction": prediction,
                "slip": slip,
            }
        )
    return series
