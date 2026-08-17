"""Prima validazione ("proviamo") del mercato Over/Under sul TOTALE GAME IN PARTITA.

Secondo mercato della sequenza (dopo "vincitore 1 set", vedi
``train_first_set_winner.py``) nel piano di espansione incrementale verso
nuovi eventi di predizione, sempre riusando l'infrastruttura walk-forward
condivisa (``generate_walk_forward_folds``, ``slice_fold_frames``,
``WalkForwardConfig``, ``detect_leakage_flags`` da ``walk_forward.py``).

A differenza del 1 set winner, per questo mercato ESISTONO quote di mercato
dirette (``over_under_games_odds_builder.py``, mercato provider "Over/Under by
Games in Match", linea di riferimento 20.5 — la piu' diffusa, 84% dei match
con questo mercato): la validazione include quindi, oltre alla classificazione
pura, anche ROI/value-bet REALI (non un proxy), riusando
``walk_forward._compute_official_metrics`` passando le quote Over/Under al
posto di quelle player_1/player_2 (stessa formula: profit per unit stake sulla
side scelta dal modello/benchmark).

Target: ``score_parser.target_over_line(total_games, line)`` — 1 se Over
(game totali giocati nel match > linea), 0 se Under — applicato al
``target_total_games`` prodotto da ``score_parser.build_score_targets_dataframe``
(Fase 0), agganciato al dataset v3 esistente (Elo/rank/forma/H2H + quote
match-winner) via merge su ``match_id``. Righe scartate se: punteggio non
attendibile (ritiro/anomalia, target None) OPPURE quote O/U assenti per la
linea scelta (mercato presente solo nel 26.75% delle fixture con odds, vedi
docstring di modulo in ``over_under_games_odds_builder.py``).

Feature: stesso set v3 (Elo/rank/forma/H2H + odds match-winner aggregate) +
le nuove feature quote O/U games (``OVER_UNDER_ODDS_FEATURE_COLUMNS``).

Benchmark inclusi (oltre a logistic_regression/random_forest, stessi
iperparametri ufficiali di ``walk_forward._estimators``):

- ``coin_flip``: 0.5 costante (pavimento).
- ``market_favorite`` / ``market_no_vig``: quote REALI del mercato O/U games
  per la linea scelta (non un proxy come nel 1 set winner).

Script di prima validazione: NON tocca ``train_baseline.py``, ``model_registry.json``
ne' il modello pubblico. Report dedicato standalone:
``data/reports/over_under_games_walk_forward_results.json``.
``build_over_under_games_dataframe``/``evaluate_fold_models_over_under_games``
sono riusate anche dal motore walk-forward ufficiale (persistito su DB, vedi
``walk_forward_markets.py``) — questo script CLI resta comunque disponibile
invariato per validazioni ad-hoc.

Uso (da repo root, richiede DB per il merge dei target/quote)::

    python -m backend.src.app.ml.training.train_over_under_games
    python -m backend.src.app.ml.training.train_over_under_games --quick
    python -m backend.src.app.ml.training.train_over_under_games --line 21.5
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

from backend.src.app.ml.datasets.over_under_games_odds_builder import (
    DEFAULT_LINE,
    OVER_UNDER_ODDS_FEATURE_COLUMNS,
    build_over_under_odds_dataframe,
)
from backend.src.app.ml.datasets.score_parser import (
    attach_score_targets_to_dataset,
    build_score_targets_dataframe,
    target_over_line,
)
from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR, select_training_dataset_path
from backend.src.app.ml.training.train_baseline import build_preprocessor, selected_feature_columns
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
    _mean_metrics,
    detect_leakage_flags,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

OVER_UNDER_TARGET_COLUMN = "target_over_under_games"
OVER_UNDER_MODEL_VERSION_LABEL = "over_under_games_v1"
OVER_UNDER_MODEL_NAMES = MODEL_NAMES  # ("logistic_regression", "random_forest")
OVER_UNDER_BENCHMARK_NAMES = ("coin_flip", "market_favorite", "market_no_vig")
RESULTS_FILENAME = "over_under_games_walk_forward_results.json"
# Report separato per la validazione limitata al periodo "maturo" (vedi
# ``min_date`` in ``run_over_under_games_walk_forward``): il mercato O/U games
# risulta avere copertura quasi nulla prima di fine 2024 (confermato
# empiricamente sul run 2026-08-13: train_rows=1 fino al fold con
# test_start=2024-09-26, poi salto a migliaia di righe dal 2024-12-25 in poi).
# Usare tutto lo storico 2021-2024 come train "vuoto" spreca fold senza
# aggiungere segnale: la Fase mature limita il dataframe a partire da questa
# soglia per ottenere piu' fold utili sullo stesso periodo con dati reali.
MATURE_RESULTS_FILENAME = "over_under_games_walk_forward_mature_results.json"

QUICK_CONFIG_OVERRIDES: dict[str, Any] = {
    "initial_train_days": 60,
    "test_days": 30,
    "step_days": 30,
    "min_train_rows": 20,
    "min_test_rows": 10,
}


def _coin_flip_probabilities(test: pd.DataFrame) -> pd.Series:
    return pd.Series(0.5, index=test.index, dtype=float)


def _market_favorite_over_under_probabilities(test: pd.DataFrame) -> pd.Series:
    over_odds = pd.to_numeric(test.get("avg_over_odds"), errors="coerce")
    under_odds = pd.to_numeric(test.get("avg_under_odds"), errors="coerce")
    probabilities = pd.Series(index=test.index, dtype=float)
    favorite_over = (over_odds < under_odds) & over_odds.notna() & under_odds.notna()
    favorite_under = (under_odds < over_odds) & over_odds.notna() & under_odds.notna()
    tie = (over_odds == under_odds) & over_odds.notna()
    probabilities.loc[favorite_over] = 1.0
    probabilities.loc[favorite_under] = 0.0
    probabilities.loc[tie] = 0.5
    return probabilities


def _market_no_vig_over_under_probabilities(test: pd.DataFrame) -> pd.Series:
    over_odds = pd.to_numeric(test.get("avg_over_odds"), errors="coerce")
    under_odds = pd.to_numeric(test.get("avg_under_odds"), errors="coerce")
    denom = (1.0 / over_odds) + (1.0 / under_odds)
    probs = (1.0 / over_odds) / denom
    return probs.where((over_odds > 1.0) & (under_odds > 1.0) & denom.notna() & (denom > 0.0))


def _over_under_benchmark_probabilities(test: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "coin_flip": _coin_flip_probabilities(test),
        "market_favorite": _market_favorite_over_under_probabilities(test),
        "market_no_vig": _market_no_vig_over_under_probabilities(test),
    }


def build_over_under_games_dataframe(
    db: Session,
    *,
    line: float = DEFAULT_LINE,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    dataset_version: str = "v3",
) -> tuple[pd.DataFrame, Path]:
    """Dataset v3 (Elo/rank/forma/H2H + quote match-winner) + colonna target
    Over/Under games (linea ``line``) + feature quote O/U games, tutte
    agganciate via merge su ``match_id``/``match_date``."""
    dataset_path = select_training_dataset_path(processed_dir, version=dataset_version)  # type: ignore[arg-type]
    raw = pd.read_csv(dataset_path, low_memory=False)
    raw["match_id"] = pd.to_numeric(raw["match_id"], errors="coerce").astype("int64")
    raw["match_date"] = pd.to_datetime(raw["match_date"], errors="coerce").dt.date.astype("string")

    score_targets = build_score_targets_dataframe(db)
    score_targets["match_id"] = pd.to_numeric(score_targets["match_id"], errors="coerce").astype("int64")
    merged = attach_score_targets_to_dataset(raw, score_targets)

    odds_ou = build_over_under_odds_dataframe(db, line=line)
    if not odds_ou.empty:
        odds_ou["match_id"] = pd.to_numeric(odds_ou["match_id"], errors="coerce").astype("int64")
    merged = merged.merge(odds_ou, on=["match_id", "match_date"], how="left", validate="one_to_one")

    total_games = pd.to_numeric(merged["target_total_games"], errors="coerce")
    merged[OVER_UNDER_TARGET_COLUMN] = total_games.apply(
        lambda value: target_over_line(value, line) if pd.notna(value) else None
    )
    return merged, dataset_path


def _classification_and_roi_metrics(
    y_true: pd.Series,
    probabilities: pd.Series | None,
    test: pd.DataFrame,
) -> dict[str, Any] | None:
    """Metriche di classificazione + ROI/value-bet reali (quote O/U games
    disponibili per questo mercato, a differenza del 1 set winner). ``None``
    se non calcolabile (nessuna riga utile o classe singola)."""
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

    if "avg_over_odds" in test.columns and "avg_under_odds" in test.columns:
        over_odds = pd.to_numeric(test["avg_over_odds"], errors="coerce").loc[mask]
        under_odds = pd.to_numeric(test["avg_under_odds"], errors="coerce").loc[mask]
        metrics["value_bet"] = _compute_official_metrics(y, probs, over_odds, under_odds)
    else:
        metrics["value_bet"] = None
    return metrics


def evaluate_fold_models_over_under_games(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    dataset_path: str,
    fold: WalkForwardFoldSpec,
    config: WalkForwardConfig,
    model_names: tuple[str, ...] = OVER_UNDER_MODEL_NAMES,
    benchmark_names: tuple[str, ...] = OVER_UNDER_BENCHMARK_NAMES,
    estimators_factory=_estimators,
    feature_columns_override: list[str] | None = None,
) -> list[WalkForwardFoldOutcome]:
    from sklearn.pipeline import Pipeline

    feature_columns = (
        feature_columns_override
        if feature_columns_override is not None
        else selected_feature_columns(train, model_version="v3") + [
            column for column in OVER_UNDER_ODDS_FEATURE_COLUMNS if column in train.columns
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
                model_version=OVER_UNDER_MODEL_VERSION_LABEL,
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

    y_train = train[OVER_UNDER_TARGET_COLUMN].astype(int)
    y_test = test[OVER_UNDER_TARGET_COLUMN].astype(int)
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
                    fold=fold, model_version=OVER_UNDER_MODEL_VERSION_LABEL, model_name=model_name,
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
                        fold=fold, model_version=OVER_UNDER_MODEL_VERSION_LABEL, model_name=model_name,
                        dataset_path=dataset_path, feature_set=feature_columns,
                        status="skipped_single_class", train_rows=len(train), test_rows=len(test),
                        skip_reason="Metriche non calcolabili sul test.",
                        leakage_flags=leakage_flags, coverage=coverage,
                    )
                )
                continue
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=OVER_UNDER_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="completed",
                    train_rows=len(train), test_rows=len(test), metrics=metrics,
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
        except Exception as exc:  # noqa: BLE001 — fold isolation
            logger.exception(
                "Over-under-games fold=%s model=%s failed: %s", fold.fold_index, model_name, exc,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=OVER_UNDER_MODEL_VERSION_LABEL, model_name=model_name,
                    dataset_path=dataset_path, feature_set=feature_columns, status="error",
                    train_rows=len(train), test_rows=len(test), skip_reason=str(exc),
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )

    benchmark_probabilities = _over_under_benchmark_probabilities(test)
    for benchmark_name in benchmark_names:
        metrics = _classification_and_roi_metrics(y_test, benchmark_probabilities.get(benchmark_name), test)
        if metrics is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold, model_version=OVER_UNDER_MODEL_VERSION_LABEL, model_name=benchmark_name,
                    dataset_path=dataset_path, feature_set=feature_columns,
                    status="skipped_insufficient_data", train_rows=len(train), test_rows=len(test),
                    skip_reason="Benchmark non calcolabile (feature mancanti o classe singola).",
                    leakage_flags=leakage_flags, coverage=coverage,
                )
            )
            continue
        outcomes.append(
            WalkForwardFoldOutcome(
                fold=fold, model_version=OVER_UNDER_MODEL_VERSION_LABEL, model_name=benchmark_name,
                dataset_path=dataset_path, feature_set=feature_columns, status="completed",
                train_rows=len(train), test_rows=len(test), metrics=metrics,
                leakage_flags=leakage_flags, coverage=coverage,
            )
        )

    return outcomes


def run_over_under_games_walk_forward(
    db: Session,
    *,
    line: float = DEFAULT_LINE,
    config: WalkForwardConfig | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    min_date: str | None = None,
    results_filename: str | None = None,
) -> dict[str, Any]:
    resolved_config = config or WalkForwardConfig()
    resolved_config.validate()

    merged, dataset_path = build_over_under_games_dataframe(db, line=line, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=OVER_UNDER_TARGET_COLUMN, model_version="v3",
    )
    # Righe senza quote O/U per questa linea: il modello ML le userebbe comunque
    # (feature mancanti imputate), ma i benchmark di mercato diventerebbero NaN
    # e falserebbero il confronto. Si allena/valuta solo sul campione con quote
    # reali per questa linea, cosi' il confronto modello-vs-mercato resta equo.
    if "avg_over_odds" in dataframe.columns and "avg_under_odds" in dataframe.columns:
        has_odds = (
            pd.to_numeric(dataframe["avg_over_odds"], errors="coerce").notna()
            & pd.to_numeric(dataframe["avg_under_odds"], errors="coerce").notna()
        )
        dataframe = dataframe.loc[has_odds].reset_index(drop=True)

    mature_mode = min_date is not None
    if mature_mode:
        cutoff = pd.to_datetime(min_date).date()
        dataframe = dataframe.loc[pd.to_datetime(dataframe["match_date"]).dt.date >= cutoff].reset_index(
            drop=True
        )

    folds = generate_walk_forward_folds(dataframe, resolved_config)
    feature_set = selected_feature_columns(dataframe, model_version="v3") + [
        column for column in OVER_UNDER_ODDS_FEATURE_COLUMNS if column in dataframe.columns
    ]
    outcomes: list[WalkForwardFoldOutcome] = []
    leakage_flags = list(_fold_test_overlaps(folds))
    if not folds:
        leakage_flags.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            evaluate_fold_models_over_under_games(
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
    aggregate_roi = _mean_value_bet_metrics(completed)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "over_under_games_mature_validation" if mature_mode else "over_under_games_first_validation",
        "target_column": OVER_UNDER_TARGET_COLUMN,
        "over_under_line": line,
        "mature_mode": mature_mode,
        "min_date": min_date,
        "base_feature_set_version": "v3",
        "model_names": list(OVER_UNDER_MODEL_NAMES),
        "benchmark_names": list(OVER_UNDER_BENCHMARK_NAMES),
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
        "aggregate_value_bet_metrics": aggregate_roi,
        "folds": [outcome.to_dict() for outcome in outcomes],
        "notes": [
            "Script di prima validazione: NON tocca train_baseline.py, walk_forward.py, "
            "model_registry.json ne' il modello pubblico. Report dedicato separato.",
            f"Mercato 'Over/Under by Games in Match', linea di riferimento {line} (la piu' "
            "diffusa sul DB di produzione, vedi over_under_games_odds_builder.py). Righe "
            "senza quote per questa linea escluse dalla valutazione (confronto equo "
            "modello-vs-mercato).",
            "A differenza del 1 set winner, qui esistono quote di mercato REALI per il "
            "target: 'market_favorite'/'market_no_vig' non sono proxy, e le metriche "
            "'value_bet' (ROI/yield/max_drawdown) sono calcolate sulle quote O/U reali.",
            f"Feature-set: v3 (Elo/rank/forma/H2H + quote match-winner) + "
            f"{len(OVER_UNDER_ODDS_FEATURE_COLUMNS)} colonne quote O/U games aggregate. "
            "Righe filtrate a odds match-winner valide (filtro v3 ufficiale), punteggio "
            "set-by-set attendibile (score_parser, Fase 0) e quote O/U disponibili per "
            "questa linea.",
            (
                "Copertura reale del mercato 'Over/Under by Games in Match' fortemente "
                "concentrata negli ultimi mesi: run 2026-08-13 su tutto lo storico mostra "
                "train_rows=1 fino al fold con test_start=2024-09-26, poi salto a migliaia "
                "di righe dal 2024-12-25 in poi. Usare min_date/--min-date per validare solo "
                "sul periodo maturo (piu' fold utili, report separato "
                f"'{MATURE_RESULTS_FILENAME}')."
                if not mature_mode
                else f"Validazione limitata al periodo maturo (match_date >= {min_date})."
            ),
        ],
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    resolved_filename = results_filename or (MATURE_RESULTS_FILENAME if mature_mode else RESULTS_FILENAME)
    results_path = reports_path / resolved_filename
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def _mean_value_bet_metrics(completed: list[WalkForwardFoldOutcome]) -> dict[str, Any]:
    keys = ("roi", "yield", "max_drawdown", "bets_settled", "total_profit", "avg_odds")
    by_name: dict[str, list[dict[str, Any]]] = {}
    for outcome in completed:
        payload = (outcome.metrics or {}).get("value_bet")
        if isinstance(payload, dict):
            by_name.setdefault(outcome.model_name, []).append(payload)

    aggregate: dict[str, Any] = {}
    for name, entries in by_name.items():
        row: dict[str, Any] = {"folds_completed": len(entries)}
        for key in keys:
            values = [item.get(key) for item in entries if item.get(key) is not None]
            if not values:
                row[key] = {"mean": None, "std": None, "n": 0}
                continue
            series = pd.Series(values, dtype=float)
            row[key] = {
                "mean": round(float(series.mean()), 6),
                "std": round(float(series.std(ddof=0)), 6) if len(values) > 1 else 0.0,
                "n": len(values),
            }
        aggregate[name] = row
    return aggregate


def format_over_under_games_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Prima validazione — Over/Under Games (linea {report['over_under_line']}, walk-forward)",
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
        description="Prima validazione walk-forward del mercato Over/Under Games."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument(
        "--line", type=float, default=DEFAULT_LINE, help="Linea Over/Under di riferimento (default 20.5).",
    )
    parser.add_argument(
        "--quick", action="store_true", help="Finestre piu' corte (smoke test).",
    )
    parser.add_argument(
        "--min-date",
        default=None,
        help=(
            "Limita la validazione a match_date >= questa data (ISO, es. 2024-12-01): "
            "usare per la Fase 'matura' quando il mercato ha copertura reale solo "
            "recente (report salvato separatamente, vedi MATURE_RESULTS_FILENAME)."
        ),
    )
    parser.add_argument("--initial-train-days", type=int, default=None)
    parser.add_argument("--test-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--min-train-rows", type=int, default=None)
    parser.add_argument("--min-test-rows", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config_kwargs: dict[str, Any] = {}
    if args.quick:
        config_kwargs.update(QUICK_CONFIG_OVERRIDES)
    for key in ("initial_train_days", "test_days", "step_days", "min_train_rows", "min_test_rows"):
        value = getattr(args, key)
        if value is not None:
            config_kwargs[key] = value
    config = WalkForwardConfig(**config_kwargs)

    with SessionLocal() as db:
        report = run_over_under_games_walk_forward(
            db, line=args.line, config=config, processed_dir=args.processed_dir,
            reports_dir=args.reports_dir, min_date=args.min_date,
        )
    print(format_over_under_games_summary(report))


if __name__ == "__main__":
    main()







