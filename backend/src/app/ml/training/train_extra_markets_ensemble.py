"""Ensemble esplorativo (grid search → stacking → voting) per mercati extra.

Copre ``first_set_winner`` (feature v3 + quote 1° set) e ``over_under_games``
(feature v3 + quote O/U games). Stesso playbook di match-winner v4, ma:

1. Grid search multi-algoritmo (LR / RF / HGB / XGB / LightGBM) con
   ``TimeSeriesSplit`` sul 80% cronologico iniziale.
2. Selezione automatica dei top-3 algoritmi per ROC AUC holdout.
3. **Stacking** (meta-LR) poi **soft voting** sugli stessi base tunati.
4. Confronto holdout + walk-forward quick vs baseline di produzione attuale
   (1° set: ``logistic_regression``; O/U: ``random_forest``).

NON tocca produzione / ``extra_markets_predictor`` / registry. Report in
``data/reports/<market>_ensemble_experiment_results.json``.

Uso (da repo root, richiede DB; in Docker models montato :ro →
``--models-dir`` su reports staging)::

    python -m backend.src.app.ml.training.train_extra_markets_ensemble \\
        --market first_set_winner
    python -m backend.src.app.ml.training.train_extra_markets_ensemble \\
        --market over_under_games --min-date 2024-12-01
    python -m backend.src.app.ml.training.train_extra_markets_ensemble \\
        --market first_set_winner --quick
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.first_set_winner_odds_builder import FIRST_SET_ODDS_FEATURE_COLUMNS
from backend.src.app.ml.datasets.over_under_games_odds_builder import (
    DEFAULT_LINE,
    OVER_UNDER_ODDS_FEATURE_COLUMNS,
)
from backend.src.app.ml.model_versioning import MODELS_DIR, PROCESSED_DATA_DIR, REPORTS_DIR
from backend.src.app.ml.training.train_baseline import (
    build_preprocessor,
    selected_feature_columns,
    temporal_train_test_split,
)
from backend.src.app.ml.training.train_first_set_winner import FIRST_SET_TARGET_COLUMN
from backend.src.app.ml.training.train_first_set_winner_odds import (
    FIRST_SET_ODDS_BENCHMARK_NAMES,
    QUICK_CONFIG_OVERRIDES as FIRST_SET_QUICK_OVERRIDES,
    build_first_set_winner_odds_dataframe,
    evaluate_fold_models_first_set_odds,
    _classification_and_roi_metrics as first_set_metrics,
)
from backend.src.app.ml.training.train_over_under_games import (
    OVER_UNDER_BENCHMARK_NAMES,
    OVER_UNDER_TARGET_COLUMN,
    QUICK_CONFIG_OVERRIDES as OVER_UNDER_QUICK_OVERRIDES,
    build_over_under_games_dataframe,
    evaluate_fold_models_over_under_games,
    _classification_and_roi_metrics as over_under_metrics,
    _mean_value_bet_metrics,
)
from backend.src.app.ml.training.train_v4_search import (
    _date_max,
    _date_min,
    _json_default,
    _round,
    _top_cv_combinations,
    build_base_estimators,
    build_param_grids,
)
from backend.src.app.ml.training.walk_forward import (
    WalkForwardConfig,
    WalkForwardFoldOutcome,
    _estimators,
    _fold_test_overlaps,
    _mean_metrics,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

MarketName = Literal["first_set_winner", "over_under_games"]

DEFAULT_DEV_SIZE = 0.8
DEFAULT_CV_SPLITS = 3
DEFAULT_TOP_N_BASE = 3
OVER_UNDER_DEFAULT_MIN_DATE = "2024-12-01"

MARKET_CONFIG: dict[MarketName, dict[str, Any]] = {
    "first_set_winner": {
        "target_column": FIRST_SET_TARGET_COLUMN,
        "prod_baseline": "logistic_regression",
        "odds_feature_columns": FIRST_SET_ODDS_FEATURE_COLUMNS,
        "search_results_filename": "first_set_winner_grid_search_results.json",
        "ensemble_results_filename": "first_set_winner_ensemble_experiment_results.json",
        "models_dir_name": "first_set_winner_ensemble",
        "label": "first_set_winner_ensemble",
        "quick_overrides": FIRST_SET_QUICK_OVERRIDES,
        "benchmark_names": FIRST_SET_ODDS_BENCHMARK_NAMES,
    },
    "over_under_games": {
        "target_column": OVER_UNDER_TARGET_COLUMN,
        "prod_baseline": "random_forest",
        "odds_feature_columns": OVER_UNDER_ODDS_FEATURE_COLUMNS,
        "search_results_filename": "over_under_games_grid_search_results.json",
        "ensemble_results_filename": "over_under_games_ensemble_experiment_results.json",
        "models_dir_name": "over_under_games_ensemble",
        "label": "over_under_games_ensemble",
        "quick_overrides": OVER_UNDER_QUICK_OVERRIDES,
        "benchmark_names": OVER_UNDER_BENCHMARK_NAMES,
    },
}


def _market_metrics(
    market: MarketName,
    y_true: pd.Series,
    probabilities: pd.Series | np.ndarray,
    test: pd.DataFrame,
) -> dict[str, Any] | None:
    probs = pd.Series(probabilities, index=test.index, dtype=float)
    if market == "first_set_winner":
        return first_set_metrics(y_true, probs, test)
    return over_under_metrics(y_true, probs, test)


def _feature_columns(dataframe: pd.DataFrame, market: MarketName) -> list[str]:
    odds_cols = MARKET_CONFIG[market]["odds_feature_columns"]
    return selected_feature_columns(dataframe, model_version="v3") + [
        column for column in odds_cols if column in dataframe.columns
    ]


def _filter_valid_rows(dataframe: pd.DataFrame, market: MarketName) -> pd.DataFrame:
    target = MARKET_CONFIG[market]["target_column"]
    frame = dataframe.copy()
    frame[target] = pd.to_numeric(frame[target], errors="coerce")
    frame = frame.loc[frame[target].notna()].copy()
    if market == "first_set_winner":
        has_odds = (
            pd.to_numeric(frame.get("avg_first_set_player_1_odds"), errors="coerce").notna()
            & pd.to_numeric(frame.get("avg_first_set_player_2_odds"), errors="coerce").notna()
        )
    else:
        has_odds = (
            pd.to_numeric(frame.get("avg_over_odds"), errors="coerce").notna()
            & pd.to_numeric(frame.get("avg_under_odds"), errors="coerce").notna()
        )
    return frame.loc[has_odds].reset_index(drop=True)


def load_market_dataframe(
    db: Session,
    market: MarketName,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    line: float = DEFAULT_LINE,
    min_date: str | None = None,
) -> tuple[pd.DataFrame, Path, str]:
    if market == "first_set_winner":
        merged, dataset_path = build_first_set_winner_odds_dataframe(db, processed_dir=processed_dir)
        note = "first_set odds required"
    else:
        merged, dataset_path = build_over_under_games_dataframe(
            db, line=line, processed_dir=processed_dir,
        )
        note = f"over_under line={line}"
        if min_date is None:
            min_date = OVER_UNDER_DEFAULT_MIN_DATE
            note += f"; default min_date={min_date}"
    if min_date is not None:
        cutoff = pd.to_datetime(min_date).date()
        dates = pd.to_datetime(merged["match_date"], errors="coerce").dt.date
        merged = merged.loc[dates >= cutoff].reset_index(drop=True)
        note += f"; filtered match_date>={min_date}"
    filtered = _filter_valid_rows(merged, market)
    if filtered.empty:
        raise ValueError(f"Nessuna riga valida per {market} ({note}).")
    return filtered, dataset_path, note


def select_top_algorithms(
    search_algorithms: dict[str, Any],
    *,
    top_n: int = DEFAULT_TOP_N_BASE,
) -> list[str]:
    """Top-N per ROC AUC holdout; tie-break su ROI value-bet (meno negativo meglio)."""

    def _sort_key(item: tuple[str, Any]) -> tuple[float, float]:
        name, payload = item
        metrics = payload.get("test_metrics") or {}
        roc = metrics.get("roc_auc")
        value_bet = metrics.get("value_bet") or {}
        roi = value_bet.get("roi") if isinstance(value_bet, dict) else None
        # Missing ROI sorts last among equal AUC.
        roi_key = float(roi) if roi is not None else -1e9
        return (float(roc) if roc is not None else -1.0, roi_key)

    ranked = sorted(search_algorithms.items(), key=_sort_key, reverse=True)
    return [name for name, _ in ranked[:top_n]]


def build_tuned_estimator(algorithm: str, params: dict[str, Any], *, random_state: int = 42) -> Any:
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    clean = {key.removeprefix("model__"): value for key, value in params.items()}
    if algorithm == "logistic_regression":
        return LogisticRegression(**clean)
    if algorithm == "random_forest":
        return RandomForestClassifier(random_state=random_state, n_jobs=-1, **clean)
    if algorithm == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=random_state, **clean)
    if algorithm == "xgboost":
        return XGBClassifier(random_state=random_state, n_jobs=-1, eval_metric="logloss", **clean)
    if algorithm == "lightgbm":
        return LGBMClassifier(random_state=random_state, n_jobs=-1, verbosity=-1, **clean)
    raise ValueError(f"Algoritmo non supportato: {algorithm}")


@dataclass(frozen=True)
class SearchResult:
    algorithm: str
    best_params: dict[str, Any]
    cv_best_roc_auc: float | None
    cv_best_neg_log_loss: float | None
    cv_results_top: list[dict[str, Any]]
    test_metrics: dict[str, Any]
    fit_seconds: float
    model_path: str


def run_grid_search(
    dataframe: pd.DataFrame,
    market: MarketName,
    *,
    dataset_path: Path,
    reports_dir: Path,
    models_dir: Path,
    dev_size: float = DEFAULT_DEV_SIZE,
    cv_splits: int = DEFAULT_CV_SPLITS,
    quick: bool = False,
    n_jobs: int = 1,
) -> dict[str, Any]:
    from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
    from sklearn.pipeline import Pipeline

    cfg = MARKET_CONFIG[market]
    target = cfg["target_column"]
    split = temporal_train_test_split(
        dataframe,
        target_column=target,
        test_size=round(1 - dev_size, 6),
    )
    feature_columns = _feature_columns(split.train, market)
    if not feature_columns:
        raise ValueError(f"Nessuna feature disponibile per {market}.")

    x_dev = split.train[feature_columns]
    y_dev = split.train[target].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[target].astype(int)

    models_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    estimators = build_base_estimators()
    param_grids = build_param_grids(quick=quick)
    effective_cv_splits = 2 if quick else cv_splits
    time_series_cv = TimeSeriesSplit(n_splits=effective_cv_splits)

    results: dict[str, SearchResult] = {}
    for name, estimator in estimators.items():
        logger.info("[%s] GridSearchCV %s (quick=%s)", market, name, quick)
        pipeline = Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(split.train, feature_columns)),
                ("model", estimator),
            ]
        )
        grid = GridSearchCV(
            pipeline,
            param_grid=param_grids[name],
            cv=time_series_cv,
            scoring={"roc_auc": "roc_auc", "neg_log_loss": "neg_log_loss"},
            refit="roc_auc",
            n_jobs=n_jobs,
            verbose=1,
            error_score="raise",
        )
        start = time.perf_counter()
        grid.fit(x_dev, y_dev)
        fit_seconds = round(time.perf_counter() - start, 2)

        probabilities = grid.predict_proba(x_test)[:, 1]
        test_metrics = _market_metrics(market, y_test, probabilities, split.test) or {}

        model_path = models_dir / f"search_{name}.pkl"
        with model_path.open("wb") as handle:
            pickle.dump(
                {
                    "pipeline": grid.best_estimator_,
                    "feature_columns": feature_columns,
                    "market": market,
                    "algorithm": name,
                    "best_params": grid.best_params_,
                },
                handle,
            )

        best_index = grid.best_index_
        results[name] = SearchResult(
            algorithm=name,
            best_params=grid.best_params_,
            cv_best_roc_auc=_round(grid.best_score_),
            cv_best_neg_log_loss=_round(grid.cv_results_["mean_test_neg_log_loss"][best_index]),
            cv_results_top=_top_cv_combinations(grid.cv_results_, top_n=5),
            test_metrics=test_metrics,
            fit_seconds=fit_seconds,
            model_path=str(model_path),
        )
        logger.info(
            "[%s] %s done in %.1fs — CV auc=%s test auc=%s",
            market,
            name,
            fit_seconds,
            results[name].cv_best_roc_auc,
            test_metrics.get("roc_auc"),
        )

    algorithms_payload = {
        name: {
            "best_params": item.best_params,
            "cv_best_roc_auc": item.cv_best_roc_auc,
            "cv_best_neg_log_loss": item.cv_best_neg_log_loss,
            "cv_top_combinations": item.cv_results_top,
            "test_metrics": item.test_metrics,
            "fit_seconds": item.fit_seconds,
            "model_path": item.model_path,
        }
        for name, item in results.items()
    }
    top_algorithms = select_top_algorithms(algorithms_payload)
    winner = top_algorithms[0] if top_algorithms else None

    # Baseline produzione sullo stesso holdout (iperparametri ufficiali walk_forward).
    prod_name = cfg["prod_baseline"]
    prod_pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(split.train, feature_columns)),
            ("model", _estimators(42)[prod_name]),
        ]
    )
    prod_pipeline.fit(x_dev, y_dev)
    prod_probs = prod_pipeline.predict_proba(x_test)[:, 1]
    production_baseline_metrics = _market_metrics(market, y_test, prod_probs, split.test)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "grid_search",
        "market": market,
        "dataset_path": str(dataset_path),
        "rows_total": int(len(dataframe)),
        "date_min": _date_min(dataframe, "match_date"),
        "date_max": _date_max(dataframe, "match_date"),
        "split": {
            "strategy": "temporal_dev_test",
            "dev_size": dev_size,
            "dev_rows": int(len(split.train)),
            "test_rows": int(len(split.test)),
            "dev_date_min": split.train_start,
            "dev_date_max": split.train_end,
            "test_date_min": split.test_start,
            "test_date_max": split.test_end,
            "inner_cv": f"TimeSeriesSplit(n_splits={effective_cv_splits})",
        },
        "features_used": feature_columns,
        "features_count": len(feature_columns),
        "quick_mode": quick,
        "algorithms": algorithms_payload,
        "top_algorithms_for_ensemble": top_algorithms,
        "winner": winner,
        "winner_test_roc_auc": (
            algorithms_payload[winner]["test_metrics"].get("roc_auc") if winner else None
        ),
        "production_baseline": {
            "model_name": prod_name,
            "source": "walk_forward._estimators (untuned production defaults)",
            "test_metrics": production_baseline_metrics,
        },
        "notes": [
            "Esplorativo: NON promuove modelli in produzione.",
            f"Top-{len(top_algorithms)} selezionati per stacking/voting: {top_algorithms}.",
        ],
    }
    results_path = reports_dir / cfg["search_results_filename"]
    with results_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False, default=_json_default)
    report["results_path"] = str(results_path)
    return report


def run_stacking_then_voting(
    dataframe: pd.DataFrame,
    market: MarketName,
    search_report: dict[str, Any],
    *,
    dataset_path: Path,
    reports_dir: Path,
    models_dir: Path,
    dev_size: float = DEFAULT_DEV_SIZE,
    cv_splits: int = DEFAULT_CV_SPLITS,
    quick: bool = False,
    n_jobs: int = 1,
) -> dict[str, Any]:
    from sklearn.ensemble import StackingClassifier, VotingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import KFold
    from sklearn.pipeline import Pipeline

    cfg = MARKET_CONFIG[market]
    target = cfg["target_column"]
    base_names: list[str] = list(search_report["top_algorithms_for_ensemble"])
    if len(base_names) < 2:
        raise ValueError("Servono almeno 2 algoritmi per stacking/voting.")

    split = temporal_train_test_split(
        dataframe,
        target_column=target,
        test_size=round(1 - dev_size, 6),
    )
    feature_columns = list(search_report["features_used"])
    x_dev = split.train[feature_columns]
    y_dev = split.train[target].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[target].astype(int)

    provenance: dict[str, Any] = {}
    base_estimators: list[tuple[str, Any]] = []
    for name in base_names:
        params = search_report["algorithms"][name]["best_params"]
        base_estimators.append((name, build_tuned_estimator(name, params)))
        provenance[name] = {
            "params_used": {k.removeprefix("model__"): v for k, v in params.items()},
            "search_test_roc_auc": search_report["algorithms"][name]["test_metrics"].get("roc_auc"),
        }

    effective_cv_splits = 2 if quick else cv_splits
    stacking_inner_cv = KFold(n_splits=effective_cv_splits, shuffle=False)

    # Ordine richiesto: prima stacking, poi voting. Preprocessor clonato per pipeline.
    ensemble_definitions: list[tuple[str, Any]] = [
        (
            "stacking",
            Pipeline(
                steps=[
                    ("preprocessor", build_preprocessor(split.train, feature_columns)),
                    (
                        "ensemble",
                        StackingClassifier(
                            estimators=list(base_estimators),
                            final_estimator=LogisticRegression(max_iter=2000),
                            cv=stacking_inner_cv,
                            stack_method="predict_proba",
                            n_jobs=n_jobs,
                            passthrough=False,
                        ),
                    ),
                ]
            ),
        ),
        (
            "voting_soft",
            Pipeline(
                steps=[
                    ("preprocessor", build_preprocessor(split.train, feature_columns)),
                    (
                        "ensemble",
                        VotingClassifier(
                            estimators=[
                                (name, build_tuned_estimator(name, search_report["algorithms"][name]["best_params"]))
                                for name in base_names
                            ],
                            voting="soft",
                            n_jobs=n_jobs,
                        ),
                    ),
                ]
            ),
        ),
    ]

    ensembles: dict[str, Any] = {}
    for name, pipeline in ensemble_definitions:
        logger.info("[%s] Fit ensemble %s (base=%s)", market, name, base_names)
        start = time.perf_counter()
        pipeline.fit(x_dev, y_dev)
        fit_seconds = round(time.perf_counter() - start, 2)
        probabilities = pipeline.predict_proba(x_test)[:, 1]
        test_metrics = _market_metrics(market, y_test, probabilities, split.test) or {}

        model_path = models_dir / f"{name}.pkl"
        with model_path.open("wb") as handle:
            pickle.dump(
                {
                    "pipeline": pipeline,
                    "feature_columns": feature_columns,
                    "market": market,
                    "ensemble_name": name,
                    "base_algorithms": base_names,
                },
                handle,
            )

        extra: dict[str, Any] = {"base_algorithms": base_names}
        if name == "stacking":
            meta = pipeline.named_steps["ensemble"].final_estimator_
            extra["meta_learner_coefficients"] = {
                algo: _round(coef)
                for algo, coef in zip(base_names, meta.coef_[0].tolist())
            }
            extra["meta_learner_intercept"] = _round(meta.intercept_[0])

        ensembles[name] = {
            "test_metrics": test_metrics,
            "fit_seconds": fit_seconds,
            "model_path": str(model_path),
            **extra,
        }
        logger.info(
            "[%s] %s done in %.1fs — test auc=%s",
            market,
            name,
            fit_seconds,
            test_metrics.get("roc_auc"),
        )

    candidates: dict[str, float] = {
        name: float((payload["test_metrics"] or {}).get("roc_auc") or -1.0)
        for name, payload in ensembles.items()
    }
    for algo_name, algo_data in search_report["algorithms"].items():
        roc = (algo_data.get("test_metrics") or {}).get("roc_auc")
        if roc is not None:
            candidates[f"single:{algo_name}"] = float(roc)
    prod = search_report.get("production_baseline") or {}
    prod_roc = ((prod.get("test_metrics") or {}).get("roc_auc"))
    if prod_roc is not None:
        candidates[f"production:{prod.get('model_name')}"] = float(prod_roc)

    winner = max(candidates, key=lambda key: candidates[key])

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "stacking_then_voting",
        "market": market,
        "dataset_path": str(dataset_path),
        "rows_total": int(len(dataframe)),
        "split": search_report["split"],
        "features_used": feature_columns,
        "quick_mode": quick,
        "base_estimators": provenance,
        "ensembles": ensembles,
        "production_baseline": search_report.get("production_baseline"),
        "comparison_candidates_roc_auc": {k: _round(v) for k, v in candidates.items()},
        "winner_holdout": winner,
        "winner_holdout_roc_auc": _round(candidates[winner]),
        "beats_production_holdout": bool(
            prod_roc is not None
            and max(
                (ensembles["stacking"]["test_metrics"] or {}).get("roc_auc") or -1.0,
                (ensembles["voting_soft"]["test_metrics"] or {}).get("roc_auc") or -1.0,
            )
            > float(prod_roc)
        ),
        "notes": [
            "Esplorativo: stacking valutato prima, poi soft voting.",
            "KFold(shuffle=False) per OOF stacking (TimeSeriesSplit non partiziona).",
            "NON promuove in produzione: serve conferma walk-forward + decisione esplicita.",
        ],
    }
    return report


def _ensemble_estimators_factory(
    base_names: list[str],
    params_by_algo: dict[str, dict[str, Any]],
    *,
    production_baseline: str,
) -> Callable[[int], dict[str, Any]]:
    def factory(random_state: int) -> dict[str, Any]:
        from sklearn.ensemble import StackingClassifier, VotingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import KFold

        bases = [
            (name, build_tuned_estimator(name, params_by_algo[name], random_state=random_state))
            for name in base_names
        ]
        stacking_cv = KFold(n_splits=2, shuffle=False)
        defaults = dict(_estimators(random_state))
        # Conserva l'iperparametrizzazione di produzione per il baseline WF,
        # anche se lo stesso algoritmo e' tra i top tunati.
        production_estimator = defaults[production_baseline]
        estimators = dict(defaults)
        for name, estimator in bases:
            estimators[name] = estimator
        estimators[production_baseline] = production_estimator
        estimators["stacking"] = StackingClassifier(
            estimators=list(bases),
            final_estimator=LogisticRegression(max_iter=2000),
            cv=stacking_cv,
            stack_method="predict_proba",
            n_jobs=1,
            passthrough=False,
        )
        estimators["voting_soft"] = VotingClassifier(
            estimators=list(bases),
            voting="soft",
            n_jobs=1,
        )
        return estimators

    return factory


def run_walk_forward_comparison(
    db: Session,
    dataframe: pd.DataFrame,
    market: MarketName,
    search_report: dict[str, Any],
    *,
    dataset_path: Path,
    quick: bool = True,
) -> dict[str, Any]:
    """Walk-forward quick: baseline prod + stacking + voting (+ top single)."""
    cfg = MARKET_CONFIG[market]
    target = cfg["target_column"]
    base_names: list[str] = list(search_report["top_algorithms_for_ensemble"])
    params_by_algo = {
        name: search_report["algorithms"][name]["best_params"] for name in base_names
    }
    model_names = (
        cfg["prod_baseline"],
        "stacking",
        "voting_soft",
        base_names[0],
    )
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered_models: list[str] = []
    for name in model_names:
        if name not in seen:
            ordered_models.append(name)
            seen.add(name)

    prepared = prepare_temporal_dataframe(
        dataframe, target_column=target, model_version="v3",
    )
    config_kwargs = dict(cfg["quick_overrides"]) if quick else {}
    config = WalkForwardConfig(**config_kwargs) if config_kwargs else WalkForwardConfig()
    folds = generate_walk_forward_folds(prepared, config)
    factory = _ensemble_estimators_factory(
        base_names,
        params_by_algo,
        production_baseline=cfg["prod_baseline"],
    )

    evaluate = (
        evaluate_fold_models_first_set_odds
        if market == "first_set_winner"
        else evaluate_fold_models_over_under_games
    )
    outcomes: list[WalkForwardFoldOutcome] = []
    for fold in folds:
        train, test = slice_fold_frames(prepared, fold)
        outcomes.extend(
            evaluate(
                train,
                test,
                dataset_path=str(dataset_path),
                fold=fold,
                config=config,
                model_names=tuple(ordered_models),
                benchmark_names=tuple(cfg["benchmark_names"]),
                estimators_factory=factory,
            )
        )

    completed = [item for item in outcomes if item.status == "completed"]
    aggregate_metrics = _mean_metrics(completed)
    aggregate_value_bet = _mean_value_bet_metrics(completed)

    def _auc(name: str) -> float:
        return float(((aggregate_metrics.get(name) or {}).get("roc_auc") or {}).get("mean") or -1.0)

    prod = cfg["prod_baseline"]
    # Ranking solo sui modelli ML sotto test (non sui benchmark di mercato).
    ranking = sorted(list(ordered_models), key=_auc, reverse=True)
    ranking_all = sorted(
        [name for name in aggregate_metrics.keys()],
        key=_auc,
        reverse=True,
    )
    return {
        "mode": "quick" if quick else "full",
        "folds_planned": len(folds),
        "fold_overlap_warnings": list(_fold_test_overlaps(folds)),
        "folds_completed_per_model": {
            name: int((aggregate_metrics.get(name) or {}).get("folds_completed") or 0)
            for name in ranking_all
        },
        "model_names": ordered_models,
        "base_algorithms": base_names,
        "aggregate_metrics": aggregate_metrics,
        "aggregate_value_bet_metrics": aggregate_value_bet,
        "ranking_by_roc_auc": ranking,
        "ranking_including_benchmarks": ranking_all,
        "best_model": ranking[0] if ranking else None,
        "beats_production": bool(
            ranking
            and ranking[0] in {"stacking", "voting_soft"}
            and _auc(ranking[0]) > _auc(prod)
        ),
        "production_baseline": prod,
        "production_roc_auc_mean": _round(_auc(prod)),
    }


def run_experiment(
    db: Session,
    market: MarketName,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    models_dir: str | Path | None = None,
    line: float = DEFAULT_LINE,
    min_date: str | None = None,
    quick: bool = False,
    skip_walk_forward: bool = False,
    n_jobs: int = 1,
) -> dict[str, Any]:
    cfg = MARKET_CONFIG[market]
    reports_path = Path(reports_dir)
    resolved_models_dir = (
        Path(models_dir)
        if models_dir is not None
        else Path(MODELS_DIR) / cfg["models_dir_name"]
    )
    resolved_models_dir.mkdir(parents=True, exist_ok=True)

    dataframe, dataset_path, prep_note = load_market_dataframe(
        db,
        market,
        processed_dir=processed_dir,
        line=line,
        min_date=min_date,
    )
    logger.info("[%s] Dataset pronto: %s righe (%s)", market, len(dataframe), prep_note)

    search_report = run_grid_search(
        dataframe,
        market,
        dataset_path=dataset_path,
        reports_dir=reports_path,
        models_dir=resolved_models_dir,
        quick=quick,
        n_jobs=n_jobs,
    )
    ensemble_partial = run_stacking_then_voting(
        dataframe,
        market,
        search_report,
        dataset_path=dataset_path,
        reports_dir=reports_path,
        models_dir=resolved_models_dir,
        quick=quick,
        n_jobs=n_jobs,
    )

    walk_forward: dict[str, Any] | None = None
    if not skip_walk_forward:
        walk_forward = run_walk_forward_comparison(
            db,
            dataframe,
            market,
            search_report,
            dataset_path=dataset_path,
            quick=True,
        )

    recommendation = _build_recommendation(
        market, search_report, ensemble_partial, walk_forward,
    )

    final_report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "extra_markets_ensemble_experiment",
        "market": market,
        "preparation_note": prep_note,
        "dataset_path": str(dataset_path),
        "rows_total": int(len(dataframe)),
        "date_min": search_report["date_min"],
        "date_max": search_report["date_max"],
        "quick_mode": quick,
        "grid_search": {
            "results_path": search_report.get("results_path"),
            "algorithms": {
                name: {
                    "cv_best_roc_auc": payload["cv_best_roc_auc"],
                    "test_roc_auc": (payload.get("test_metrics") or {}).get("roc_auc"),
                    "test_roi": ((payload.get("test_metrics") or {}).get("value_bet") or {}).get("roi")
                    if isinstance((payload.get("test_metrics") or {}).get("value_bet"), dict)
                    else None,
                    "best_params": payload["best_params"],
                    "fit_seconds": payload["fit_seconds"],
                }
                for name, payload in search_report["algorithms"].items()
            },
            "top_algorithms_for_ensemble": search_report["top_algorithms_for_ensemble"],
            "winner": search_report["winner"],
            "production_baseline": search_report["production_baseline"],
        },
        "ensembles": ensemble_partial["ensembles"],
        "holdout_comparison": {
            "candidates_roc_auc": ensemble_partial["comparison_candidates_roc_auc"],
            "winner": ensemble_partial["winner_holdout"],
            "winner_roc_auc": ensemble_partial["winner_holdout_roc_auc"],
            "beats_production": ensemble_partial["beats_production_holdout"],
        },
        "walk_forward_comparison": walk_forward,
        "recommendation": recommendation,
        "production_gate": {
            "promote_now": False,
            "reason": (
                "Promozione bloccata di proposito: serve conferma esplicita dopo "
                "lettura del resoconto metriche."
            ),
        },
    }

    results_path = reports_path / cfg["ensemble_results_filename"]
    with results_path.open("w", encoding="utf-8") as handle:
        json.dump(final_report, handle, indent=2, ensure_ascii=False, default=_json_default)
    final_report["results_path"] = str(results_path)
    return final_report


def _build_recommendation(
    market: MarketName,
    search_report: dict[str, Any],
    ensemble_report: dict[str, Any],
    walk_forward: dict[str, Any] | None,
) -> dict[str, Any]:
    prod = MARKET_CONFIG[market]["prod_baseline"]
    holdout_beats = bool(ensemble_report.get("beats_production_holdout"))
    wf_beats = bool((walk_forward or {}).get("beats_production"))
    best_ensemble = None
    best_ensemble_auc = -1.0
    for name in ("stacking", "voting_soft"):
        auc = ((ensemble_report["ensembles"].get(name) or {}).get("test_metrics") or {}).get("roc_auc")
        if auc is not None and float(auc) > best_ensemble_auc:
            best_ensemble_auc = float(auc)
            best_ensemble = name

    if holdout_beats and wf_beats:
        verdict = "candidate_for_production"
        detail = (
            f"{best_ensemble} batte {prod} sia su holdout sia su walk-forward quick. "
            "Attendere conferma esplicita prima del promote."
        )
    elif holdout_beats or wf_beats:
        verdict = "mixed_evidence"
        detail = (
            f"Segnale misto vs {prod}: holdout_beats={holdout_beats}, "
            f"walk_forward_beats={wf_beats}. Non promuovere ancora."
        )
    else:
        verdict = "keep_current_production"
        detail = (
            f"Ensemble non superiori a {prod} in modo consistente. "
            "Mantenere il modello di produzione attuale."
        )
    return {
        "verdict": verdict,
        "detail": detail,
        "best_ensemble_holdout": best_ensemble,
        "best_ensemble_holdout_roc_auc": _round(best_ensemble_auc) if best_ensemble else None,
        "production_baseline": prod,
        "search_winner": search_report.get("winner"),
        "walk_forward_best": (walk_forward or {}).get("best_model"),
    }


def format_experiment_summary(report: dict[str, Any]) -> str:
    market = report["market"]
    lines = [
        f"=== Ensemble experiment — {market} ===",
        f"Righe: {report['rows_total']} ({report['date_min']} → {report['date_max']})",
        f"Prep: {report['preparation_note']}",
        f"Quick mode: {report['quick_mode']}",
        "",
        "--- Grid search (holdout) ---",
    ]
    for name, payload in report["grid_search"]["algorithms"].items():
        lines.append(
            f"  {name}: CV auc={payload['cv_best_roc_auc']} | "
            f"test auc={payload['test_roc_auc']} | test roi={payload['test_roi']} "
            f"({payload['fit_seconds']}s)"
        )
    lines.append(f"  Top for ensemble: {report['grid_search']['top_algorithms_for_ensemble']}")
    prod = report["grid_search"]["production_baseline"]
    prod_m = prod.get("test_metrics") or {}
    lines.append(
        f"  Production baseline ({prod.get('model_name')}): "
        f"auc={prod_m.get('roc_auc')} roi={(prod_m.get('value_bet') or {}).get('roi')}"
    )
    lines.append("")
    lines.append("--- Ensembles (holdout; stacking then voting) ---")
    for name in ("stacking", "voting_soft"):
        ens = report["ensembles"][name]
        m = ens.get("test_metrics") or {}
        lines.append(
            f"  {name}: auc={m.get('roc_auc')} log_loss={m.get('log_loss')} "
            f"roi={(m.get('value_bet') or {}).get('roi')} ({ens['fit_seconds']}s)"
        )
        if "meta_learner_coefficients" in ens:
            lines.append(f"    meta coef: {ens['meta_learner_coefficients']}")
    holdout = report["holdout_comparison"]
    lines.append(
        f"  Holdout winner: {holdout['winner']} (auc={holdout['winner_roc_auc']}) "
        f"| beats_production={holdout['beats_production']}"
    )
    lines.append("")
    wf = report.get("walk_forward_comparison")
    if wf:
        lines.append("--- Walk-forward quick ---")
        for name in wf.get("ranking_by_roc_auc") or []:
            auc = ((wf.get("aggregate_metrics") or {}).get(name) or {}).get("roc_auc") or {}
            roi = ((wf.get("aggregate_value_bet_metrics") or {}).get(name) or {}).get("roi") or {}
            lines.append(
                f"  {name}: auc_mean={auc.get('mean')} roi_mean={roi.get('mean')} "
                f"(folds={wf.get('folds_completed_per_model', {}).get(name)})"
            )
        lines.append(
            f"  Best={wf.get('best_model')} | beats_production={wf.get('beats_production')}"
        )
    else:
        lines.append("--- Walk-forward: skipped ---")
    lines.append("")
    rec = report["recommendation"]
    lines.append(f"VERDICT: {rec['verdict']}")
    lines.append(f"  {rec['detail']}")
    lines.append(f"Report: {report.get('results_path')}")
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Grid search + stacking + voting per first_set_winner / over_under_games."
    )
    parser.add_argument(
        "--market",
        required=True,
        choices=["first_set_winner", "over_under_games"],
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--models-dir", default=None)
    parser.add_argument("--line", type=float, default=DEFAULT_LINE)
    parser.add_argument(
        "--min-date",
        default=None,
        help="Filtro cronologico (default O/U: 2024-12-01).",
    )
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--skip-walk-forward", action="store_true")
    parser.add_argument("--n-jobs", type=int, default=1)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with SessionLocal() as db:
        report = run_experiment(
            db,
            args.market,  # type: ignore[arg-type]
            processed_dir=args.processed_dir,
            reports_dir=args.reports_dir,
            models_dir=args.models_dir,
            line=args.line,
            min_date=args.min_date,
            quick=args.quick,
            skip_walk_forward=args.skip_walk_forward,
            n_jobs=args.n_jobs,
        )
    print(format_experiment_summary(report))


if __name__ == "__main__":
    main()
