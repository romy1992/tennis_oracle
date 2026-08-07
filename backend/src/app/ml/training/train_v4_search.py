"""Fase 1+2 — Grid search multi-algoritmo per valutare un possibile modello v4.

Riusa dataset/feature/preprocessing della v3 (le migliori feature disponibili oggi:
Elo/rank/form/H2H + quote di mercato come feature ML) e confronta, tramite
``GridSearchCV`` con validazione temporale (``TimeSeriesSplit``, niente shuffle
casuale), cinque famiglie di algoritmi:

- ``logistic_regression`` (penalty l2 e elasticnet)
- ``random_forest``
- ``hist_gradient_boosting`` (nativo scikit-learn, ZERO nuove dipendenze)
- ``xgboost`` (Fase 2 — nuova dipendenza ``xgboost``)
- ``lightgbm`` (Fase 2 — nuova dipendenza ``lightgbm``)

Questo script è **esplorativo**: non sovrascrive i modelli v1/v2/v3 in produzione,
non tocca ``model_registry.json``/``model_comparison.json`` e non modifica il
modello pubblico. Produce:

- un report JSON dedicato: ``data/reports/v4_grid_search_results.json``
- le pipeline vincitrici per ispezione manuale: ``data/models/v4_search/*.pkl``

Split temporale (no shuffle):
- 80% iniziale = "dev" set, usato dentro ``GridSearchCV`` con CV interna
  ``TimeSeriesSplit`` (rispetta l'ordine cronologico anche nella ricerca iperparametri);
- 20% finale = "test" set, mai visto durante il tuning, usato solo per il confronto
  onesto finale (accuracy, ROC AUC, log loss, value-bet ROI, benchmark di mercato).

Uso (da ``backend/src``)::

    python -m app.ml.training.train_v4_search --quick   # smoke test veloce (~1 min)
    python -m app.ml.training.train_v4_search           # grid search completa

Nota memoria/CPU: per prudenza (già osservati OOM nel walk-forward con i modelli
attuali), il parallelismo di ``GridSearchCV`` è impostato a 1 per default
(``--n-jobs``): RandomForest/XGBoost/LightGBM usano comunque il proprio ``n_jobs=-1``
internamente per gli alberi di un singolo fit, ma le combinazioni di griglia vengono
provate in sequenza per evitare di moltiplicare i processi paralleli.
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.model_versioning import (  # noqa: E402
    MODELS_DIR,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
)
from backend.src.app.ml.training.train_baseline import (  # noqa: E402
    TARGET_COLUMN,
    build_preprocessor,
    classification_metrics,
    excluded_feature_columns,
    filter_rows_with_valid_odds,
    market_benchmark_metrics,
    select_training_dataset,
    selected_feature_columns,
    temporal_train_test_split,
)
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD  # noqa: E402

logger = logging.getLogger(__name__)

# La ricerca riusa il dataset/feature-set della v3 (le migliori disponibili oggi:
# include odds come feature ML). Cambia solo l'algoritmo, non le feature.
SEARCH_MODEL_VERSION = "v3"
DEFAULT_DEV_SIZE = 0.8
DEFAULT_CV_SPLITS = 3
RESULTS_FILENAME = "v4_grid_search_results.json"
SEARCH_MODELS_DIR_NAME = "v4_search"


def build_param_grids(quick: bool = False) -> dict[str, list[dict[str, Any]]]:
    """Griglie iperparametri per algoritmo (lista di dict = combinazioni alternative)."""
    if quick:
        return {
            "logistic_regression": [
                {
                    "model__l1_ratio": [0.0],
                    "model__solver": ["lbfgs"],
                    "model__C": [1.0],
                    "model__class_weight": [None],
                    "model__max_iter": [2000],
                },
            ],
            "random_forest": [
                {
                    "model__n_estimators": [100],
                    "model__max_depth": [14],
                    "model__min_samples_leaf": [20],
                    "model__max_features": ["sqrt"],
                },
            ],
            "hist_gradient_boosting": [
                {
                    "model__max_iter": [100],
                    "model__max_depth": [6],
                    "model__learning_rate": [0.1],
                    "model__l2_regularization": [0.0],
                },
            ],
            "xgboost": [
                {
                    "model__n_estimators": [100],
                    "model__max_depth": [6],
                    "model__learning_rate": [0.1],
                    "model__subsample": [1.0],
                    "model__colsample_bytree": [1.0],
                },
            ],
            "lightgbm": [
                {
                    "model__n_estimators": [100],
                    "model__max_depth": [-1],
                    "model__learning_rate": [0.1],
                    "model__num_leaves": [31],
                },
            ],
        }

    return {
        "logistic_regression": [
            {
                "model__l1_ratio": [0.0],
                "model__solver": ["lbfgs"],
                "model__C": [0.01, 0.1, 1.0, 10.0],
                "model__class_weight": [None, "balanced"],
                "model__max_iter": [3000],
            },
            {
                # 'saga' con elasticnet non converge velocemente su ~80K righe con
                # feature one-hot (osservato: >40 minuti senza completare 24 combinazioni).
                # Griglia ridotta al minimo utile per uno screening, non esaustiva.
                "model__solver": ["saga"],
                "model__C": [0.1, 1.0],
                "model__l1_ratio": [0.5],
                "model__class_weight": [None],
                "model__max_iter": [1500],
                "model__tol": [1e-3],
            },
        ],
        "random_forest": [
            {
                "model__n_estimators": [100, 200],
                "model__max_depth": [10, 14, 20],
                "model__min_samples_leaf": [10, 20, 50],
                "model__max_features": ["sqrt", "log2"],
            },
        ],
        "hist_gradient_boosting": [
            {
                "model__max_iter": [100, 300],
                "model__max_depth": [None, 6, 10],
                "model__learning_rate": [0.05, 0.1, 0.2],
                "model__l2_regularization": [0.0, 1.0],
            },
        ],
        "xgboost": [
            {
                "model__n_estimators": [100, 300],
                "model__max_depth": [3, 6],
                "model__learning_rate": [0.05, 0.1],
                "model__subsample": [0.8, 1.0],
                "model__colsample_bytree": [0.8],
            },
        ],
        "lightgbm": [
            {
                "model__n_estimators": [100, 300],
                "model__max_depth": [-1, 10],
                "model__learning_rate": [0.05, 0.1],
                "model__num_leaves": [31, 63],
            },
        ],
    }


def build_base_estimators() -> dict[str, Any]:
    """Stimatori "vuoti": i valori effettivi vengono impostati da GridSearchCV."""
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    return {
        "logistic_regression": LogisticRegression(),
        # random_state/n_jobs fissi (come in train_baseline/walk_forward), non in griglia.
        "random_forest": RandomForestClassifier(random_state=42, n_jobs=-1),
        "hist_gradient_boosting": HistGradientBoostingClassifier(random_state=42),
        # eval_metric fisso per evitare il warning di xgboost sul default che cambia in base
        # all'obiettivo; n_jobs=-1 come gli altri alberi. Nessun early stopping (coerente con
        # RF/HistGB, che non lo usano in questa fase esplorativa).
        "xgboost": XGBClassifier(random_state=42, n_jobs=-1, eval_metric="logloss"),
        # verbosity=-1 silenzia i log interni di LightGBM (altrimenti molto verboso per ogni fit).
        "lightgbm": LGBMClassifier(random_state=42, n_jobs=-1, verbosity=-1),
    }


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


def run_search(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    models_dir: str | Path | None = None,
    dev_size: float = DEFAULT_DEV_SIZE,
    cv_splits: int = DEFAULT_CV_SPLITS,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    quick: bool = False,
    n_jobs: int = 1,
) -> dict[str, Any]:
    from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
    from sklearn.pipeline import Pipeline

    dataset_path = select_training_dataset(processed_dir, model_version=SEARCH_MODEL_VERSION)
    dataframe = pd.read_csv(dataset_path, low_memory=False)
    rows_before_odds_filter = len(dataframe)
    dataframe = filter_rows_with_valid_odds(dataframe)
    if dataframe.empty:
        raise ValueError("Dataset v3 senza righe con odds valide.")

    # "train" = dev set (80% cronologico iniziale, CV interna); "test" = holdout finale.
    split = temporal_train_test_split(dataframe, test_size=round(1 - dev_size, 6))
    feature_columns = selected_feature_columns(split.train, model_version=SEARCH_MODEL_VERSION)
    if not feature_columns:
        raise ValueError("Nessuna feature pre-match disponibile per la grid search v4.")
    excluded_columns = excluded_feature_columns(dataframe, feature_columns, model_version=SEARCH_MODEL_VERSION)

    x_dev = split.train[feature_columns]
    y_dev = split.train[TARGET_COLUMN].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[TARGET_COLUMN].astype(int)

    resolved_models_dir = Path(models_dir) if models_dir is not None else (Path(MODELS_DIR) / SEARCH_MODELS_DIR_NAME)
    resolved_models_dir.mkdir(parents=True, exist_ok=True)
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    estimators = build_base_estimators()
    param_grids = build_param_grids(quick=quick)
    effective_cv_splits = 2 if quick else cv_splits
    time_series_cv = TimeSeriesSplit(n_splits=effective_cv_splits)

    results: dict[str, SearchResult] = {}
    for name, estimator in estimators.items():
        logger.info("Avvio GridSearchCV per %s (quick=%s, combinazioni=%s)", name, quick, _grid_size(param_grids[name]))
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
        predictions = (probabilities >= 0.5).astype(int)
        test_metrics = classification_metrics(
            y_dev,
            y_test,
            predictions,
            probabilities,
            split.test,
            edge_threshold=edge_threshold,
        )

        best_index = grid.best_index_
        cv_best_neg_log_loss = grid.cv_results_["mean_test_neg_log_loss"][best_index]

        model_path = resolved_models_dir / f"{name}.pkl"
        with model_path.open("wb") as model_file:
            pickle.dump(
                {
                    "pipeline": grid.best_estimator_,
                    "feature_columns": feature_columns,
                    "dataset_path": str(dataset_path),
                    "model_version": "v4_search",
                    "algorithm": name,
                    "best_params": grid.best_params_,
                },
                model_file,
            )

        results[name] = SearchResult(
            algorithm=name,
            best_params=grid.best_params_,
            cv_best_roc_auc=_round(grid.best_score_),
            cv_best_neg_log_loss=_round(cv_best_neg_log_loss),
            cv_results_top=_top_cv_combinations(grid.cv_results_, top_n=5),
            test_metrics=test_metrics,
            fit_seconds=fit_seconds,
            model_path=str(model_path),
        )
        logger.info(
            "%s completato in %.1fs — CV best roc_auc=%s — test roc_auc=%s",
            name,
            fit_seconds,
            _round(grid.best_score_),
            test_metrics.get("roc_auc"),
        )

    winner = max(results.values(), key=lambda item: (item.test_metrics.get("roc_auc") or -1.0))

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "fase_1_grid_search",
        "search_model_version_base": SEARCH_MODEL_VERSION,
        "dataset_used": str(dataset_path),
        "rows_total": int(len(dataframe)),
        "rows_before_odds_filter": int(rows_before_odds_filter),
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
        "features_excluded": excluded_columns,
        "edge_threshold": edge_threshold,
        "quick_mode": quick,
        "algorithms": {
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
        },
        "market_benchmark_on_test": market_benchmark_metrics(split.test),
        "winner": winner.algorithm,
        "winner_test_roc_auc": winner.test_metrics.get("roc_auc"),
        "notes": [
            "Script esplorativo Fase 1: NON sovrascrive v1/v2/v3 ne' model_registry.json.",
            "Modelli salvati in data/models/v4_search/ solo per ispezione manuale.",
            "Il vincitore va validato con walk-forward (Fase 5) prima di una eventuale promozione a v4 ufficiale.",
        ],
    }

    results_path = reports_path / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=_json_default)

    report["results_path"] = str(results_path)
    return report


def format_search_summary(report: dict[str, Any]) -> str:
    split = report["split"]
    lines = [
        f"Fase 1 - Grid search v4 (feature base: {report['search_model_version_base']})",
        f"Dataset: {report['dataset_used']}",
        f"Righe con odds valide: {report['rows_total']} (prima del filtro: {report['rows_before_odds_filter']})",
        (
            f"Split dev/test: {split['dev_rows']} / {split['test_rows']} "
            f"({split['dev_date_min']} - {split['dev_date_max']} / "
            f"{split['test_date_min']} - {split['test_date_max']})"
        ),
        f"CV interna: {split['inner_cv']}",
        "",
    ]
    for name, algo in report["algorithms"].items():
        value_bet = algo["test_metrics"].get("value_bet_overall", {})
        lines.append(f"--- {name} (fit in {algo['fit_seconds']}s) ---")
        lines.append(f"  best_params: {algo['best_params']}")
        lines.append(
            "  CV best roc_auc=%s | test roc_auc=%s | test log_loss=%s | test accuracy=%s"
            % (
                algo["cv_best_roc_auc"],
                algo["test_metrics"].get("roc_auc"),
                algo["test_metrics"].get("log_loss"),
                algo["test_metrics"].get("accuracy"),
            )
        )
        lines.append(
            "  value_bet edge>=%s: bets=%s hit_rate=%s roi=%s"
            % (
                report["edge_threshold"],
                value_bet.get("bets_count"),
                value_bet.get("hit_rate"),
                value_bet.get("roi"),
            )
        )
        lines.append("")
    lines.append(f"VINCITORE (test roc_auc piu' alto): {report['winner']} (roc_auc={report['winner_test_roc_auc']})")
    market = report.get("market_benchmark_on_test") or {}
    lines.append(
        "Benchmark mercato sullo stesso test set: accuracy=%s roc_auc=%s roi_bet_all=%s"
        % (
            market.get("market_accuracy"),
            market.get("market_roc_auc"),
            market.get("market_roi_if_bet_player_1_all"),
        )
    )
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Fase 1: grid search multi-algoritmo (logistic_regression / random_forest / "
            "hist_gradient_boosting) per valutare un possibile modello v4."
        )
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--models-dir", default=None)
    parser.add_argument("--dev-size", type=float, default=DEFAULT_DEV_SIZE)
    parser.add_argument("--cv-splits", type=int, default=DEFAULT_CV_SPLITS)
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="Parallelismo GridSearchCV (default 1: conservativo per evitare OOM, RF usa comunque n_jobs=-1 interno).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Griglie ridotte a 1 combinazione per algoritmo + cv=2: smoke test veloce end-to-end.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Avvio Fase 1 grid search v4 (quick=%s)", args.quick)

    report = run_search(
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        models_dir=args.models_dir,
        dev_size=args.dev_size,
        cv_splits=args.cv_splits,
        edge_threshold=args.edge_threshold,
        quick=args.quick,
        n_jobs=args.n_jobs,
    )
    print(format_search_summary(report))


def _grid_size(param_grid_list: list[dict[str, Any]]) -> int:
    total = 0
    for grid in param_grid_list:
        combinations = 1
        for values in grid.values():
            combinations *= len(values)
        total += combinations
    return total


def _top_cv_combinations(cv_results: dict[str, Any], top_n: int = 5) -> list[dict[str, Any]]:
    n_candidates = len(cv_results["params"])
    order = sorted(
        range(n_candidates),
        key=lambda i: (cv_results["mean_test_roc_auc"][i] if cv_results["mean_test_roc_auc"][i] is not None else -1.0),
        reverse=True,
    )
    top: list[dict[str, Any]] = []
    for i in order[:top_n]:
        top.append(
            {
                "params": cv_results["params"][i],
                "mean_roc_auc": _round(cv_results["mean_test_roc_auc"][i]),
                "std_roc_auc": _round(cv_results["std_test_roc_auc"][i]),
                "mean_neg_log_loss": _round(cv_results["mean_test_neg_log_loss"][i]),
            }
        )
    return top


def _round(value: Any) -> float | None:
    if value is None:
        return None
    try:
        float_value = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(float_value):
        return None
    return round(float_value, 6)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


def _date_min(dataframe: pd.DataFrame, column: str) -> str | None:
    if column not in dataframe.columns:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.min().date().isoformat()


def _date_max(dataframe: pd.DataFrame, column: str) -> str | None:
    if column not in dataframe.columns:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.max().date().isoformat()


if __name__ == "__main__":
    main()

