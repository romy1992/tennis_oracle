"""Validazione walk-forward del Vincitore 1° set CON quote dedicate.

A differenza di ``train_first_set_winner.py`` (classificazione pura, quote
match-winner usate solo come proxy), qui si estraggono le quote reali
``Home/Away (1st Set)`` e si valutano ROI/value-bet sullo stesso mercato
del target. Feature: v3 (Elo/rank/forma/H2H + quote match-winner) +
aggregati 1° set (``FIRST_SET_ODDS_FEATURE_COLUMNS``).

NON tocca ``train_baseline.py``, ``model_registry.json`` ne' ``first_set_winner_v1``.
Report standalone: ``data/reports/first_set_winner_odds_walk_forward_results.json``.
``build_first_set_winner_odds_dataframe``/``evaluate_fold_models_first_set_odds``
sono riusate anche dal motore walk-forward ufficiale (persistito su DB, vedi
``walk_forward_markets.py``) — questo script CLI resta comunque disponibile
invariato per validazioni ad-hoc.

Uso (da repo root, richiede DB)::

    python -m backend.src.app.ml.training.train_first_set_winner_odds
    python -m backend.src.app.ml.training.train_first_set_winner_odds --quick
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.first_set_winner_odds_builder import (
    FIRST_SET_ODDS_FEATURE_COLUMNS,
    build_first_set_odds_dataframe,
)
from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR
from backend.src.app.ml.training.train_baseline import build_preprocessor, selected_feature_columns
from backend.src.app.ml.training.train_first_set_winner import (
    FIRST_SET_TARGET_COLUMN,
    build_first_set_winner_dataframe,
)
from backend.src.app.ml.training.train_over_under_games import _mean_value_bet_metrics
from backend.src.app.ml.training.walk_forward import (
    MODEL_NAMES,
    WalkForwardConfig,
    WalkForwardFoldOutcome,
    WalkForwardFoldSpec,
    _compute_official_metrics,
    _date_max,
    _date_min,
    _estimators,
    _fold_test_overlaps,
    _market_no_vig_probabilities,
    _mean_metrics,
    detect_leakage_flags,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

FIRST_SET_ODDS_MODEL_VERSION_LABEL = "first_set_winner_v2"
FIRST_SET_ODDS_MODEL_NAMES = MODEL_NAMES
FIRST_SET_ODDS_BENCHMARK_NAMES = (
    "coin_flip",
    "market_favorite",
    "market_no_vig",
    "match_winner_no_vig",
)
RESULTS_FILENAME = "first_set_winner_odds_walk_forward_results.json"

QUICK_CONFIG_OVERRIDES: dict[str, Any] = {
    "initial_train_days": 60,
    "test_days": 30,
    "step_days": 30,
    "min_train_rows": 20,
    "min_test_rows": 10,
}


def _coin_flip_probabilities(test: pd.DataFrame) -> pd.Series:
    return pd.Series(0.5, index=test.index, dtype=float)


def _market_favorite_first_set_probabilities(test: pd.DataFrame) -> pd.Series:
    p1_odds = pd.to_numeric(test.get("avg_first_set_player_1_odds"), errors="coerce")
    p2_odds = pd.to_numeric(test.get("avg_first_set_player_2_odds"), errors="coerce")
    probabilities = pd.Series(index=test.index, dtype=float)
    favorite_p1 = (p1_odds < p2_odds) & p1_odds.notna() & p2_odds.notna()
    favorite_p2 = (p2_odds < p1_odds) & p1_odds.notna() & p2_odds.notna()
    tie = (p1_odds == p2_odds) & p1_odds.notna()
    probabilities.loc[favorite_p1] = 1.0
    probabilities.loc[favorite_p2] = 0.0
    probabilities.loc[tie] = 0.5
    return probabilities


def _market_no_vig_first_set_probabilities(test: pd.DataFrame) -> pd.Series:
    p1_odds = pd.to_numeric(test.get("avg_first_set_player_1_odds"), errors="coerce")
    p2_odds = pd.to_numeric(test.get("avg_first_set_player_2_odds"), errors="coerce")
    denom = (1.0 / p1_odds) + (1.0 / p2_odds)
    probs = (1.0 / p1_odds) / denom
    return probs.where((p1_odds > 1.0) & (p2_odds > 1.0) & denom.notna() & (denom > 0.0))


def _first_set_odds_benchmark_probabilities(test: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "coin_flip": _coin_flip_probabilities(test),
        "market_favorite": _market_favorite_first_set_probabilities(test),
        "market_no_vig": _market_no_vig_first_set_probabilities(test),
        "match_winner_no_vig": _market_no_vig_probabilities(test),
    }


def build_first_set_winner_odds_dataframe(
    db: Session,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    dataset_version: str = "v3",
) -> tuple[pd.DataFrame, Path]:
    """Dataset v3 + target 1° set + feature quote ``Home/Away (1st Set)``."""
    merged, dataset_path = build_first_set_winner_dataframe(
        db, processed_dir=processed_dir, dataset_version=dataset_version,
    )
    merged["match_date"] = pd.to_datetime(merged["match_date"], errors="coerce").dt.date.astype("string")

    odds_fs = build_first_set_odds_dataframe(db)
    if not odds_fs.empty:
        odds_fs["match_id"] = pd.to_numeric(odds_fs["match_id"], errors="coerce").astype("int64")
        odds_fs["match_date"] = pd.to_datetime(odds_fs["match_date"], errors="coerce").dt.date.astype("string")
        merged["match_id"] = pd.to_numeric(merged["match_id"], errors="coerce").astype("int64")
        merged = merged.merge(odds_fs, on=["match_id", "match_date"], how="left", validate="one_to_one")
    return merged, dataset_path


def _classification_and_roi_metrics(
    y_true: pd.Series,
    probabilities: pd.Series | None,
    test: pd.DataFrame,
) -> dict[str, Any] | None:
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        confusion_matrix,
        f1_score,
        log_loss,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    if probabilities is None:
        return None
    probs_numeric = pd.to_numeric(probabilities, errors="coerce")
    mask = probs_numeric.notna() & y_true.notna()
    if mask.sum() == 0:
        return None

    y = y_true.loc[mask].astype(int)
    if y.nunique() < 2:
        return None
    probs = probs_numeric.loc[mask].astype(float).clip(lower=1e-6, upper=1.0 - 1e-6)
    predictions = (probs >= 0.5).astype(int)
    try:
        roc_auc = round(float(roc_auc_score(y, probs)), 6)
    except ValueError:
        roc_auc = None

    metrics: dict[str, Any] = {
        "accuracy": round(float(accuracy_score(y, predictions)), 6),
        "precision": round(float(precision_score(y, predictions, zero_division=0)), 6),
        "recall": round(float(recall_score(y, predictions, zero_division=0)), 6),
        "f1": round(float(f1_score(y, predictions, zero_division=0)), 6),
        "roc_auc": roc_auc,
        "log_loss": round(float(log_loss(y, probs, labels=[0, 1])), 6),
        "brier_score": round(float(brier_score_loss(y, probs)), 6),
        "confusion_matrix": confusion_matrix(y, predictions, labels=[0, 1]).tolist(),
        "class_distribution": {int(k): int(v) for k, v in y.value_counts().to_dict().items()},
        "eval_rows": int(mask.sum()),
        "eval_rows_total": int(len(y_true)),
    }

    if (
        "avg_first_set_player_1_odds" in test.columns
        and "avg_first_set_player_2_odds" in test.columns
    ):
        p1_odds = pd.to_numeric(test["avg_first_set_player_1_odds"], errors="coerce").loc[mask]
        p2_odds = pd.to_numeric(test["avg_first_set_player_2_odds"], errors="coerce").loc[mask]
        metrics["value_bet"] = _compute_official_metrics(y, probs, p1_odds, p2_odds)
    else:
        metrics["value_bet"] = None
    return metrics


def evaluate_fold_models_first_set_odds(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    dataset_path: str,
    fold: WalkForwardFoldSpec,
    config: WalkForwardConfig,
    model_names: tuple[str, ...] = FIRST_SET_ODDS_MODEL_NAMES,
    benchmark_names: tuple[str, ...] = FIRST_SET_ODDS_BENCHMARK_NAMES,
    estimators_factory=_estimators,
    feature_columns_override: list[str] | None = None,
) -> list[WalkForwardFoldOutcome]:
    from sklearn.pipeline import Pipeline

    feature_columns = (
        feature_columns_override
        if feature_columns_override is not None
        else selected_feature_columns(train, model_version="v3") + [
            column for column in FIRST_SET_ODDS_FEATURE_COLUMNS if column in train.columns
        ]
    )
    leakage_flags = detect_leakage_flags(
        feature_columns, fold, model_version="v3", train=train, test=test,
    )
    coverage = {
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "train_date_min": fold.train_start.isoformat(),
        "train_date_max": fold.train_end.isoformat(),
        "test_date_min": fold.test_start.isoformat(),
        "test_date_max": fold.test_end.isoformat(),
        "features_count": len(feature_columns),
    }
    all_names = (*model_names, *benchmark_names)

    def _skip_all(status: str, reason: str) -> list[WalkForwardFoldOutcome]:
        return [
            WalkForwardFoldOutcome(
                fold=fold,
                model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL,
                model_name=name,
                dataset_path=dataset_path,
                feature_set=feature_columns,
                status=status,  # type: ignore[arg-type]
                train_rows=len(train),
                test_rows=len(test),
                skip_reason=reason,
                leakage_flags=leakage_flags,
                coverage=coverage,
            )
            for name in all_names
        ]

    if len(train) < config.min_train_rows or len(test) < config.min_test_rows:
        return _skip_all(
            "skipped_insufficient_data",
            f"Dati insufficienti: train={len(train)} (min {config.min_train_rows}), "
            f"test={len(test)} (min {config.min_test_rows}).",
        )
    if not feature_columns:
        return _skip_all("skipped_insufficient_data", "Nessuna feature pre-match disponibile.")

    y_train = train[FIRST_SET_TARGET_COLUMN].astype(int)
    y_test = test[FIRST_SET_TARGET_COLUMN].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return _skip_all(
            "skipped_single_class",
            "Classe singola nel train o nel test: metriche non calcolabili.",
        )

    x_train = train[feature_columns]
    x_test = test[feature_columns]
    estimators = estimators_factory(config.random_state)
    outcomes: list[WalkForwardFoldOutcome] = []

    for model_name in model_names:
        if model_name not in estimators:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="error",
                    train_rows=len(train), test_rows=len(test),
                    skip_reason=f"Modello sconosciuto: {model_name}",
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
            continue
        try:
            pipeline = Pipeline(
                steps=[
                    ("preprocessor", build_preprocessor(train, feature_columns)),
                    ("model", estimators[model_name]),
                ]
            )
            pipeline.fit(x_train, y_train)
            probabilities = pd.Series(pipeline.predict_proba(x_test)[:, 1], index=test.index)
            metrics = _classification_and_roi_metrics(y_test, probabilities, test)
            if metrics is None:
                outcomes.append(
                    WalkForwardFoldOutcome(
                        fold=fold, model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL, model_name=model_name,
                        dataset_path=dataset_path, feature_set=feature_columns,
                        status="skipped_single_class", train_rows=len(train), test_rows=len(test),
                        skip_reason="Metriche non calcolabili sul test.",
                        leakage_flags=leakage_flags, coverage=coverage,
                    )
                )
                continue
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="completed",
                    train_rows=len(train), test_rows=len(test), metrics=metrics,
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
        except Exception as exc:  # noqa: BLE001 — fold isolation
            logger.exception(
                "First-set-odds fold=%s model=%s failed: %s", fold.fold_index, model_name, exc,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="error",
                    train_rows=len(train), test_rows=len(test), skip_reason=str(exc),
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )

    benchmark_probabilities = _first_set_odds_benchmark_probabilities(test)
    for benchmark_name in benchmark_names:
        metrics = _classification_and_roi_metrics(y_test, benchmark_probabilities.get(benchmark_name), test)
        if metrics is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL, model_name=benchmark_name,
                    dataset_path=dataset_path, feature_set=feature_columns,
                    status="skipped_insufficient_data", train_rows=len(train), test_rows=len(test),
                    skip_reason="Benchmark non calcolabile (feature mancanti o classe singola).",
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
            continue
        outcomes.append(
            WalkForwardFoldOutcome(
                fold=fold, model_version=FIRST_SET_ODDS_MODEL_VERSION_LABEL, model_name=benchmark_name,
                dataset_path=dataset_path, feature_set=feature_columns, status="completed",
                train_rows=len(train), test_rows=len(test), metrics=metrics,
                leakage_flags=leakage_flags, coverage=coverage,
            )
        )

    return outcomes


def run_first_set_winner_odds_walk_forward(
    db: Session,
    *,
    config: WalkForwardConfig | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    results_filename: str | None = None,
) -> dict[str, Any]:
    resolved_config = config or WalkForwardConfig()
    resolved_config.validate()

    merged, dataset_path = build_first_set_winner_odds_dataframe(db, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=FIRST_SET_TARGET_COLUMN, model_version="v3",
    )
    if (
        "avg_first_set_player_1_odds" in dataframe.columns
        and "avg_first_set_player_2_odds" in dataframe.columns
    ):
        has_odds = (
            pd.to_numeric(dataframe["avg_first_set_player_1_odds"], errors="coerce").notna()
            & pd.to_numeric(dataframe["avg_first_set_player_2_odds"], errors="coerce").notna()
        )
        dataframe = dataframe.loc[has_odds].reset_index(drop=True)

    folds = generate_walk_forward_folds(dataframe, resolved_config)
    feature_set = selected_feature_columns(dataframe, model_version="v3") + [
        column for column in FIRST_SET_ODDS_FEATURE_COLUMNS if column in dataframe.columns
    ]
    outcomes: list[WalkForwardFoldOutcome] = []
    leakage_flags = list(_fold_test_overlaps(folds))
    if not folds:
        leakage_flags.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            evaluate_fold_models_first_set_odds(
                train, test, dataset_path=str(dataset_path), fold=fold, config=resolved_config,
            )
        )

    completed = [item for item in outcomes if item.status == "completed"]
    skipped = [item for item in outcomes if item.status.startswith("skipped")]
    errors = [item for item in outcomes if item.status == "error"]
    for outcome in outcomes:
        leakage_flags.extend(outcome.leakage_flags)
    seen: set[str] = set()
    unique_leakage: list[str] = []
    for flag in leakage_flags:
        if flag not in seen:
            seen.add(flag)
            unique_leakage.append(flag)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "first_set_winner_odds_validation",
        "target_column": FIRST_SET_TARGET_COLUMN,
        "provider_market": "Home/Away (1st Set)",
        "base_feature_set_version": "v3",
        "model_names": list(FIRST_SET_ODDS_MODEL_NAMES),
        "benchmark_names": list(FIRST_SET_ODDS_BENCHMARK_NAMES),
        "config": {
            "mode": resolved_config.mode,
            "initial_train_days": resolved_config.initial_train_days,
            "test_days": resolved_config.test_days,
            "step_days": resolved_config.step_days,
            "min_train_rows": resolved_config.min_train_rows,
            "min_test_rows": resolved_config.min_test_rows,
            "embargo_days": resolved_config.embargo_days,
            "random_state": resolved_config.random_state,
        },
        "dataset_path": str(dataset_path),
        "dataset_rows": int(len(dataframe)),
        "date_min": _date_min(dataframe),
        "date_max": _date_max(dataframe),
        "feature_set": feature_set,
        "feature_set_count": len(feature_set),
        "coverage": {
            "folds_planned": len(folds),
            "fold_outcomes": len(outcomes),
            "completed": len(completed),
            "skipped": len(skipped),
            "errors": len(errors),
        },
        "leakage_flags": unique_leakage,
        "aggregate_metrics": _mean_metrics(completed),
        "aggregate_value_bet_metrics": _mean_value_bet_metrics(completed),
        "folds": [outcome.to_dict() for outcome in outcomes],
        "notes": [
            "Script di validazione: NON tocca train_baseline.py, walk_forward.py, "
            "model_registry.json ne' first_set_winner_v1. Report dedicato.",
            "Mercato provider 'Home/Away (1st Set)'. Righe senza quote 1° set "
            "escluse (confronto equo modello-vs-mercato). value_bet/ROI calcolati "
            "sulle quote 1° set reali, non sul proxy match-winner.",
            "Benchmark 'match_winner_no_vig' e' il proxy usato da first_set_winner_v1 "
            "(quote Home/Away della partita) per confrontare se le quote dedicate "
            "migliorano il segnale.",
            f"Feature-set: v3 + {len(FIRST_SET_ODDS_FEATURE_COLUMNS)} colonne quote 1° set.",
        ],
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    results_path = reports_path / (results_filename or RESULTS_FILENAME)
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def format_first_set_winner_odds_summary(report: dict[str, Any]) -> str:
    lines = [
        "Validazione — Vincitore 1° set con quote dedicate (walk-forward)",
        f"Dataset: {report['dataset_path']}",
        f"  {report['dataset_rows']} righe ({report['date_min']} - {report['date_max']})",
        f"Feature totali usate: {report['feature_set_count']}",
        (
            f"Config: mode={report['config']['mode']} "
            f"initial_train_days={report['config']['initial_train_days']} "
            f"test_days={report['config']['test_days']} step_days={report['config']['step_days']}"
        ),
        (
            f"Fold: pianificati={report['coverage']['folds_planned']} "
            f"completati={report['coverage']['completed']} "
            f"skipped={report['coverage']['skipped']} errors={report['coverage']['errors']}"
        ),
        "",
    ]
    for name in (*report["model_names"], *report["benchmark_names"]):
        agg = report["aggregate_metrics"].get(name, {})
        roi_agg = report["aggregate_value_bet_metrics"].get(name, {})
        if not agg:
            lines.append(f"--- {name}: nessun fold completato ---")
            continue
        lines.append(f"--- {name} (media sui fold completati, n={agg.get('folds_completed')}) ---")
        for key in ("roc_auc", "log_loss", "accuracy", "f1"):
            stat = agg.get(key, {})
            lines.append(f"  {key}: mean={stat.get('mean')} std={stat.get('std')} n={stat.get('n')}")
        for key in ("roi", "yield", "max_drawdown"):
            stat = roi_agg.get(key, {})
            lines.append(f"  {key}: mean={stat.get('mean')} std={stat.get('std')} n={stat.get('n')}")
    lines.append("")
    if report["leakage_flags"]:
        lines.append(f"Leakage flags: {report['leakage_flags']}")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Validazione walk-forward del Vincitore 1° set con quote dedicate."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--quick", action="store_true", help="Finestre piu' corte (smoke test).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = WalkForwardConfig(**QUICK_CONFIG_OVERRIDES) if args.quick else WalkForwardConfig()
    with SessionLocal() as db:
        report = run_first_set_winner_odds_walk_forward(
            db,
            config=config,
            processed_dir=args.processed_dir,
            reports_dir=args.reports_dir,
        )
    print(format_first_set_winner_odds_summary(report))


if __name__ == "__main__":
    main()
