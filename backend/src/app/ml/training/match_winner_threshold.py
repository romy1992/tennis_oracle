"""Temporal, production-aligned tuning of the match-winner PLAY threshold.

The experiment trains the active v4 voting ensemble in walk-forward folds and
uses only out-of-sample probabilities.  Thresholds are expressed exactly like
the live application: ``(selected_odds * selected_probability - 1) * 100``.
No registry, model artifact, public configuration, or official latest report is
modified.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR
from backend.src.app.ml.training.calibration import (
    OosPredictionBatch,
    collect_oos_predictions_for_version,
)
from backend.src.app.ml.training.walk_forward import (
    V4_ENSEMBLE_MODEL_NAME,
    WalkForwardConfig,
)

MODEL_VERSION = "v4"
CURRENT_LIVE_THRESHOLD_PERCENT = 2.0
LEGACY_WALK_FORWARD_THRESHOLD_PERCENT = 3.0
DEFAULT_THRESHOLDS_PERCENT = tuple(float(value) for value in range(0, 16)) + (20.0, 25.0)
DEFAULT_MIN_PRIOR_BETS = 100
DEFAULT_CONFIDENCE_Z = 1.96
MATURE_INITIAL_TRAIN_DAYS = 1095
EXPERIMENT_REPORTS_DIRNAME = "experiments"


@dataclass(frozen=True)
class ThresholdTuningConfig:
    thresholds_percent: tuple[float, ...] = DEFAULT_THRESHOLDS_PERCENT
    baseline_threshold_percent: float = CURRENT_LIVE_THRESHOLD_PERCENT
    min_prior_bets: int = DEFAULT_MIN_PRIOR_BETS
    confidence_z: float = DEFAULT_CONFIDENCE_Z

    def validate(self) -> None:
        if not self.thresholds_percent:
            raise ValueError("thresholds_percent non puo' essere vuoto.")
        if any(not math.isfinite(value) or value < 0 for value in self.thresholds_percent):
            raise ValueError("Le soglie devono essere finite e >= 0.")
        if self.baseline_threshold_percent < 0:
            raise ValueError("baseline_threshold_percent deve essere >= 0.")
        if self.min_prior_bets < 1:
            raise ValueError("min_prior_bets deve essere >= 1.")
        if self.confidence_z <= 0:
            raise ValueError("confidence_z deve essere > 0.")


@dataclass(frozen=True)
class _SelectionArrays:
    candidates_count: int
    edges_percent: np.ndarray
    profits: np.ndarray
    wins: np.ndarray
    odds: np.ndarray


def _round(value: Any, digits: int = 6) -> Any:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def _selection_arrays(
    batches: Iterable[OosPredictionBatch],
    threshold_percent: float,
) -> _SelectionArrays:
    edge_parts: list[np.ndarray] = []
    profit_parts: list[np.ndarray] = []
    win_parts: list[np.ndarray] = []
    odds_parts: list[np.ndarray] = []
    candidates_count = 0

    for batch in batches:
        if batch.player_1_odds is None or batch.player_2_odds is None:
            raise ValueError("Quote player 1/player 2 mancanti nel batch OOS.")
        probabilities = np.asarray(batch.prob_raw, dtype=float)
        y_true = np.asarray(batch.y_true, dtype=int)
        player_1_odds = np.asarray(batch.player_1_odds, dtype=float)
        player_2_odds = np.asarray(batch.player_2_odds, dtype=float)
        if not (
            len(probabilities)
            == len(y_true)
            == len(player_1_odds)
            == len(player_2_odds)
        ):
            raise ValueError("Lunghezze incoerenti nel batch OOS.")

        predicts_player_1 = probabilities >= 0.5
        selected_probabilities = np.where(
            predicts_player_1, probabilities, 1.0 - probabilities
        )
        selected_odds = np.where(predicts_player_1, player_1_odds, player_2_odds)
        valid = (
            np.isfinite(selected_probabilities)
            & np.isfinite(selected_odds)
            & (selected_probabilities > 0.0)
            & (selected_probabilities <= 1.0)
            & (selected_odds > 1.0)
        )
        candidates_count += int(valid.sum())
        edges_percent = (selected_odds * selected_probabilities - 1.0) * 100.0
        selected = valid & (edges_percent >= threshold_percent)
        if not selected.any():
            continue

        wins = np.where(predicts_player_1, y_true == 1, y_true == 0)[selected]
        selected_market_odds = selected_odds[selected]
        profits = np.where(wins, selected_market_odds - 1.0, -1.0)
        edge_parts.append(edges_percent[selected])
        profit_parts.append(profits.astype(float))
        win_parts.append(wins.astype(bool))
        odds_parts.append(selected_market_odds.astype(float))

    empty_float = np.asarray([], dtype=float)
    empty_bool = np.asarray([], dtype=bool)
    return _SelectionArrays(
        candidates_count=candidates_count,
        edges_percent=np.concatenate(edge_parts) if edge_parts else empty_float,
        profits=np.concatenate(profit_parts) if profit_parts else empty_float,
        wins=np.concatenate(win_parts) if win_parts else empty_bool,
        odds=np.concatenate(odds_parts) if odds_parts else empty_float,
    )


def _metrics_from_selection(
    selection: _SelectionArrays,
    *,
    threshold_percent: float | None,
    confidence_z: float,
) -> dict[str, Any]:
    bets_count = int(len(selection.profits))
    if bets_count == 0:
        return {
            "threshold_percent": threshold_percent,
            "candidates_count": selection.candidates_count,
            "bets_count": 0,
            "coverage_pct": 0.0,
            "hit_rate": None,
            "total_profit": 0.0,
            "roi": None,
            "roi_percent": None,
            "roi_ci_lower": None,
            "roi_ci_upper": None,
            "avg_odds": None,
            "avg_edge_percent": None,
        }

    roi_value = float(selection.profits.mean())
    if bets_count > 1:
        standard_error = float(selection.profits.std(ddof=1) / math.sqrt(bets_count))
        ci_lower = roi_value - confidence_z * standard_error
        ci_upper = roi_value + confidence_z * standard_error
    else:
        ci_lower = None
        ci_upper = None
    return {
        "threshold_percent": threshold_percent,
        "candidates_count": selection.candidates_count,
        "bets_count": bets_count,
        "coverage_pct": _round(
            bets_count / selection.candidates_count * 100.0
            if selection.candidates_count
            else 0.0
        ),
        "hit_rate": _round(selection.wins.mean()),
        "total_profit": _round(selection.profits.sum()),
        "roi": _round(roi_value),
        "roi_percent": _round(roi_value * 100.0),
        "roi_ci_lower": _round(ci_lower),
        "roi_ci_upper": _round(ci_upper),
        "avg_odds": _round(selection.odds.mean()),
        "avg_edge_percent": _round(selection.edges_percent.mean()),
    }


def evaluate_threshold(
    batches: Iterable[OosPredictionBatch],
    threshold_percent: float,
    *,
    confidence_z: float = DEFAULT_CONFIDENCE_Z,
) -> dict[str, Any]:
    selection = _selection_arrays(batches, threshold_percent)
    return _metrics_from_selection(
        selection,
        threshold_percent=threshold_percent,
        confidence_z=confidence_z,
    )


def _choose_threshold(
    batches: list[OosPredictionBatch],
    config: ThresholdTuningConfig,
) -> tuple[float, list[dict[str, Any]], str]:
    diagnostics = [
        evaluate_threshold(batches, threshold, confidence_z=config.confidence_z)
        for threshold in sorted(set(config.thresholds_percent))
    ]
    eligible = [
        item
        for item in diagnostics
        if item["bets_count"] >= config.min_prior_bets
        and item["roi_ci_lower"] is not None
    ]
    if not eligible:
        return config.baseline_threshold_percent, diagnostics, "fallback_insufficient_prior_bets"
    winner = max(
        eligible,
        key=lambda item: (
            float(item["roi_ci_lower"]),
            float(item["roi"]),
            float(item["threshold_percent"]),
        ),
    )
    return float(winner["threshold_percent"]), diagnostics, "max_prior_roi_lower_ci"


def _evaluate_variable_thresholds(
    batch_threshold_pairs: list[tuple[OosPredictionBatch, float]],
    *,
    confidence_z: float,
) -> dict[str, Any]:
    selections = [
        _selection_arrays([batch], threshold)
        for batch, threshold in batch_threshold_pairs
    ]
    combined = _SelectionArrays(
        candidates_count=sum(item.candidates_count for item in selections),
        edges_percent=np.concatenate([item.edges_percent for item in selections]),
        profits=np.concatenate([item.profits for item in selections]),
        wins=np.concatenate([item.wins for item in selections]),
        odds=np.concatenate([item.odds for item in selections]),
    )
    return _metrics_from_selection(
        combined,
        threshold_percent=None,
        confidence_z=confidence_z,
    )


def temporal_threshold_retuning(
    batches: list[OosPredictionBatch],
    config: ThresholdTuningConfig,
) -> dict[str, Any]:
    """Choose on prior OOS folds and evaluate only on the immediately next fold."""
    config.validate()
    ordered = sorted(batches, key=lambda item: (item.test_start, item.fold_index))
    per_fold: list[dict[str, Any]] = []
    tuned_pairs: list[tuple[OosPredictionBatch, float]] = []
    baseline_pairs: list[tuple[OosPredictionBatch, float]] = []

    for index in range(1, len(ordered)):
        prior = ordered[:index]
        evaluation = ordered[index]
        selected_threshold, diagnostics, reason = _choose_threshold(prior, config)
        tuned_metrics = evaluate_threshold(
            [evaluation], selected_threshold, confidence_z=config.confidence_z
        )
        baseline_metrics = evaluate_threshold(
            [evaluation],
            config.baseline_threshold_percent,
            confidence_z=config.confidence_z,
        )
        tuned_pairs.append((evaluation, selected_threshold))
        baseline_pairs.append((evaluation, config.baseline_threshold_percent))
        selected_prior = next(
            (
                item
                for item in diagnostics
                if item["threshold_percent"] == selected_threshold
            ),
            None,
        )
        per_fold.append(
            {
                "fold_index": evaluation.fold_index,
                "test_start": evaluation.test_start.isoformat(),
                "test_end": evaluation.test_end.isoformat(),
                "prior_folds_count": len(prior),
                "selected_threshold_percent": selected_threshold,
                "selection_reason": reason,
                "selected_threshold_prior_metrics": selected_prior,
                "tuned_evaluation": tuned_metrics,
                "baseline_evaluation": baseline_metrics,
            }
        )

    tuned_aggregate = _evaluate_variable_thresholds(
        tuned_pairs, confidence_z=config.confidence_z
    ) if tuned_pairs else _metrics_from_selection(
        _SelectionArrays(0, np.array([]), np.array([]), np.array([]), np.array([])),
        threshold_percent=None,
        confidence_z=config.confidence_z,
    )
    baseline_aggregate = _evaluate_variable_thresholds(
        baseline_pairs, confidence_z=config.confidence_z
    ) if baseline_pairs else _metrics_from_selection(
        _SelectionArrays(0, np.array([]), np.array([]), np.array([]), np.array([])),
        threshold_percent=config.baseline_threshold_percent,
        confidence_z=config.confidence_z,
    )
    positive_folds = sum(
        1
        for item in per_fold
        if (item["tuned_evaluation"].get("total_profit") or 0.0) > 0.0
    )
    return {
        "selection_rule": (
            "For each fold, maximize the lower normal 95% CI of ROI using only prior "
            "OOS folds and thresholds with at least min_prior_bets."
        ),
        "warmup_folds_excluded_from_evaluation": 1 if ordered else 0,
        "evaluation_folds": len(per_fold),
        "positive_evaluation_folds": positive_folds,
        "per_fold": per_fold,
        "tuned_aggregate": tuned_aggregate,
        "baseline_aggregate_same_folds": baseline_aggregate,
    }


def build_threshold_report(
    batches: list[OosPredictionBatch],
    *,
    tuning_config: ThresholdTuningConfig,
    walk_forward_config: WalkForwardConfig,
) -> dict[str, Any]:
    tuning_config.validate()
    if len(batches) < 2:
        raise ValueError("Servono almeno due fold OOS per la ritaratura temporale.")
    ordered = sorted(batches, key=lambda item: (item.test_start, item.fold_index))
    diagnostic_grid = [
        evaluate_threshold(ordered, threshold, confidence_z=tuning_config.confidence_z)
        for threshold in sorted(set(tuning_config.thresholds_percent))
    ]
    candidate_threshold, _diagnostics, candidate_reason = _choose_threshold(
        ordered, tuning_config
    )
    temporal = temporal_threshold_retuning(ordered, tuning_config)
    tuned = temporal["tuned_aggregate"]
    baseline = temporal["baseline_aggregate_same_folds"]
    evaluation_folds = int(temporal["evaluation_folds"])
    positive_folds = int(temporal["positive_evaluation_folds"])
    required_positive_folds = math.ceil(evaluation_folds * 0.6)
    enough_bets = int(tuned["bets_count"]) >= tuning_config.min_prior_bets
    beats_baseline = (
        tuned["roi"] is not None
        and baseline["roi"] is not None
        and float(tuned["roi"]) > float(baseline["roi"])
    )
    positive_roi = tuned["roi"] is not None and float(tuned["roi"]) > 0.0
    stable_folds = positive_folds >= required_positive_folds
    promising = bool(enough_bets and beats_baseline and positive_roi and stable_folds)
    lower_ci_positive = (
        tuned["roi_ci_lower"] is not None and float(tuned["roi_ci_lower"]) > 0.0
    )
    passes_offline_gate = bool(promising and lower_ci_positive and evaluation_folds >= 4)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "match_winner_play_threshold_retuning",
        "model_version": MODEL_VERSION,
        "model_name": V4_ENSEMBLE_MODEL_NAME,
        "probability_kind": "raw",
        "does_not_change_production": True,
        "metric_contract": {
            "predicted_side": "player_1 if probability >= 0.5 else player_2",
            "edge_percent": "(selected_odds * selected_probability - 1) * 100",
            "profit": "selected_odds - 1 on win, -1 on loss, unit stake",
            "alignment": "Same PLAY threshold formula used by single_match_value.py",
        },
        "walk_forward_config": asdict(walk_forward_config),
        "tuning_config": asdict(tuning_config),
        "oos_coverage": {
            "folds": len(ordered),
            "date_min": ordered[0].test_start.isoformat(),
            "date_max": ordered[-1].test_end.isoformat(),
            "samples": sum(item.n_samples for item in ordered),
        },
        "baselines_full_oos_diagnostic": {
            "current_live_2_percent": evaluate_threshold(
                ordered,
                CURRENT_LIVE_THRESHOLD_PERCENT,
                confidence_z=tuning_config.confidence_z,
            ),
            "legacy_walk_forward_3_percent": evaluate_threshold(
                ordered,
                LEGACY_WALK_FORWARD_THRESHOLD_PERCENT,
                confidence_z=tuning_config.confidence_z,
            ),
        },
        "diagnostic_grid_full_oos_not_selection_proof": diagnostic_grid,
        "temporal_retuning": temporal,
        "candidate_for_shadow_validation": {
            "threshold_percent": candidate_threshold,
            "selection_reason": candidate_reason,
            "note": "Selected on all available OOS folds; validate on future shadow data before production.",
        },
        "decision": {
            "promising": promising,
            "passes_offline_gate": passes_offline_gate,
            "criteria": {
                "enough_bets": enough_bets,
                "beats_current_2_percent_on_same_future_folds": beats_baseline,
                "positive_nested_roi": positive_roi,
                "positive_fold_share_at_least_60_percent": stable_folds,
                "roi_lower_95_ci_positive": lower_ci_positive,
                "at_least_4_evaluation_folds": evaluation_folds >= 4,
            },
            "next_step": (
                "shadow_validation_only"
                if promising
                else "keep_current_production_threshold_and_do_not_promote_candidate"
            ),
        },
    }


def write_threshold_report(
    report: dict[str, Any],
    *,
    reports_dir: str | Path = REPORTS_DIR,
    output_path: str | Path | None = None,
) -> Path:
    if output_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = (
            Path(reports_dir)
            / EXPERIMENT_REPORTS_DIRNAME
            / f"match_winner_threshold_{stamp}.json"
        )
    else:
        path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return path


def run_threshold_experiment(
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    walk_forward_config: WalkForwardConfig | None = None,
    tuning_config: ThresholdTuningConfig | None = None,
    output_path: str | Path | None = None,
) -> tuple[dict[str, Any], Path]:
    wf = walk_forward_config or WalkForwardConfig(
        initial_train_days=MATURE_INITIAL_TRAIN_DAYS
    )
    tuning = tuning_config or ThresholdTuningConfig()
    batches = collect_oos_predictions_for_version(
        MODEL_VERSION,
        wf,
        processed_dir=processed_dir,
        reports_dir=reports_dir,
        model_names=(V4_ENSEMBLE_MODEL_NAME,),
    )[V4_ENSEMBLE_MODEL_NAME]
    report = build_threshold_report(
        batches,
        tuning_config=tuning,
        walk_forward_config=wf,
    )
    path = write_threshold_report(
        report,
        reports_dir=reports_dir,
        output_path=output_path,
    )
    report["report_path"] = str(path)
    return report, path


def format_threshold_summary(report: dict[str, Any]) -> str:
    temporal = report["temporal_retuning"]
    tuned = temporal["tuned_aggregate"]
    baseline = temporal["baseline_aggregate_same_folds"]
    candidate = report["candidate_for_shadow_validation"]["threshold_percent"]
    decision = report["decision"]
    return "\n".join(
        [
            f"OOS folds: {report['oos_coverage']['folds']} ({report['oos_coverage']['date_min']} -> {report['oos_coverage']['date_max']})",
            f"Candidate threshold: {candidate}%",
            f"Nested tuned: bets={tuned['bets_count']} ROI={tuned['roi_percent']}% profit={tuned['total_profit']}",
            f"Current 2% same folds: bets={baseline['bets_count']} ROI={baseline['roi_percent']}% profit={baseline['total_profit']}",
            f"Promising={decision['promising']} offline_gate={decision['passes_offline_gate']} next={decision['next_step']}",
        ]
    )


def _parse_thresholds(raw: str) -> tuple[float, ...]:
    return tuple(float(item.strip()) for item in raw.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--thresholds",
        default=",".join(str(value) for value in DEFAULT_THRESHOLDS_PERCENT),
        help="Comma-separated PLAY thresholds in percent.",
    )
    parser.add_argument("--min-prior-bets", type=int, default=DEFAULT_MIN_PRIOR_BETS)
    parser.add_argument("--initial-train-days", type=int, default=MATURE_INITIAL_TRAIN_DAYS)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    tuning = ThresholdTuningConfig(
        thresholds_percent=_parse_thresholds(args.thresholds),
        min_prior_bets=args.min_prior_bets,
    )
    wf = WalkForwardConfig(initial_train_days=args.initial_train_days)
    report, path = run_threshold_experiment(
        walk_forward_config=wf,
        tuning_config=tuning,
        output_path=args.output,
    )
    print(format_threshold_summary(report))
    print(f"Report: {path}")


if __name__ == "__main__":
    main()
