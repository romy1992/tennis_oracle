"""Esperimento esplorativo — impatto delle feature di dominanza al servizio
("serve stats") sul feature-set v3/v4.

Verifica se aggiungere le medie storiche di dominanza al servizio per giocatore
(``app.ml.datasets.serve_stats_features``: ``serve_pts_won_pct``, ``bp_saved_pct``,
``ace_rate``, media sulle ultime 10 partite, per-giocatore e diff) al feature-set
v3 (Elo/rank/form/H2H + odds) migliora le metriche di walk-forward rispetto al
feature-set v3 originale, sia per i due modelli ufficiali (``logistic_regression``,
``random_forest``) sia per i due ensemble gia' confrontati in Fase 3
(``voting_soft``, vincitore ufficiale Fase 3/5, e ``stacking``, scartato allora
per ROI nettamente peggiore a parita' di ROC AUC — ri-testato qui per vedere se
le nuove feature cambiano quel confronto).

Riusa integralmente l'infrastruttura di ``walk_forward.py`` per generazione fold,
controlli anti-leakage temporale e metriche (``generate_walk_forward_folds``,
``slice_fold_frames``, ``detect_leakage_flags``, ``classification_metrics``,
``market_benchmark_metrics``, i benchmark ufficiali mercato/ATP/Elo). NON può
riusare cosi' come sono ``evaluate_fold_models``/``run_walk_forward_for_version``
per il ramo "con serve stats": quelle funzioni fissano il feature-set tramite
``train_baseline.selected_feature_columns`` (lista hardcoded per versione), mentre
qui il feature-set e' esteso con le nuove colonne. ``evaluate_fold_models_experiment``
qui sotto e' quindi una copia adattata di ``walk_forward.evaluate_fold_models``: la
SOLA differenza e' la selezione feature; non e' stato necessario ne' opportuno
modificare ``train_baseline.py``, che usa deliberatamente liste fisse e hardcoded
(``ALLOWED_FEATURE_COLUMNS_V3``) per garantire la riproducibilita' dei modelli in
produzione (v1-v4).

Per il confronto "senza serve stats" riusa invece ``run_walk_forward_for_version``
originale, NON modificato, sugli stessi fold/config (stesso dataset prima
dell'arricchimento): nessun rischio di alterare il comportamento del walk-forward
ufficiale.

E' uno script **esplorativo**: NON tocca ``train_baseline.py``, ``walk_forward.py``,
``model_registry.json``/``model_comparison.json``, ``walk_forward_latest.json`` ne'
il modello pubblico. Produce un report dedicato:
``data/reports/v4_serve_stats_experiment_results.json``.

Uso (da repo root)::

    python -m backend.src.app.ml.training.train_v4_serve_stats_experiment --quick
    python -m backend.src.app.ml.training.train_v4_serve_stats_experiment
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from backend.src.app.ml.datasets.serve_stats_features import (  # noqa: E402
    DEFAULT_WINDOW,
    EXTRA_FEATURE_COLUMNS,
    add_serve_stat_features,
)
from backend.src.app.ml.model_versioning import (  # noqa: E402
    ATP_DATA_DIR,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
)
from backend.src.app.ml.training.train_baseline import (  # noqa: E402
    ALLOWED_FEATURE_COLUMNS_V3,
    TARGET_COLUMN,
    build_preprocessor,
    classification_metrics,
    leakage_excluded_columns,
    market_benchmark_metrics,
    select_training_dataset,
)
from backend.src.app.ml.training.train_v4_ensemble import (  # noqa: E402
    BASE_ALGORITHMS,
    build_base_estimators,
)
from backend.src.app.ml.training.train_v4_walk_forward import (  # noqa: E402
    _aggregate_value_bet_across_folds,
)
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD  # noqa: E402
from backend.src.app.ml.training.walk_forward import (  # noqa: E402
    MODEL_NAMES,
    OFFICIAL_BENCHMARK_NAMES,
    WalkForwardConfig,
    WalkForwardFoldOutcome,
    WalkForwardFoldSpec,
    _aggregate_official_benchmarks,
    _date_max,
    _date_min,
    _estimators as _default_estimators,
    _evaluate_official_contenders,
    _fold_test_overlaps,
    _mean_metrics,
    _official_probability_inputs,
    detect_leakage_flags,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    run_walk_forward_for_version,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

# L'ensemble e le feature di mercato sono definiti solo per v3 (odds-aware):
# non ha senso testare le serve stats su v1/v2.
SEARCH_MODEL_VERSION = "v3"
ENSEMBLE_MODEL_NAME = "voting_ensemble_v4"
# Secondo ensemble gia' valutato (senza serve-stats) in Fase 3 (v4_ensemble_results.json):
# scartato allora per ROI nettamente peggiore del voting_soft (-4.99% vs -2.49%) a
# parita' di ROC AUC (0.789453 vs 0.789457). Ri-testato qui con le nuove feature per
# completezza: stesso principio anti-leakage per l'OOF interno del meta-learner
# documentato in train_v4_ensemble.run_ensemble (KFold non mescolato, NON TimeSeriesSplit).
STACKING_MODEL_NAME = "stacking_ensemble_v4"
STACKING_CV_SPLITS = 3
EXPERIMENT_MODEL_NAMES = (*MODEL_NAMES, ENSEMBLE_MODEL_NAME, STACKING_MODEL_NAME)
RESULTS_FILENAME = "v4_serve_stats_experiment_results.json"
OFFICIAL_V4_WALK_FORWARD_FILENAME = "v4_walk_forward_results.json"

# Feature-set esteso: SOLO definito in questo modulo esplorativo, non tocca
# ALLOWED_FEATURE_COLUMNS_V3 in train_baseline.py.
ALLOWED_FEATURE_COLUMNS_SERVE_STATS = [*ALLOWED_FEATURE_COLUMNS_V3, *EXTRA_FEATURE_COLUMNS]

# Stesse finestre ridotte usate da train_v4_walk_forward.py per uno smoke-test veloce.
QUICK_CONFIG_OVERRIDES: dict[str, Any] = {
    "initial_train_days": 60,
    "test_days": 30,
    "step_days": 30,
    "min_train_rows": 20,
    "min_test_rows": 10,
}


def selected_feature_columns_experiment(dataframe: pd.DataFrame) -> list[str]:
    """Come ``train_baseline.selected_feature_columns(df, model_version="v3")``
    ma con in piu' le feature di dominanza al servizio (``EXTRA_FEATURE_COLUMNS``).
    Riusa ``leakage_excluded_columns("v3")`` (pubblica, non duplicata) per restare
    coerente con le regole anti-leakage ufficiali."""
    excluded = leakage_excluded_columns(SEARCH_MODEL_VERSION)
    return [
        column
        for column in ALLOWED_FEATURE_COLUMNS_SERVE_STATS
        if column in dataframe.columns and column not in excluded
    ]


def excluded_feature_columns_experiment(
    dataframe: pd.DataFrame, selected_features: list[str]
) -> list[str]:
    allowed = set(ALLOWED_FEATURE_COLUMNS_SERVE_STATS)
    selected = set(selected_features)
    excluded = leakage_excluded_columns(SEARCH_MODEL_VERSION)
    return [
        column
        for column in dataframe.columns
        if column not in selected and (column in excluded or column not in allowed)
    ]


def make_experiment_estimators_factory(
    reports_dir: str | Path,
) -> Callable[[int], dict[str, Any]]:
    """estimators_factory con ``logistic_regression`` + ``random_forest`` (stessi
    iperparametri di default del walk-forward ufficiale) PIU' i due ensemble gia'
    confrontati in Fase 3 (``build_base_estimators``, stessi best_params tunati):
    ``voting_soft`` (vincitore ufficiale Fase 3/5) e ``stacking`` (scartato allora
    per ROI nettamente peggiore a parita' di ROC AUC — vedi commento sopra
    ``STACKING_MODEL_NAME``). Cosi' l'esperimento copre 2 modelli ufficiali + 2
    ensemble con le feature estese, in un solo giro di fold."""

    def factory(random_state: int) -> dict[str, Any]:
        from sklearn.ensemble import StackingClassifier, VotingClassifier
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import KFold

        estimators = _default_estimators(random_state)

        voting_base, _provenance = build_base_estimators(reports_dir)
        estimators[ENSEMBLE_MODEL_NAME] = VotingClassifier(
            estimators=list(voting_base), voting="soft", n_jobs=1
        )

        # Basi INDIPENDENTI (nuove istanze) per lo stacking: build_base_estimators
        # ne crea di nuove ad ogni chiamata, nessuna condivisione di stato col voting.
        stacking_base, _provenance_stacking = build_base_estimators(reports_dir)
        # Stesso motivo documentato in train_v4_ensemble.run_ensemble: TimeSeriesSplit
        # non e' una partizione completa (richiesta da cross_val_predict), quindi si usa
        # KFold non mescolato solo per l'OOF interno del meta-learner (leak residuo
        # confinato li', non intacca mai il test set del fold walk-forward).
        estimators[STACKING_MODEL_NAME] = StackingClassifier(
            estimators=list(stacking_base),
            final_estimator=LogisticRegression(max_iter=2000),
            cv=KFold(n_splits=STACKING_CV_SPLITS, shuffle=False),
            stack_method="predict_proba",
            n_jobs=1,
            passthrough=False,
        )
        return estimators

    return factory


def evaluate_fold_models_experiment(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    dataset_path: str,
    fold: WalkForwardFoldSpec,
    config: WalkForwardConfig,
    model_names: tuple[str, ...],
    estimators_factory: Callable[[int], dict[str, Any]],
) -> list[WalkForwardFoldOutcome]:
    """Copia adattata di ``walk_forward.evaluate_fold_models``: la SOLA differenza
    e' la selezione feature (``selected_feature_columns_experiment`` invece di
    ``selected_feature_columns(model_version=...)`` con liste fisse per versione).
    Skip/leakage/training/benchmark ufficiali restano identici, per un confronto
    onesto con il walk-forward ufficiale."""
    from sklearn.pipeline import Pipeline

    feature_columns = selected_feature_columns_experiment(train)
    leakage_flags = detect_leakage_flags(
        feature_columns,
        fold,
        model_version=SEARCH_MODEL_VERSION,
        train=train,
        test=test,
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

    outcomes: list[WalkForwardFoldOutcome] = []
    if len(train) < config.min_train_rows or len(test) < config.min_test_rows:
        reason = (
            f"Dati insufficienti: train={len(train)} (min {config.min_train_rows}), "
            f"test={len(test)} (min {config.min_test_rows})."
        )
        for model_name in model_names:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=reason,
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        return outcomes

    if not feature_columns:
        for model_name in model_names:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=[],
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason="Nessuna feature pre-match disponibile.",
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        return outcomes

    y_train = train[TARGET_COLUMN].astype(int)
    y_test = test[TARGET_COLUMN].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        reason = "Classe singola nel train o nel test: metriche ufficiali non calcolabili."
        for model_name in model_names:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_single_class",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=reason,
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        return outcomes

    x_train = train[feature_columns]
    x_test = test[feature_columns]
    market = market_benchmark_metrics(test)
    estimators = estimators_factory(config.random_state)
    trained_probabilities: dict[str, pd.Series] = {}

    for model_name in model_names:
        if model_name not in estimators:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="error",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=f"Modello sconosciuto: {model_name}",
                    leakage_flags=leakage_flags,
                    coverage=coverage,
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
            probabilities = pipeline.predict_proba(x_test)[:, 1]
            trained_probabilities[model_name] = pd.Series(probabilities, index=test.index)
            predictions = (probabilities >= 0.5).astype(int)
            metrics = classification_metrics(
                y_train,
                y_test,
                predictions,
                probabilities,
                test,
                edge_threshold=config.edge_threshold,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="completed",
                    train_rows=len(train),
                    test_rows=len(test),
                    metrics=metrics,
                    market_benchmark=market,
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )
        except Exception as exc:  # noqa: BLE001 — fold isolation
            logger.exception(
                "Serve-stats experiment fold=%s model=%s failed: %s",
                fold.fold_index,
                model_name,
                exc,
            )
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=model_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="error",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason=str(exc),
                    leakage_flags=leakage_flags,
                    coverage=coverage,
                )
            )

    official_probabilities = _official_probability_inputs(test, trained_probabilities)
    contenders = tuple(dict.fromkeys((*OFFICIAL_BENCHMARK_NAMES, *model_names)))
    official_metrics, sample_meta = _evaluate_official_contenders(
        test,
        probabilities_by_name=official_probabilities,
        contenders=contenders,
    )

    for outcome in outcomes:
        if outcome.status != "completed":
            continue
        model_official = official_metrics.get(outcome.model_name)
        if model_official is not None:
            outcome.metrics = {**(outcome.metrics or {}), "official_benchmark": model_official}
        outcome_coverage = dict(outcome.coverage)
        outcome_coverage["official_benchmark_sample"] = sample_meta
        outcome.coverage = outcome_coverage

    completed_reference = next((item for item in outcomes if item.status == "completed"), None)
    for benchmark_name in OFFICIAL_BENCHMARK_NAMES:
        benchmark_metrics = official_metrics.get(benchmark_name)
        if completed_reference is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=benchmark_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason="Nessun modello ML completato nel fold.",
                    leakage_flags=leakage_flags,
                    coverage={**coverage, "official_benchmark_sample": sample_meta},
                )
            )
            continue
        if benchmark_metrics is None:
            outcomes.append(
                WalkForwardFoldOutcome(
                    fold=fold,
                    model_version=SEARCH_MODEL_VERSION,
                    model_name=benchmark_name,
                    dataset_path=dataset_path,
                    feature_set=feature_columns,
                    status="skipped_insufficient_data",
                    train_rows=len(train),
                    test_rows=len(test),
                    skip_reason="Campione comune insufficiente per benchmark ufficiali.",
                    leakage_flags=leakage_flags,
                    coverage={**coverage, "official_benchmark_sample": sample_meta},
                )
            )
            continue
        outcomes.append(
            WalkForwardFoldOutcome(
                fold=fold,
                model_version=SEARCH_MODEL_VERSION,
                model_name=benchmark_name,
                dataset_path=dataset_path,
                feature_set=feature_columns,
                status="completed",
                train_rows=len(train),
                test_rows=len(test),
                metrics={"official_benchmark": benchmark_metrics},
                market_benchmark=market if benchmark_name.startswith("market_") else None,
                leakage_flags=leakage_flags,
                coverage={**coverage, "official_benchmark_sample": sample_meta},
            )
        )

    return outcomes


def _load_official_v4_walk_forward_comparison(reports_dir: str | Path) -> dict[str, Any] | None:
    """Estratto in sola lettura dell'ultimo report Fase 5 ufficiale (ensemble v4
    SENZA serve stats, ``train_v4_walk_forward.py``), per confrontare lo stesso
    ensemble con/senza le nuove feature. Non e' una nuova esecuzione."""
    path = Path(reports_dir) / OFFICIAL_V4_WALK_FORWARD_FILENAME
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return {
            "source": str(path),
            "generated_at": payload.get("generated_at"),
            "aggregate_metrics": payload.get("aggregate_metrics"),
            "value_bet_aggregate_across_folds": payload.get("value_bet_aggregate_across_folds"),
            "coverage": payload.get("coverage"),
        }
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Impossibile leggere %s per il confronto: %s", path, exc)
        return None


def run_serve_stats_experiment(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    atp_data_dir: str | Path = ATP_DATA_DIR,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    window: int = DEFAULT_WINDOW,
    quick: bool = False,
) -> dict[str, Any]:
    config_kwargs: dict[str, Any] = {"edge_threshold": edge_threshold}
    if quick:
        config_kwargs.update(QUICK_CONFIG_OVERRIDES)
    config = WalkForwardConfig(**config_kwargs)

    logger.info(
        "Avvio esperimento serve-stats (window=%s, quick=%s, extra_features=%s)",
        window,
        quick,
        len(EXTRA_FEATURE_COLUMNS),
    )

    dataset_path = select_training_dataset(processed_dir, model_version=SEARCH_MODEL_VERSION)
    raw = pd.read_csv(dataset_path, low_memory=False)
    dataframe = prepare_temporal_dataframe(raw, model_version=SEARCH_MODEL_VERSION)
    dataframe = add_serve_stat_features(dataframe, atp_data_dir, window=window)

    folds = generate_walk_forward_folds(dataframe, config)
    feature_set = selected_feature_columns_experiment(dataframe)

    estimators_factory = make_experiment_estimators_factory(reports_dir)
    outcomes: list[WalkForwardFoldOutcome] = []
    leakage_flags = list(_fold_test_overlaps(folds))
    if not folds:
        leakage_flags.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        outcomes.extend(
            evaluate_fold_models_experiment(
                train,
                test,
                dataset_path=str(dataset_path),
                fold=fold,
                config=config,
                model_names=EXPERIMENT_MODEL_NAMES,
                estimators_factory=estimators_factory,
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

    coverage = {
        "folds_planned": len(folds),
        "fold_outcomes": len(outcomes),
        "completed": len(completed),
        "skipped": len(skipped),
        "errors": len(errors),
        "dataset_rows_after_filters": int(len(dataframe)),
        "features_excluded_sample": excluded_feature_columns_experiment(dataframe, feature_set)[:40],
        "serve_stats_features_present_in_final_set": [
            column for column in EXTRA_FEATURE_COLUMNS if column in feature_set
        ],
        "serve_stats_features_missing": [
            column for column in EXTRA_FEATURE_COLUMNS if column not in feature_set
        ],
    }

    aggregate_metrics = _mean_metrics(completed)
    aggregate_metrics["official_benchmarks"] = _aggregate_official_benchmarks(completed)

    fold_dicts = [outcome.to_dict() for outcome in outcomes]
    value_bet_aggregate = {
        model_name: _aggregate_value_bet_across_folds(fold_dicts, model_name)
        for model_name in EXPERIMENT_MODEL_NAMES
    }

    # Baseline v3 SENZA serve stats, stessa config/edge_threshold, per confronto
    # diretto: riusa run_walk_forward_for_version originale, NON modificato.
    baseline_result = run_walk_forward_for_version(
        SEARCH_MODEL_VERSION,
        config,
        processed_dir=processed_dir,
        reports_dir=reports_dir,
        model_names=MODEL_NAMES,
    )
    historical_ensemble_comparison = _load_official_v4_walk_forward_comparison(reports_dir)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "serve_stats_feature_experiment",
        "model_version_base": SEARCH_MODEL_VERSION,
        "base_algorithms_ensemble": BASE_ALGORITHMS,
        "extra_feature_columns": EXTRA_FEATURE_COLUMNS,
        "window": window,
        "quick_mode": quick,
        "config": {
            "mode": config.mode,
            "initial_train_days": config.initial_train_days,
            "test_days": config.test_days,
            "step_days": config.step_days,
            "min_train_rows": config.min_train_rows,
            "min_test_rows": config.min_test_rows,
            "embargo_days": config.embargo_days,
            "edge_threshold": config.edge_threshold,
            "random_state": config.random_state,
        },
        "dataset_path": str(dataset_path),
        "dataset_rows": int(len(dataframe)),
        "date_min": _date_min(dataframe),
        "date_max": _date_max(dataframe),
        "feature_set_full": feature_set,
        "feature_set_count": len(feature_set),
        "coverage": coverage,
        "leakage_flags": unique_leakage,
        "aggregate_metrics": aggregate_metrics,
        "value_bet_aggregate_across_folds": value_bet_aggregate,
        "baseline_v3_no_serve_stats": {
            "note": (
                "Stesso walk-forward ufficiale (walk_forward.run_walk_forward_for_version, "
                "NON modificato) su v3 senza le feature di servizio, stessa config/edge_threshold: "
                "confronto diretto per isolare l'effetto delle nuove feature su logistic_regression "
                "e random_forest."
            ),
            "aggregate_metrics": baseline_result.aggregate_metrics,
            "coverage": baseline_result.coverage,
            "dataset_rows": baseline_result.dataset_rows,
        },
        "historical_v4_ensemble_walk_forward_no_serve_stats": historical_ensemble_comparison,
        "folds": fold_dicts,
        "notes": [
            "Script esplorativo: NON tocca train_baseline.py, walk_forward.py, model_registry.json, "
            "model_comparison.json, walk_forward_latest.json ne' il modello pubblico. Report dedicato "
            "separato.",
            "evaluate_fold_models_experiment() e' una copia adattata di walk_forward.evaluate_fold_models: "
            "l'unica differenza e' la selezione feature (feature-set v3 + serve stats invece della "
            "lista fissa per versione), per non dover modificare train_baseline.py.",
            f"Feature aggiuntive testate ({len(EXTRA_FEATURE_COLUMNS)}): {EXTRA_FEATURE_COLUMNS}.",
            "Confronta 4 modelli con le feature estese: logistic_regression, random_forest (stessi "
            "iperparametri di default del walk-forward ufficiale), l'ensemble vincitore Fase 3/5 "
            "(voting_soft, stessi best_params tunati) e lo stacking (secondo ensemble gia' valutato "
            "in Fase 3 senza serve-stats: ROC AUC quasi identico al voting_soft ma ROI nettamente "
            "peggiore, -4.99% vs -2.49%, per questo scartato allora — ri-testato qui per vedere se le "
            "nuove feature cambiano quel confronto) per vedere se le nuove feature migliorano anche i "
            "modelli attualmente migliori, non solo i due modelli base.",
            "'baseline_v3_no_serve_stats' esegue lo stesso identico walk-forward ufficiale (fold "
            "leggermente diversi possono derivare solo se il dataset grezzo v3 e' cambiato nel "
            "frattempo) per un confronto onesto su logistic_regression/random_forest.",
            "'historical_v4_ensemble_walk_forward_no_serve_stats' e' un estratto in sola lettura "
            "dell'ultimo report Fase 5 (train_v4_walk_forward.py, ensemble SENZA serve stats): non "
            "e' una nuova esecuzione, i fold possono differire leggermente se la config e' cambiata.",
        ],
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    results_path = reports_path / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def format_experiment_summary(report: dict[str, Any]) -> str:
    lines = [
        "Esperimento serve-stats (esplorativo) — dominanza al servizio su v3/v4",
        f"Dataset: {report['dataset_path']}",
        f"  {report['dataset_rows']} righe ({report['date_min']} - {report['date_max']})",
        (
            f"Feature totali usate: {report['feature_set_count']} "
            f"(extra serve-stats: {len(report['extra_feature_columns'])})"
        ),
        (
            f"Config: mode={report['config']['mode']} initial_train_days={report['config']['initial_train_days']} "
            f"test_days={report['config']['test_days']} step_days={report['config']['step_days']}"
        ),
        (
            f"Fold: pianificati={report['coverage'].get('folds_planned')} "
            f"completati={report['coverage'].get('completed')} "
            f"skipped={report['coverage'].get('skipped')} errors={report['coverage'].get('errors')}"
        ),
        "",
    ]

    for model_name in EXPERIMENT_MODEL_NAMES:
        agg = report["aggregate_metrics"].get(model_name, {})
        lines.append(f"--- {model_name} (CON serve-stats, media sui fold completati) ---")
        for key in ("roc_auc", "log_loss", "accuracy", "f1"):
            stat = agg.get(key, {})
            lines.append(f"  {key}: mean={stat.get('mean')} std={stat.get('std')} n={stat.get('n')}")
        value_bet_agg = report["value_bet_aggregate_across_folds"].get(model_name, {})
        lines.append(
            "  value-bet ROI: roi_per_fold "
            f"mean={value_bet_agg.get('roi_per_fold_stats', {}).get('mean')} "
            f"cumulativo={value_bet_agg.get('cumulative_roi_all_folds')} "
            f"(bets={value_bet_agg.get('total_bets_all_folds')})"
        )

    lines.append("")
    lines.append("--- Confronto: v3 SENZA serve-stats (stesso walk-forward ufficiale) ---")
    baseline_agg = report.get("baseline_v3_no_serve_stats", {}).get("aggregate_metrics", {})
    for model_name in ("logistic_regression", "random_forest"):
        agg = baseline_agg.get(model_name, {})
        roc = agg.get("roc_auc", {})
        lines.append(f"  {model_name}: roc_auc mean={roc.get('mean')} n={roc.get('n')}")

    historical = report.get("historical_v4_ensemble_walk_forward_no_serve_stats")
    if historical:
        lines.append("")
        lines.append(f"Ensemble v4 SENZA serve-stats (Fase 5, {historical.get('source')}):")
        ensemble_agg_hist = (historical.get("aggregate_metrics") or {}).get(ENSEMBLE_MODEL_NAME, {})
        roc_hist = ensemble_agg_hist.get("roc_auc", {})
        lines.append(f"  {ENSEMBLE_MODEL_NAME}: roc_auc mean={roc_hist.get('mean')} n={roc_hist.get('n')}")
    else:
        lines.append("")
        lines.append("Nessun walk-forward ufficiale Fase 5 (ensemble) trovato per il confronto.")

    lines.append("")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Esperimento esplorativo: feature di dominanza al servizio su v3/v4."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--atp-data-dir", default=str(ATP_DATA_DIR))
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Finestre piu' corte (smoke test): initial_train_days/test_days/step_days ridotti.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Avvio esperimento serve-stats (quick=%s, window=%s)", args.quick, args.window)

    report = run_serve_stats_experiment(
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        atp_data_dir=args.atp_data_dir,
        edge_threshold=args.edge_threshold,
        window=args.window,
        quick=args.quick,
    )
    print(format_experiment_summary(report))


if __name__ == "__main__":
    main()





