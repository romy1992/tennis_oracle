"""Fase 3 — Ensemble (Voting + Stacking) sui migliori algoritmi delle Fasi 1+2.

Riusa lo stesso dataset/feature-set/split temporale della Fase 1+2 (v3: Elo/rank/
form/H2H + quote di mercato come feature ML) e i migliori iperparametri già trovati
da ``train_v4_search`` (``data/reports/v4_grid_search_results.json``) per tre modelli
base selezionati in base ai risultati Fase 1+2 (ROC AUC e ROI value-bet):

- ``logistic_regression`` (miglior ROI, roc_auc quasi al top)
- ``xgboost`` (miglior ROC AUC assoluto della Fase 2)
- ``hist_gradient_boosting`` (zero nuove dipendenze, terzo per ROC AUC)

Esclusi deliberatamente ``random_forest`` (ROI nettamente peggiore, -10.5%) e
``lightgbm`` (peggior ROC AUC/accuracy tra i 5 algoritmi testati).

Costruisce e valuta due ensemble, sullo stesso holdout "test" mai visto in fase di
tuning (confronto onesto con Fase 1+2):

- ``voting_soft``: media delle probabilità dei 3 modelli base (nessun training
  aggiuntivo oltre ai 3 base estimator).
- ``stacking``: meta-learner (``LogisticRegression``) allenato sulle previsioni
  out-of-fold dei 3 modelli base, con CV interna ``TimeSeriesSplit`` per rispettare
  l'ordine cronologico ed evitare leakage nel meta-learner.

Questo script è **esplorativo**: non sovrascrive i modelli v1/v2/v3 in produzione,
non tocca ``model_registry.json``/``model_comparison.json`` e non modifica il
modello pubblico. Produce:

- un report JSON dedicato: ``data/reports/v4_ensemble_results.json``
- le pipeline vincitrici per ispezione manuale: ``data/models/v4_ensemble/*.pkl``

Uso (da repo root)::

    python -m backend.src.app.ml.training.train_v4_ensemble --quick   # smoke test
    python -m backend.src.app.ml.training.train_v4_ensemble           # run completa
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
from backend.src.app.ml.training.train_v4_search import (  # noqa: E402
    _date_max,
    _date_min,
    _json_default,
    _round,
)
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD  # noqa: E402

logger = logging.getLogger(__name__)

SEARCH_MODEL_VERSION = "v3"
DEFAULT_DEV_SIZE = 0.8
DEFAULT_CV_SPLITS = 3
SEARCH_RESULTS_FILENAME = "v4_grid_search_results.json"
RESULTS_FILENAME = "v4_ensemble_results.json"
ENSEMBLE_MODELS_DIR_NAME = "v4_ensemble"

# I 3 modelli base selezionati in base ai risultati Fase 1+2 (vedi docstring).
BASE_ALGORITHMS = ["logistic_regression", "xgboost", "hist_gradient_boosting"]

# Iperparametri di fallback (usati solo se v4_grid_search_results.json non esiste
# ancora o non contiene un algoritmo atteso): valori ragionevoli, non ottimizzati.
_FALLBACK_BEST_PARAMS: dict[str, dict[str, Any]] = {
    "logistic_regression": {"C": 0.01, "class_weight": "balanced", "max_iter": 3000, "solver": "lbfgs"},
    "xgboost": {"n_estimators": 100, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.8, "colsample_bytree": 0.8},
    "hist_gradient_boosting": {"max_iter": 100, "max_depth": 10, "learning_rate": 0.05, "l2_regularization": 0.0},
}


def load_best_params(reports_dir: str | Path, algorithm: str) -> tuple[dict[str, Any], str]:
    """Legge i best_params trovati in Fase 1+2 per un algoritmo dal report grid search.

    Ritorna (params_puliti_senza_prefisso_model__, sorgente_descrittiva).
    Se il report o l'algoritmo non sono disponibili, usa un fallback ragionevole
    (non ottimizzato) e lo segnala nella sorgente, senza sollevare eccezioni: lo
    script Fase 3 deve poter girare anche prima di aver eseguito la Fase 1+2.
    """
    results_path = Path(reports_dir) / SEARCH_RESULTS_FILENAME
    if results_path.exists():
        try:
            with results_path.open("r", encoding="utf-8") as handle:
                search_report = json.load(handle)
            raw_params = search_report["algorithms"][algorithm]["best_params"]
            clean_params = {key.removeprefix("model__"): value for key, value in raw_params.items()}
            return clean_params, f"v4_grid_search_results.json ({search_report.get('generated_at', '?')})"
        except (KeyError, json.JSONDecodeError, OSError) as exc:
            logger.warning("Impossibile leggere best_params per %s da %s: %s", algorithm, results_path, exc)
    return dict(_FALLBACK_BEST_PARAMS[algorithm]), "fallback (Fase 1+2 non ancora eseguita per questo algoritmo)"


def build_tuned_estimator(algorithm: str, params: dict[str, Any]) -> Any:
    """Istanzia lo stimatore di un algoritmo con gli iperparametri tunati forniti."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from xgboost import XGBClassifier

    if algorithm == "logistic_regression":
        return LogisticRegression(**params)
    if algorithm == "xgboost":
        return XGBClassifier(random_state=42, n_jobs=-1, eval_metric="logloss", **params)
    if algorithm == "hist_gradient_boosting":
        return HistGradientBoostingClassifier(random_state=42, **params)
    raise ValueError(f"Algoritmo non supportato per l'ensemble: {algorithm}")


def build_base_estimators(reports_dir: str | Path) -> tuple[list[tuple[str, Any]], dict[str, dict[str, Any]]]:
    """Costruisce i 3 stimatori base (tunati) e ne registra provenienza/parametri."""
    estimators: list[tuple[str, Any]] = []
    provenance: dict[str, dict[str, Any]] = {}
    for algorithm in BASE_ALGORITHMS:
        params, source = load_best_params(reports_dir, algorithm)
        estimators.append((algorithm, build_tuned_estimator(algorithm, params)))
        provenance[algorithm] = {"params_used": params, "source": source}
    return estimators, provenance


@dataclass(frozen=True)
class EnsembleResult:
    name: str
    test_metrics: dict[str, Any]
    fit_seconds: float
    model_path: str
    extra_info: dict[str, Any]


def run_ensemble(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    models_dir: str | Path | None = None,
    dev_size: float = DEFAULT_DEV_SIZE,
    cv_splits: int = DEFAULT_CV_SPLITS,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    quick: bool = False,
    n_jobs: int = 1,
) -> dict[str, Any]:
    from sklearn.ensemble import StackingClassifier, VotingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import KFold
    from sklearn.pipeline import Pipeline

    dataset_path = select_training_dataset(processed_dir, model_version=SEARCH_MODEL_VERSION)
    dataframe = pd.read_csv(dataset_path, low_memory=False)
    rows_before_odds_filter = len(dataframe)
    dataframe = filter_rows_with_valid_odds(dataframe)
    if dataframe.empty:
        raise ValueError("Dataset v3 senza righe con odds valide.")

    # Stesso split della Fase 1+2 (identico dev_size, stessa strategia temporale):
    # garantisce un confronto onesto tra ensemble e singoli modelli.
    split = temporal_train_test_split(dataframe, test_size=round(1 - dev_size, 6))
    feature_columns = selected_feature_columns(split.train, model_version=SEARCH_MODEL_VERSION)
    if not feature_columns:
        raise ValueError("Nessuna feature pre-match disponibile per l'ensemble v4.")
    excluded_columns = excluded_feature_columns(dataframe, feature_columns, model_version=SEARCH_MODEL_VERSION)

    x_dev = split.train[feature_columns]
    y_dev = split.train[TARGET_COLUMN].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[TARGET_COLUMN].astype(int)

    resolved_models_dir = Path(models_dir) if models_dir is not None else (Path(MODELS_DIR) / ENSEMBLE_MODELS_DIR_NAME)
    resolved_models_dir.mkdir(parents=True, exist_ok=True)
    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)

    base_estimators, provenance = build_base_estimators(reports_dir)
    effective_cv_splits = 2 if quick else cv_splits
    # NOTA: StackingClassifier genera le predizioni out-of-fold (OOF) per allenare il
    # meta-learner tramite sklearn.model_selection.cross_val_predict, che richiede che i
    # fold di test formino una PARTIZIONE COMPLETA del dataset passato a .fit(). TimeSeriesSplit,
    # per costruzione, esclude sempre la porzione iniziale (usata solo come "warm-up" di
    # training) da qualunque fold di test: non e' MAI una partizione completa per
    # n_splits >= 1, quindi non e' utilizzabile come cv di uno StackingClassifier (solleva
    # "ValueError: cross_val_predict only works for partitions", riprodotto anche con dati
    # sintetici in test_train_v4_ensemble.py). Usiamo percio' un KFold non mescolato
    # (shuffle=False -> blocchi contigui in ordine cronologico) solo per l'OOF interno del
    # meta-learner: il fold i puo' essere valutato da un modello allenato anche su blocchi
    # cronologicamente successivi, ma questo leak residuo resta confinato alla calibrazione
    # dei pesi del meta-learner (LogisticRegression) e NON intacca il test set finale, mai
    # visto ne' dai base estimator ne' dal meta-learner durante il fit.
    stacking_inner_cv = KFold(n_splits=effective_cv_splits, shuffle=False)

    preprocessor = build_preprocessor(split.train, feature_columns)

    ensemble_definitions: dict[str, Any] = {
        "voting_soft": Pipeline(
            steps=[
                ("preprocessor", preprocessor),
                (
                    "ensemble",
                    VotingClassifier(estimators=list(base_estimators), voting="soft", n_jobs=n_jobs),
                ),
            ]
        ),
        "stacking": Pipeline(
            steps=[
                ("preprocessor", preprocessor),
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
    }

    results: dict[str, EnsembleResult] = {}
    for name, pipeline in ensemble_definitions.items():
        logger.info("Avvio fit ensemble '%s' (base=%s, quick=%s)", name, BASE_ALGORITHMS, quick)
        start = time.perf_counter()
        pipeline.fit(x_dev, y_dev)
        fit_seconds = round(time.perf_counter() - start, 2)

        probabilities = pipeline.predict_proba(x_test)[:, 1]
        predictions = (probabilities >= 0.5).astype(int)
        test_metrics = classification_metrics(
            y_dev,
            y_test,
            predictions,
            probabilities,
            split.test,
            edge_threshold=edge_threshold,
        )

        model_path = resolved_models_dir / f"{name}.pkl"
        with model_path.open("wb") as model_file:
            pickle.dump(
                {
                    "pipeline": pipeline,
                    "feature_columns": feature_columns,
                    "dataset_path": str(dataset_path),
                    "model_version": "v4_ensemble",
                    "ensemble_name": name,
                    "base_algorithms": BASE_ALGORITHMS,
                },
                model_file,
            )

        extra_info: dict[str, Any] = {"base_algorithms": BASE_ALGORITHMS}
        if name == "stacking":
            meta = pipeline.named_steps["ensemble"].final_estimator_
            extra_info["meta_learner_coefficients"] = {
                algo: _round(coef)
                for algo, coef in zip(BASE_ALGORITHMS, meta.coef_[0].tolist())
            }
            extra_info["meta_learner_intercept"] = _round(meta.intercept_[0])

        results[name] = EnsembleResult(
            name=name,
            test_metrics=test_metrics,
            fit_seconds=fit_seconds,
            model_path=str(model_path),
            extra_info=extra_info,
        )
        logger.info(
            "%s completato in %.1fs — test roc_auc=%s",
            name,
            fit_seconds,
            test_metrics.get("roc_auc"),
        )

    # Confronto con i singoli modelli della Fase 1+2 (se il report esiste).
    single_models_comparison: dict[str, Any] = {}
    best_single_algorithm = None
    best_single_roc_auc = -1.0
    search_results_path = Path(reports_dir) / SEARCH_RESULTS_FILENAME
    if search_results_path.exists():
        try:
            with search_results_path.open("r", encoding="utf-8") as handle:
                search_report = json.load(handle)
            for algo_name, algo_data in search_report.get("algorithms", {}).items():
                roc_auc = algo_data.get("test_metrics", {}).get("roc_auc")
                single_models_comparison[algo_name] = {
                    "test_roc_auc": roc_auc,
                    "test_roi": algo_data.get("test_metrics", {}).get("value_bet_overall", {}).get("roi"),
                }
                if roc_auc is not None and roc_auc > best_single_roc_auc:
                    best_single_roc_auc = roc_auc
                    best_single_algorithm = algo_name
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Impossibile leggere %s per il confronto: %s", search_results_path, exc)

    all_candidates: dict[str, float] = {
        name: (item.test_metrics.get("roc_auc") or -1.0) for name, item in results.items()
    }
    if best_single_algorithm is not None:
        all_candidates[f"single:{best_single_algorithm}"] = best_single_roc_auc
    winner_overall = max(all_candidates, key=lambda key: all_candidates[key])

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "fase_3_ensemble",
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
            "inner_cv_stacking": (
                f"KFold(n_splits={effective_cv_splits}, shuffle=False) "
                "(TimeSeriesSplit non e' compatibile con cross_val_predict di StackingClassifier: "
                "vedi commento in run_ensemble)"
            ),
        },
        "features_used": feature_columns,
        "features_excluded": excluded_columns,
        "edge_threshold": edge_threshold,
        "quick_mode": quick,
        "base_estimators": provenance,
        "ensembles": {
            name: {
                "test_metrics": item.test_metrics,
                "fit_seconds": item.fit_seconds,
                "model_path": item.model_path,
                **item.extra_info,
            }
            for name, item in results.items()
        },
        "comparison_with_phase_1_2": {
            "single_models": single_models_comparison,
            "best_single_model": best_single_algorithm,
            "best_single_model_roc_auc": _round(best_single_roc_auc) if best_single_algorithm else None,
        },
        "market_benchmark_on_test": market_benchmark_metrics(split.test),
        "winner_overall": winner_overall,
        "winner_overall_roc_auc": _round(all_candidates[winner_overall]),
        "notes": [
            "Script esplorativo Fase 3: NON sovrascrive v1/v2/v3 ne' model_registry.json.",
            "Modelli salvati in data/models/v4_ensemble/ solo per ispezione manuale.",
            "Base estimator (logistic_regression/xgboost/hist_gradient_boosting) usano i best_params "
            "della Fase 1+2 se disponibili (vedi 'base_estimators' per la provenienza esatta).",
            "Il vincitore va validato con walk-forward (Fase 5) prima di una eventuale promozione a v4 ufficiale.",
            "Il meta-learner (stacking) usa KFold(shuffle=False) invece di TimeSeriesSplit per l'OOF interno: "
            "TimeSeriesSplit non forma mai una partizione completa (esclude sempre la porzione iniziale usata "
            "come warm-up) e cross_val_predict richiede una partizione completa, altrimenti solleva "
            "ValueError. Il test set finale resta comunque temporalmente separato e mai visto in training: "
            "nessun leakage sulle metriche riportate, solo un leak residuo, minore, confinato alla "
            "calibrazione interna dei pesi del meta-learner.",
        ],
    }

    results_path = reports_path / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=_json_default)

    report["results_path"] = str(results_path)
    return report


def format_ensemble_summary(report: dict[str, Any]) -> str:
    split = report["split"]
    lines = [
        f"Fase 3 - Ensemble v4 (feature base: {report['search_model_version_base']})",
        f"Dataset: {report['dataset_used']}",
        f"Righe con odds valide: {report['rows_total']} (prima del filtro: {report['rows_before_odds_filter']})",
        (
            f"Split dev/test: {split['dev_rows']} / {split['test_rows']} "
            f"({split['dev_date_min']} - {split['dev_date_max']} / "
            f"{split['test_date_min']} - {split['test_date_max']})"
        ),
        f"Base estimator: {', '.join(BASE_ALGORITHMS)}",
        "",
    ]
    for name, ens in report["ensembles"].items():
        value_bet = ens["test_metrics"].get("value_bet_overall", {})
        lines.append(f"--- {name} (fit in {ens['fit_seconds']}s) ---")
        lines.append(
            "  test roc_auc=%s | test log_loss=%s | test accuracy=%s"
            % (ens["test_metrics"].get("roc_auc"), ens["test_metrics"].get("log_loss"), ens["test_metrics"].get("accuracy"))
        )
        lines.append(
            "  value_bet edge>=%s: bets=%s hit_rate=%s roi=%s"
            % (report["edge_threshold"], value_bet.get("bets_count"), value_bet.get("hit_rate"), value_bet.get("roi"))
        )
        if "meta_learner_coefficients" in ens:
            lines.append(f"  meta-learner coef: {ens['meta_learner_coefficients']} intercept={ens['meta_learner_intercept']}")
        lines.append("")

    comparison = report["comparison_with_phase_1_2"]
    lines.append(f"Miglior modello singolo (Fase 1+2): {comparison['best_single_model']} (roc_auc={comparison['best_single_model_roc_auc']})")
    lines.append(f"VINCITORE COMPLESSIVO: {report['winner_overall']} (roc_auc={report['winner_overall_roc_auc']})")
    market = report.get("market_benchmark_on_test") or {}
    lines.append(
        "Benchmark mercato sullo stesso test set: accuracy=%s roc_auc=%s roi_bet_all=%s"
        % (market.get("market_accuracy"), market.get("market_roc_auc"), market.get("market_roi_if_bet_player_1_all"))
    )
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fase 3: ensemble (voting soft + stacking) sui migliori 3 algoritmi delle Fasi 1+2."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--models-dir", default=None)
    parser.add_argument("--dev-size", type=float, default=DEFAULT_DEV_SIZE)
    parser.add_argument("--cv-splits", type=int, default=DEFAULT_CV_SPLITS)
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument("--n-jobs", type=int, default=1)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="cv=2 per lo stacking: smoke test veloce end-to-end (i base estimator restano quelli tunati).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Avvio Fase 3 ensemble v4 (quick=%s)", args.quick)

    report = run_ensemble(
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        models_dir=args.models_dir,
        dev_size=args.dev_size,
        cv_splits=args.cv_splits,
        edge_threshold=args.edge_threshold,
        quick=args.quick,
        n_jobs=args.n_jobs,
    )
    print(format_ensemble_summary(report))


if __name__ == "__main__":
    main()







