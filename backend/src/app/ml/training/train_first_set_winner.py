"""Prima validazione ("proviamo") del mercato Vincitore 1° set.

Riusa integralmente l'infrastruttura walk-forward gia' in produzione
(generazione fold, split temporale, anti-leakage: ``generate_walk_forward_folds``,
``slice_fold_frames``, ``WalkForwardConfig``, ``detect_leakage_flags`` da
``walk_forward.py``) e i benchmark generici gia' validati che NON dipendono dal
target (solo dalle feature): ``_atp_rank_probabilities``, ``_elo_probabilities``,
``_market_favorite_probabilities``, ``_market_no_vig_probabilities``.

NON riusa invece ``classification_metrics``/``market_benchmark_metrics``/
``_evaluate_official_contenders``: sono legati a doppio filo al mercato match
winner (value-bet/ROI calcolati sulle quote Home/Away, ``TARGET_COLUMN``
hardcoded a ``target_player_1_win``). Per il 1 set winner non esistono ancora
quote estratte (mercato diverso, non ancora ingerito): qui si valuta quindi
la SOLA qualita' di classificazione (accuracy/precision/recall/f1/roc_auc/
log_loss/brier), senza ROI — un secondo giro con value-bet reale sara'
possibile solo dopo aver estratto anche le quote "1st Set Winner" dal JSON
odds grezzo (lavoro futuro separato).

Target: ``score_parser.build_score_targets_dataframe`` (Fase 0), colonna
``target_first_set_winner``, agganciato al dataset v3 esistente (Elo/rank/
forma/H2H + quote match-winner aggregate) via merge su ``match_id``. Le righe
con punteggio non attendibile (ritiro/anomalia) hanno gia' target ``None``
(vedi ``score_targets_from_parsed``): il dropna standard di
``prepare_temporal_dataframe`` le esclude automaticamente.

Benchmark inclusi (oltre a logistic_regression/random_forest, stessi
iperparametri ufficiali di ``walk_forward._estimators``):

- ``coin_flip``: 0.5 costante (pavimento).
- ``market_favorite`` / ``market_no_vig``: quote di mercato del MATCH WINNER
  usate come proxy ingenuo per "chi vince il 1 set" — testa direttamente
  l'ipotesi che il favorito match sia anche favorito nel 1 set.
- ``atp_ranking`` / ``elo``: favorito per ranking/Elo storico.

Script di prima validazione: NON tocca ``train_baseline.py``, ``walk_forward.py``,
``model_registry.json`` ne' il modello pubblico. Report dedicato:
``data/reports/first_set_winner_walk_forward_results.json``.

Uso (da repo root, richiede DB per il merge dei target — vedi ``score_parser``)::

    python -m backend.src.app.ml.training.train_first_set_winner
    python -m backend.src.app.ml.training.train_first_set_winner --quick
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

from backend.src.app.ml.datasets.score_parser import (
    attach_score_targets_to_dataset,
    build_score_targets_dataframe,
)
from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR, select_training_dataset_path
from backend.src.app.ml.training.train_baseline import (
    ODDS_FEATURE_COLUMNS,
    build_preprocessor,
    selected_feature_columns,
)
from backend.src.app.ml.training.walk_forward import (
    MODEL_NAMES,
    WalkForwardConfig,
    WalkForwardFoldOutcome,
    WalkForwardFoldSpec,
    _atp_rank_probabilities,
    _date_max,
    _date_min,
    _elo_probabilities,
    _estimators,
    _fold_test_overlaps,
    _market_favorite_probabilities,
    _market_no_vig_probabilities,
    _mean_metrics,
    detect_leakage_flags,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

FIRST_SET_TARGET_COLUMN = "target_first_set_winner"
FIRST_SET_MODEL_VERSION_LABEL = "first_set_winner_v1"
FIRST_SET_MODEL_NAMES = MODEL_NAMES  # ("logistic_regression", "random_forest")
FIRST_SET_BENCHMARK_NAMES = (
    "coin_flip",
    "market_favorite",
    "market_no_vig",
    "atp_ranking",
    "elo",
)
RESULTS_FILENAME = "first_set_winner_walk_forward_results.json"

QUICK_CONFIG_OVERRIDES: dict[str, Any] = {
    "initial_train_days": 60,
    "test_days": 30,
    "step_days": 30,
    "min_train_rows": 20,
    "min_test_rows": 10,
}


def _coin_flip_probabilities(test: pd.DataFrame) -> pd.Series:
    return pd.Series(0.5, index=test.index, dtype=float)


def _first_set_benchmark_probabilities(test: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "coin_flip": _coin_flip_probabilities(test),
        "market_favorite": _market_favorite_probabilities(test),
        "market_no_vig": _market_no_vig_probabilities(test),
        "atp_ranking": _atp_rank_probabilities(test),
        "elo": _elo_probabilities(test),
    }


def build_first_set_winner_dataframe(
    db: Session,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    dataset_version: str = "v3",
) -> tuple[pd.DataFrame, Path]:
    """Dataset v3 (Elo/rank/forma/H2H + quote match-winner) + colonna
    ``target_first_set_winner`` agganciata via merge su ``match_id``."""
    dataset_path = select_training_dataset_path(processed_dir, version=dataset_version)  # type: ignore[arg-type]
    raw = pd.read_csv(dataset_path, low_memory=False)
    raw["match_id"] = pd.to_numeric(raw["match_id"], errors="coerce").astype("int64")

    score_targets = build_score_targets_dataframe(db)
    score_targets["match_id"] = pd.to_numeric(score_targets["match_id"], errors="coerce").astype("int64")

    merged = attach_score_targets_to_dataset(raw, score_targets)
    return merged, dataset_path


def _simple_classification_metrics(
    y_true: pd.Series,
    probabilities: pd.Series | None,
) -> dict[str, Any] | None:
    """Metriche di classificazione pure (no value-bet/ROI: nessuna quota
    "1 set winner" disponibile ancora). ``None`` se non calcolabile (nessuna
    riga utile o classe singola nel campione disponibile per questo
    contendente)."""
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

    return {
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


def evaluate_fold_models_first_set(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    dataset_path: str,
    fold: WalkForwardFoldSpec,
    config: WalkForwardConfig,
    model_names: tuple[str, ...] = FIRST_SET_MODEL_NAMES,
    benchmark_names: tuple[str, ...] = FIRST_SET_BENCHMARK_NAMES,
    estimators_factory=_estimators,
    feature_columns_override: list[str] | None = None,
) -> list[WalkForwardFoldOutcome]:
    """``feature_columns_override``: se fornito, sostituisce il feature-set v3
    standard (usato ad es. da ``train_first_set_winner_serve_stats_experiment.py``
    per testare feature aggiuntive senza duplicare tutta la logica di fold/
    leakage/metriche di questa funzione)."""
    from sklearn.pipeline import Pipeline

    feature_columns = (
        feature_columns_override
        if feature_columns_override is not None
        else selected_feature_columns(train, model_version="v3")
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
                model_version=FIRST_SET_MODEL_VERSION_LABEL,
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
                    fold=fold, model_version=FIRST_SET_MODEL_VERSION_LABEL, model_name=model_name,
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
            metrics = _simple_classification_metrics(y_test, probabilities)
            if metrics is None:
                outcomes.append(
                    WalkForwardFoldOutcome(
                        fold=fold, model_version=FIRST_SET_MODEL_VERSION_LABEL, model_name=model_name,
                        dataset_path=dataset_path, feature_set=feature_columns,
                        status="skipped_single_class", train_rows=len(train), test_rows=len(test),
                        skip_reason="Metriche non calcolabili sul test.",
                        leakage_flags=leakage_flags, coverage=coverage,
                    )
                )
                continue
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="completed",
                    train_rows=len(train), test_rows=len(test), metrics=metrics,
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
        except Exception as exc:  # noqa: BLE001 — fold isolation
            logger.exception(
                "First-set-winner fold=%s model=%s failed: %s", fold.fold_index, model_name, exc,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="error",
                    train_rows=len(train), test_rows=len(test), skip_reason=str(exc),
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )

    benchmark_probabilities = _first_set_benchmark_probabilities(test)
    for benchmark_name in benchmark_names:
        metrics = _simple_classification_metrics(y_test, benchmark_probabilities.get(benchmark_name))
        if metrics is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=FIRST_SET_MODEL_VERSION_LABEL, model_name=benchmark_name,
                    dataset_path=dataset_path, feature_set=feature_columns,
                    status="skipped_insufficient_data", train_rows=len(train), test_rows=len(test),
                    skip_reason="Benchmark non calcolabile (feature mancanti o classe singola).",
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
            continue
        outcomes.append(
            WalkForwardFoldOutcome(
                fold=fold, model_version=FIRST_SET_MODEL_VERSION_LABEL, model_name=benchmark_name,
                dataset_path=dataset_path, feature_set=feature_columns, status="completed",
                train_rows=len(train), test_rows=len(test), metrics=metrics,
                leakage_flags=leakage_flags, coverage=coverage,
            )
        )

    return outcomes


def run_first_set_winner_walk_forward(
    db: Session,
    *,
    config: WalkForwardConfig | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
) -> dict[str, Any]:
    resolved_config = config or WalkForwardConfig()
    resolved_config.validate()

    merged, dataset_path = build_first_set_winner_dataframe(db, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=FIRST_SET_TARGET_COLUMN, model_version="v3",
    )

    folds = generate_walk_forward_folds(dataframe, resolved_config)
    feature_set = selected_feature_columns(dataframe, model_version="v3")
    outcomes: list[WalkForwardFoldOutcome] = []
    leakage_flags = list(_fold_test_overlaps(folds))
    if not folds:
        leakage_flags.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            evaluate_fold_models_first_set(
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

    aggregate_metrics = _mean_metrics(completed)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "first_set_winner_first_validation",
        "target_column": FIRST_SET_TARGET_COLUMN,
        "base_feature_set_version": "v3",
        "model_names": list(FIRST_SET_MODEL_NAMES),
        "benchmark_names": list(FIRST_SET_BENCHMARK_NAMES),
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
        "aggregate_metrics": aggregate_metrics,
        "folds": [outcome.to_dict() for outcome in outcomes],
        "notes": [
            "Script di prima validazione: NON tocca train_baseline.py, walk_forward.py, "
            "model_registry.json ne' il modello pubblico. Report dedicato separato.",
            "Nessun value-bet/ROI: non esistono ancora quote estratte per il mercato "
            "'1st Set Winner' (solo Home/Away e' stato estratto finora, vedi odds_builder.py). "
            "Le metriche sono di sola classificazione (accuracy/roc_auc/log_loss/brier).",
            "'market_favorite'/'market_no_vig' usano le quote del MATCH WINNER come proxy "
            "ingenuo: un ROC AUC alto per questi due benchmark indicherebbe che il favorito "
            "match e' gia' un ottimo predittore del vincitore del 1 set, di per se'.",
            f"Feature-set: stesso v3 (Elo/rank/forma/H2H + {len(ODDS_FEATURE_COLUMNS)} colonne "
            "quote match-winner aggregate). Righe filtrate a odds valide (stesso filtro v3 "
            "ufficiale) e a punteggio set-by-set attendibile (score_parser, Fase 0).",
        ],
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    results_path = reports_path / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def format_first_set_winner_summary(report: dict[str, Any]) -> str:
    lines = [
        "Prima validazione — Vincitore 1 set (walk-forward)",
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
        if not agg:
            lines.append(f"--- {name}: nessun fold completato ---")
            continue
        lines.append(f"--- {name} (media sui fold completati, n={agg.get('folds_completed')}) ---")
        for key in ("roc_auc", "log_loss", "accuracy", "f1"):
            stat = agg.get(key, {})
            lines.append(f"  {key}: mean={stat.get('mean')} std={stat.get('std')} n={stat.get('n')}")
    lines.append("")
    if report["leakage_flags"]:
        lines.append(f"Leakage flags: {report['leakage_flags']}")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Prima validazione walk-forward del mercato Vincitore 1 set."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument(
        "--quick", action="store_true", help="Finestre piu' corte (smoke test).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config_kwargs: dict[str, Any] = {}
    if args.quick:
        config_kwargs.update(QUICK_CONFIG_OVERRIDES)
    config = WalkForwardConfig(**config_kwargs)

    with SessionLocal() as db:
        report = run_first_set_winner_walk_forward(
            db, config=config, processed_dir=args.processed_dir, reports_dir=args.reports_dir,
        )
    print(format_first_set_winner_summary(report))


if __name__ == "__main__":
    main()



