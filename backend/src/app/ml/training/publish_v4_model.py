"""Fase 6 — Pubblica il modello v4 ufficiale (voting ensemble) come v1/v2/v3.

Alena l'ensemble vincitore delle Fasi 1-5 (soft-voting di logistic_regression +
xgboost + hist_gradient_boosting, iperparametri tunati via grid search) sullo
**stesso split temporale standard** usato da ``train_baseline.py`` per v1/v2/v3
(``DEFAULT_TEST_SIZE=0.2``, holdout finale cronologico), cosi' le metriche in
``baseline_v4_metrics.json`` sono direttamente confrontabili con quelle di v3.

A differenza degli script esplorativi Fase 1-5 (``train_v4_search``,
``train_v4_ensemble``, ``train_v4_voting``, ``train_v4_walk_forward``, che NON
toccano mai gli artefatti pubblici), questo script **e' quello ufficiale**:
scrive esattamente negli stessi path/formati di ``train_baseline.train_baseline``:

- ``data/models/v4/voting_ensemble.pkl`` (stesso formato ``{"pipeline",
  "feature_columns", ...}`` letto da ``predictor._load_model_artifact``)
- ``data/reports/baseline_v4_metrics.json`` (stesso schema di
  ``baseline_v3_metrics.json``, chiave ``models.voting_ensemble``)
- aggiorna ``model_comparison.json`` e ``model_registry.json`` (via le stesse
  funzioni riusate da ``train_baseline.py``)

Non attiva automaticamente v4 nel registro pubblico ML-07 (serve un passo
esplicito separato: vedi ``activate_v4_public_model.py``), cosi' la
pubblicazione degli artefatti resta disaccoppiata dalla promozione in
produzione (si puo' ripubblicare/ri-validare senza cambiare cosa il bot serve).

Uso (da repo root)::

    python -m backend.src.app.ml.training.publish_v4_model
"""

from __future__ import annotations

import argparse
import logging
import pickle
import sys
from pathlib import Path
from typing import Any, Literal

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.model_versioning import (  # noqa: E402
    MODEL_VERSIONS,
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
)
from backend.src.app.ml.training.train_baseline import (  # noqa: E402
    DEFAULT_TEST_SIZE,
    TARGET_COLUMN,
    TrainingResult,
    build_preprocessor,
    classification_metrics,
    excluded_feature_columns,
    filter_rows_with_valid_odds,
    market_benchmark_metrics,
    select_training_dataset,
    selected_feature_columns,
    temporal_train_test_split,
    update_model_registry_entry,
    write_model_comparison,
)
from backend.src.app.ml.training.train_v4_ensemble import build_base_estimators  # noqa: E402
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD  # noqa: E402

logger = logging.getLogger(__name__)

MODEL_VERSION: Literal["v4"] = "v4"
MODEL_NAME = "voting_ensemble"


def publish_v4_model(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    models_dir: str | Path | None = None,
    reports_dir: str | Path = REPORTS_DIR,
    test_size: float = DEFAULT_TEST_SIZE,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    registry_path: Path | None = None,
) -> TrainingResult:
    from sklearn.ensemble import VotingClassifier
    from sklearn.pipeline import Pipeline

    version_paths = MODEL_VERSIONS[MODEL_VERSION]
    dataset_path = select_training_dataset(processed_dir, model_version=MODEL_VERSION)
    dataframe = pd.read_csv(dataset_path, low_memory=False)
    rows_before_odds_filter = len(dataframe)
    dataframe = filter_rows_with_valid_odds(dataframe)
    if dataframe.empty:
        raise ValueError("Dataset v4 (=v3) senza righe con odds valide.")

    # Stesso split standard di v1/v2/v3: holdout finale cronologico (default 20%).
    split = temporal_train_test_split(dataframe, test_size=test_size)
    feature_columns = selected_feature_columns(split.train, model_version=MODEL_VERSION)
    if not feature_columns:
        raise ValueError("Nessuna feature pre-match disponibile per la pubblicazione v4.")

    excluded_columns = excluded_feature_columns(dataframe, feature_columns, model_version=MODEL_VERSION)
    x_train = split.train[feature_columns]
    y_train = split.train[TARGET_COLUMN].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[TARGET_COLUMN].astype(int)

    resolved_models_dir = Path(models_dir) if models_dir is not None else version_paths.models_dir
    reports_path = Path(reports_dir)
    resolved_models_dir.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)

    # Stessi 3 base estimator tunati nelle Fasi 1-2, stessa combinazione vincitrice
    # (voting soft) trovata in Fase 3 e validata in Fase 5/5.2.
    base_estimators, provenance = build_base_estimators(reports_dir)
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(split.train, feature_columns)),
            ("model", VotingClassifier(estimators=list(base_estimators), voting="soft", n_jobs=1)),
        ]
    )
    pipeline.fit(x_train, y_train)
    probabilities = pipeline.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)
    model_metrics = {
        MODEL_NAME: classification_metrics(
            y_train,
            y_test,
            predictions,
            probabilities,
            split.test,
            edge_threshold=edge_threshold,
        )
    }
    model_metrics[MODEL_NAME]["base_estimators_provenance"] = provenance

    model_path = resolved_models_dir / f"{MODEL_NAME}.pkl"
    with model_path.open("wb") as model_file:
        pickle.dump(
            {
                "pipeline": pipeline,
                "feature_columns": feature_columns,
                "dataset_path": str(dataset_path),
                "model_version": MODEL_VERSION,
                "base_algorithms": [name for name, _ in base_estimators],
            },
            model_file,
        )
    model_paths = {MODEL_NAME: model_path}

    metrics_filename = version_paths.metrics_filename
    metrics: dict[str, Any] = {
        "model_version": MODEL_VERSION,
        "dataset_used": str(dataset_path),
        "rows_total": int(len(dataframe)),
        "rows_before_odds_filter": int(rows_before_odds_filter),
        "columns_total": int(len(dataframe.columns)),
        "date_min": split.train_start,
        "date_max": split.test_end,
        "split": {
            "strategy": "temporal",
            "test_size": test_size,
            "train_rows": int(len(split.train)),
            "test_rows": int(len(split.test)),
            "train_date_min": split.train_start,
            "train_date_max": split.train_end,
            "test_date_min": split.test_start,
            "test_date_max": split.test_end,
        },
        "features_used": feature_columns,
        "features_excluded": excluded_columns,
        "rank_features_note": version_paths.rank_features_note,
        "models": model_metrics,
        "market_benchmark": market_benchmark_metrics(split.test),
        "model_paths": {name: str(path) for name, path in model_paths.items()},
        "metrics_path": str(reports_path / metrics_filename),
        "odds_filter": {
            "required": True,
            "rows_removed": int(rows_before_odds_filter - len(dataframe)),
        },
    }

    metrics_path = reports_path / metrics_filename
    import json

    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        json.dump(metrics, metrics_file, indent=2, ensure_ascii=False)

    write_model_comparison(reports_path)
    update_model_registry_entry(
        MODEL_VERSION, metrics_path, dataset_path, resolved_models_dir, registry_path=registry_path
    )

    return TrainingResult(
        metrics_path=metrics_path,
        model_paths=model_paths,
        metrics=metrics,
        model_version=MODEL_VERSION,
    )


def format_publish_summary(result: TrainingResult) -> str:
    metrics = result.metrics
    model_metrics = metrics["models"][MODEL_NAME]
    lines = [
        f"Pubblicazione modello v4 ufficiale ({MODEL_NAME})",
        f"Dataset: {metrics['dataset_used']}",
        f"Righe totali (con odds valide): {metrics['rows_total']} (prima del filtro: {metrics['rows_before_odds_filter']})",
        (
            f"Split train/test: {metrics['split']['train_rows']} / {metrics['split']['test_rows']} "
            f"({metrics['split']['train_date_min']} - {metrics['split']['train_date_max']} / "
            f"{metrics['split']['test_date_min']} - {metrics['split']['test_date_max']})"
        ),
        f"Test roc_auc={model_metrics.get('roc_auc')} log_loss={model_metrics.get('log_loss')} accuracy={model_metrics.get('accuracy')}",
        f"Value-bet ROI (edge>={metrics.get('models', {}).get(MODEL_NAME, {}).get('value_bet_overall', {}).get('edge_threshold')}): "
        f"{model_metrics.get('value_bet_overall', {}).get('roi')}",
        f"Market benchmark: {metrics.get('market_benchmark')}",
        f"Modello salvato in: {result.model_paths[MODEL_NAME]}",
        f"Metriche salvate in: {result.metrics_path}",
        "",
        "Il modello NON e' ancora attivo per bot/utenti: eseguire "
        "'python -m backend.src.app.ml.training.activate_v4_public_model' per registrarlo "
        "come candidato e attivarlo nel registro pubblico ML-07.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pubblica il modello v4 ufficiale (voting ensemble) come artefatto v1/v2/v3-style."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--models-dir", default=None)
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--test-size", type=float, default=DEFAULT_TEST_SIZE)
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Avvio pubblicazione modello v4 ufficiale")

    result = publish_v4_model(
        processed_dir=args.processed_dir,
        models_dir=args.models_dir,
        reports_dir=args.reports_dir,
        test_size=args.test_size,
        edge_threshold=args.edge_threshold,
    )
    print(format_publish_summary(result))


if __name__ == "__main__":
    main()




