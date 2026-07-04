"""Select the active prediction model from saved evaluation metrics."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.src.app.ml.model_versioning import MODEL_VERSIONS, REPORTS_DIR, ModelVersion


PREFERRED_METRICS = ("roc_auc", "accuracy", "log_loss")


@dataclass(frozen=True)
class SelectedModel:
    model_version: ModelVersion
    model_name: str
    metric_name: str
    metric_value: float
    metrics_path: Path


def _read_metrics(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as metrics_file:
        return json.load(metrics_file)


def _model_metrics(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if isinstance(payload.get("models"), dict) and payload["models"]:
        return {
            str(name): metrics
            for name, metrics in payload["models"].items()
            if isinstance(metrics, dict)
        }

    if isinstance(payload.get("comparison"), list) and payload["comparison"]:
        return {
            str(item["model"]): item
            for item in payload["comparison"]
            if isinstance(item, dict) and item.get("model")
        }

    ignored = {
        "split",
        "features_used",
        "features_excluded",
        "market_benchmark",
        "model_paths",
        "model_version",
        "metrics_path",
        "dataset_used",
        "rank_features_note",
        "warnings",
    }
    return {
        key: value
        for key, value in payload.items()
        if key not in ignored and isinstance(value, dict)
    }


def _metric_for_selection(metrics_by_model: dict[str, dict[str, Any]]) -> str:
    for metric_name in PREFERRED_METRICS:
        values = [
            metrics.get(metric_name)
            for metrics in metrics_by_model.values()
            if isinstance(metrics.get(metric_name), int | float)
        ]
        if values:
            return metric_name
    raise ValueError("No supported model selection metric found.")


def select_best_model(
    model_version: ModelVersion = "v2",
    reports_dir: Path = REPORTS_DIR,
) -> SelectedModel:
    """Choose the best saved model for a version.

    Selection policy: prefer highest ``roc_auc`` when present, otherwise highest
    ``accuracy``. If only ``log_loss`` is available, choose the lowest value.
    """

    metrics_path = reports_dir / MODEL_VERSIONS[model_version].metrics_filename
    if not metrics_path.exists():
        raise FileNotFoundError(f"Metrics report not found: {metrics_path}")

    metrics_by_model = _model_metrics(_read_metrics(metrics_path))
    if not metrics_by_model:
        raise ValueError(f"No model metrics found in {metrics_path}")

    metric_name = _metric_for_selection(metrics_by_model)
    reverse = metric_name != "log_loss"
    candidates = [
        (name, float(metrics[metric_name]))
        for name, metrics in metrics_by_model.items()
        if isinstance(metrics.get(metric_name), int | float)
    ]
    model_name, metric_value = sorted(
        candidates,
        key=lambda item: item[1],
        reverse=reverse,
    )[0]

    return SelectedModel(
        model_version=model_version,
        model_name=model_name,
        metric_name=metric_name,
        metric_value=metric_value,
        metrics_path=metrics_path,
    )
