"""Fase 3 - Voting ensemble tra i migliori algoritmi trovati in Fase 1.

Legge ``data/reports/v4_grid_search_results.json`` (prodotto da
``train_v4_search.py``), ricostruisce le pipeline vincitrici di ciascun
algoritmo con i rispettivi ``best_params`` e le combina in un
``VotingClassifier(voting="soft")``.

Approccio ai pesi: prova alcune combinazioni di pesi (uniforme, pesato sul
ROC AUC di CV) e sceglie quella con il ROC AUC piu' alto sullo stesso test
set "vergine" della Fase 1 (stesso split temporale, riprodotto identicamente
a partire dallo stesso dataset/dev_size cosi' il confronto e' onesto).

Questo script e' **esplorativo**: non tocca i modelli v1/v2/v3 in
produzione, ne' ``model_registry.json``/``model_comparison.json``.

Uso (da ``backend/src``)::

    python -m app.ml.training.train_v4_voting
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
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
    filter_rows_with_valid_odds,
    market_benchmark_metrics,
    select_training_dataset,
    selected_feature_columns,
    temporal_train_test_split,
)
from backend.src.app.ml.training.train_v4_search import (  # noqa: E402
    RESULTS_FILENAME as SEARCH_RESULTS_FILENAME,
    SEARCH_MODEL_VERSION,
)
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD  # noqa: E402

logger = logging.getLogger(__name__)

VOTING_RESULTS_FILENAME = "v4_voting_results.json"
VOTING_MODELS_DIR_NAME = "v4_voting"

# Combinazioni di pesi da provare (ordine allineato a ``sorted(algorithm_names)``).
# "uniform" e alcune varianti che privilegiano l'algoritmo con CV roc_auc piu' alto.
WEIGHT_STRATEGIES: dict[str, str] = {
    "uniform": "Pesi uguali per tutti gli algoritmi (1,1,1).",
    "cv_score_weighted": "Pesi proporzionali al CV best roc_auc di ciascun algoritmo.",
    "favor_best": "Peso doppio per l'algoritmo con miglior CV roc_auc, 1 per gli altri.",
}


def _instantiate_estimator(algorithm: str, params: dict[str, Any]):
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier

    # params sono nel formato "model__<param>": valore (prefisso pipeline step "model").
    clean_params = {key.split("__", 1)[1]: value for key, value in params.items() if key.startswith("model__")}

    if algorithm == "logistic_regression":
        return LogisticRegression(**clean_params)
    if algorithm == "random_forest":
        base = {"random_state": 42, "n_jobs": -1}
        base.update(clean_params)
        return RandomForestClassifier(**base)
    if algorithm == "hist_gradient_boosting":
        base = {"random_state": 42}
        base.update(clean_params)
        return HistGradientBoostingClassifier(**base)
    if algorithm == "xgboost":
        # Stessa convenzione di train_v4_search.build_base_estimators/
        # train_v4_ensemble.build_tuned_estimator: eval_metric fisso, n_jobs=-1.
        base = {"random_state": 42, "n_jobs": -1, "eval_metric": "logloss"}
        base.update(clean_params)
        return XGBClassifier(**base)
    if algorithm == "lightgbm":
        # verbosity=-1 silenzia i log interni di LightGBM (come in train_v4_search).
        base = {"random_state": 42, "n_jobs": -1, "verbosity": -1}
        base.update(clean_params)
        return LGBMClassifier(**base)
    raise ValueError(f"Algoritmo sconosciuto: {algorithm}")


def load_search_results(reports_dir: str | Path = REPORTS_DIR) -> dict[str, Any]:
    results_path = Path(reports_dir) / SEARCH_RESULTS_FILENAME
    if not results_path.exists():
        raise FileNotFoundError(
            f"Report Fase 1 non trovato in {results_path}. Esegui prima "
            "`python -m app.ml.training.train_v4_search` (Fase 1)."
        )
    with results_path.open("r", encoding="utf-8") as results_file:
        return json.load(results_file)


def _weight_vector(strategy: str, algorithm_names: list[str], cv_scores: dict[str, float]) -> list[float]:
    if strategy == "uniform":
        return [1.0 for _ in algorithm_names]
    if strategy == "cv_score_weighted":
        # Rebase sopra 0 (roc_auc e' gia' in [0,1], ma per sicurezza tagliamo a 0).
        return [max(cv_scores.get(name, 0.0), 1e-6) for name in algorithm_names]
    if strategy == "favor_best":
        best = max(algorithm_names, key=lambda name: cv_scores.get(name, 0.0))
        return [2.0 if name == best else 1.0 for name in algorithm_names]
    raise ValueError(f"Strategia pesi sconosciuta: {strategy}")


def run_voting(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    models_dir: str | Path | None = None,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
) -> dict[str, Any]:
    from sklearn.ensemble import VotingClassifier
    from sklearn.pipeline import Pipeline

    search_report = load_search_results(reports_dir)
    algorithms_detail = search_report["algorithms"]
    algorithm_names = sorted(algorithms_detail.keys())
    if len(algorithm_names) < 2:
        raise ValueError("Servono almeno 2 algoritmi nel report Fase 1 per costruire un voting ensemble.")

    # Ricostruisce ESATTAMENTE lo stesso split dev/test della Fase 1 (stesso dataset/dev_size).
    dataset_path = select_training_dataset(processed_dir, model_version=SEARCH_MODEL_VERSION)
    dataframe = pd.read_csv(dataset_path, low_memory=False)
    dataframe = filter_rows_with_valid_odds(dataframe)
    dev_size = search_report["split"]["dev_size"]
    split = temporal_train_test_split(dataframe, test_size=round(1 - dev_size, 6))
    feature_columns = selected_feature_columns(split.train, model_version=SEARCH_MODEL_VERSION)

    x_dev = split.train[feature_columns]
    y_dev = split.train[TARGET_COLUMN].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[TARGET_COLUMN].astype(int)

    resolved_models_dir = Path(models_dir) if models_dir is not None else (Path(MODELS_DIR) / VOTING_MODELS_DIR_NAME)
    resolved_models_dir.mkdir(parents=True, exist_ok=True)
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    cv_scores = {name: algorithms_detail[name].get("cv_best_roc_auc") or 0.0 for name in algorithm_names}

    preprocessor = build_preprocessor(split.train, feature_columns)
    estimators_for_voting = []
    for name in algorithm_names:
        best_params = algorithms_detail[name]["best_params"]
        estimator = _instantiate_estimator(name, best_params)
        pipeline = Pipeline(steps=[("preprocessor", preprocessor), ("model", estimator)])
        estimators_for_voting.append((name, pipeline))

    strategy_results: dict[str, Any] = {}
    fitted_voting_by_strategy: dict[str, VotingClassifier] = {}
    for strategy in WEIGHT_STRATEGIES:
        weights = _weight_vector(strategy, algorithm_names, cv_scores)
        logger.info("Fit VotingClassifier (strategy=%s, weights=%s)", strategy, weights)
        voting = VotingClassifier(estimators=estimators_for_voting, voting="soft", weights=weights, n_jobs=1)
        voting.fit(x_dev, y_dev)

        probabilities = voting.predict_proba(x_test)[:, 1]
        predictions = (probabilities >= 0.5).astype(int)
        test_metrics = classification_metrics(
            y_dev,
            y_test,
            predictions,
            probabilities,
            split.test,
            edge_threshold=edge_threshold,
        )
        strategy_results[strategy] = {
            "description": WEIGHT_STRATEGIES[strategy],
            "weights": dict(zip(algorithm_names, weights)),
            "test_metrics": test_metrics,
        }
        fitted_voting_by_strategy[strategy] = voting
        logger.info(
            "Strategy=%s -> test roc_auc=%s log_loss=%s accuracy=%s",
            strategy,
            test_metrics.get("roc_auc"),
            test_metrics.get("log_loss"),
            test_metrics.get("accuracy"),
        )

    best_strategy = max(
        strategy_results.items(),
        key=lambda item: (item[1]["test_metrics"].get("roc_auc") or -1.0),
    )[0]

    best_voting_path = resolved_models_dir / f"voting_{best_strategy}.pkl"
    with best_voting_path.open("wb") as model_file:
        pickle.dump(
            {
                "pipeline": fitted_voting_by_strategy[best_strategy],
                "feature_columns": feature_columns,
                "dataset_path": str(dataset_path),
                "model_version": "v4_voting",
                "strategy": best_strategy,
                "algorithms": algorithm_names,
            },
            model_file,
        )

    # Confronto diretto contro i singoli algoritmi della Fase 1 (stesso test set).
    single_algo_comparison = {
        name: {
            "roc_auc": algorithms_detail[name]["test_metrics"].get("roc_auc"),
            "log_loss": algorithms_detail[name]["test_metrics"].get("log_loss"),
            "accuracy": algorithms_detail[name]["test_metrics"].get("accuracy"),
        }
        for name in algorithm_names
    }
    best_single_algo = max(
        single_algo_comparison.items(),
        key=lambda item: (item[1]["roc_auc"] or -1.0),
    )[0]

    voting_beats_best_single = (
        (strategy_results[best_strategy]["test_metrics"].get("roc_auc") or -1.0)
        > (single_algo_comparison[best_single_algo]["roc_auc"] or -1.0)
    )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "fase_3_voting_ensemble",
        "source_search_report": str(Path(reports_dir) / SEARCH_RESULTS_FILENAME),
        "algorithms_used": algorithm_names,
        "edge_threshold": edge_threshold,
        "strategies": strategy_results,
        "best_strategy": best_strategy,
        "best_voting_model_path": str(best_voting_path),
        "single_algorithm_comparison": single_algo_comparison,
        "best_single_algorithm": best_single_algo,
        "voting_beats_best_single_algorithm": bool(voting_beats_best_single),
        "market_benchmark_on_test": market_benchmark_metrics(split.test),
        "notes": [
            "Script esplorativo Fase 3: NON sovrascrive v1/v2/v3 ne' model_registry.json.",
            "Pesi provati: uniform, cv_score_weighted, favor_best (vedi WEIGHT_STRATEGIES).",
            "Se voting_beats_best_single_algorithm=false, conviene tenere il singolo modello "
            "(piu' semplice da mantenere/spiegare) invece dell'ensemble.",
        ],
    }

    results_path = reports_path / VOTING_RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=_json_default)
    report["results_path"] = str(results_path)
    return report


def format_voting_summary(report: dict[str, Any]) -> str:
    lines = [
        "Fase 3 - Voting ensemble",
        f"Algoritmi combinati: {report['algorithms_used']}",
        "",
        "--- Confronto singoli algoritmi (Fase 1, stesso test set) ---",
    ]
    for name, metrics in report["single_algorithm_comparison"].items():
        lines.append(f"  {name}: roc_auc={metrics['roc_auc']} log_loss={metrics['log_loss']} accuracy={metrics['accuracy']}")
    lines.append(f"  Migliore singolo: {report['best_single_algorithm']}")
    lines.append("")
    lines.append("--- Strategie di voting ---")
    for strategy, detail in report["strategies"].items():
        metrics = detail["test_metrics"]
        lines.append(
            f"  {strategy} (pesi={detail['weights']}): roc_auc={metrics.get('roc_auc')} "
            f"log_loss={metrics.get('log_loss')} accuracy={metrics.get('accuracy')}"
        )
    lines.append("")
    lines.append(f"MIGLIORE STRATEGIA VOTING: {report['best_strategy']}")
    lines.append(f"Il voting batte il miglior singolo algoritmo? {report['voting_beats_best_single_algorithm']}")
    lines.append(f"Modello voting salvato in: {report['best_voting_model_path']}")
    lines.append(f"Report completo: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fase 3: Voting ensemble (soft) tra i migliori algoritmi trovati nella Fase 1."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--models-dir", default=None)
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Avvio Fase 3 voting ensemble")

    report = run_voting(
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        models_dir=args.models_dir,
        edge_threshold=args.edge_threshold,
    )
    print(format_voting_summary(report))


def _json_default(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return str(obj)


if __name__ == "__main__":
    main()



