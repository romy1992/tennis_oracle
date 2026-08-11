"""Estensione esplorativa ML-04: ROI/hit-rate dell'ensemble v4 per livello torneo.

Risponde alla domanda "il voting ensemble v4 (Fase 3, validato in Fase 5/5.2) batte
il mercato in QUALCHE segmento di livello torneo (Grand Slam / Masters 1000 /
ATP 500 / ATP 250 / Challenger / ITF / WTA...), anche se la media generale sui fold
walk-forward è negativa?" — invece di guardare solo l'aggregato multi-fold.

Non allena nulla di nuovo: riusa integralmente pezzi già esistenti e validati:

- ``walk_forward.generate_walk_forward_folds``/``slice_fold_frames`` per i fold
  temporali (stessa identica logica anti-leakage di Fase 5/5.2, nessuna duplicazione);
- ``train_v4_walk_forward.make_v4_voting_estimators_factory`` per ricreare, ad ogni
  fold, l'ESATTO VotingClassifier soft tunato in Fase 3 (stessi 3 algoritmi, stessi
  iperparametri letti da ``v4_grid_search_results.json``);
- ``segment_roi_analysis._records_from_oos_fold`` per costruire i record riga-per-riga
  con i campi di segmentazione già pronti (incluso ``level`` = ``atp_tourney_level``);
- ``segment_roi_analysis.analyze_segment_records`` per l'aggregazione ROI/hit-rate
  per segmento (stesso motore "ML-04" già usato per live/backtest).

Perché serve questo script e non basta ``segment_roi_analysis.collect_oos_segment_records``
già esistente: quella funzione genera le previsioni OOS tramite
``calibration.collect_oos_predictions_for_version``, che a sua volta usa
``walk_forward._estimators()`` — il dizionario FISSO dei soli modelli ufficiali
(``logistic_regression``/``random_forest``). Non accetta un ``estimators_factory``
custom (a differenza di ``run_walk_forward_for_version``, usata in Fase 5), quindi
non può generare previsioni per l'ensemble v4. Questo script colma quel solo divario,
SENZA modificare ``calibration.py``/``walk_forward.py``/``segment_roi_analysis.py``.

Questo script è **puramente esplorativo/di lettura** (estensione Fase 5/ML-04):

- NON allena/salva alcun modello in produzione;
- NON tocca ``model_registry.json``/``model_comparison.json``;
- NON tocca ``walk_forward_latest.json`` né alcun report ufficiale Fase 1-5.2;
- Produce un report JSON **nuovo e isolato**: ``data/reports/v4_segment_roi_by_level.json``.

Uso (da repo root)::

    python -m backend.src.app.ml.training.analyze_v4_segment_roi_by_level --quick   # smoke test
    python -m backend.src.app.ml.training.analyze_v4_segment_roi_by_level           # run completa
    python -m backend.src.app.ml.training.analyze_v4_segment_roi_by_level --mature  # soglia maturità alta (Fase 5.2 style)
    python -m backend.src.app.ml.training.analyze_v4_segment_roi_by_level --segment-dimension surface
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, get_args

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.model_versioning import (  # noqa: E402
    PROCESSED_DATA_DIR,
    REPORTS_DIR,
    select_training_dataset_path,
)
from backend.src.app.ml.training.train_baseline import (  # noqa: E402
    TARGET_COLUMN,
    build_preprocessor,
    selected_feature_columns,
)
from backend.src.app.ml.training.train_v4_ensemble import BASE_ALGORITHMS  # noqa: E402
from backend.src.app.ml.training.train_v4_walk_forward import (  # noqa: E402
    ENSEMBLE_MODEL_NAME,
    MATURE_CONFIG_OVERRIDES,
    QUICK_CONFIG_OVERRIDES,
    SEARCH_MODEL_VERSION,
    make_v4_voting_estimators_factory,
)
from backend.src.app.ml.training.segment_roi_analysis import (  # noqa: E402
    DEFAULT_MIN_SEGMENT_SAMPLES,
    SegmentAnalysisRecord,
    SegmentDimension,
    _records_from_oos_fold,
    analyze_segment_records,
)
from backend.src.app.ml.training.walk_forward import (  # noqa: E402
    WalkForwardConfig,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

RESULTS_FILENAME = "v4_segment_roi_by_level.json"
DEFAULT_SEGMENT_DIMENSION: SegmentDimension = "level"
VALID_SEGMENT_DIMENSIONS: tuple[str, ...] = get_args(SegmentDimension)


def collect_v4_ensemble_segment_records(
    config: WalkForwardConfig,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
) -> tuple[list[SegmentAnalysisRecord], dict[str, Any]]:
    """Rialleana l'ensemble v4 fold-per-fold (walk-forward) e ne raccoglie le
    previsioni OOS come ``SegmentAnalysisRecord`` (stessi campi di segmentazione
    già usati per live/backtest/altre versioni).

    Mirror di ``segment_roi_analysis.collect_oos_segment_records``, ma con
    l'ensemble v4 (via ``make_v4_voting_estimators_factory``) al posto dei modelli
    fissi di ``walk_forward._estimators``. Nessun modello viene salvato su disco:
    il fit avviene solo in memoria, per fold, esattamente come in Fase 5.
    """
    from sklearn.pipeline import Pipeline

    config.validate()
    dataset_path = select_training_dataset_path(processed_dir, version=SEARCH_MODEL_VERSION)  # type: ignore[arg-type]
    raw = pd.read_csv(dataset_path, low_memory=False)
    dataframe = prepare_temporal_dataframe(raw, model_version=SEARCH_MODEL_VERSION)
    folds = generate_walk_forward_folds(dataframe, config)
    estimators_factory = make_v4_voting_estimators_factory(reports_dir)

    all_records: list[SegmentAnalysisRecord] = []
    fold_coverage: list[dict[str, Any]] = []

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        entry: dict[str, Any] = {
            "fold_index": fold.fold_index,
            "test_start": fold.test_start.isoformat(),
            "test_end": fold.test_end.isoformat(),
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
        }

        if len(train) < config.min_train_rows or len(test) < config.min_test_rows:
            entry["status"] = "skipped_insufficient_data"
            fold_coverage.append(entry)
            continue

        feature_columns = selected_feature_columns(train, model_version=SEARCH_MODEL_VERSION)
        y_train = train[TARGET_COLUMN].astype(int)
        y_test = test[TARGET_COLUMN].astype(int)
        if not feature_columns or y_train.nunique() < 2 or y_test.nunique() < 2:
            entry["status"] = "skipped_single_class_or_no_features"
            fold_coverage.append(entry)
            continue

        estimators = estimators_factory(config.random_state)
        pipeline = Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(train, feature_columns)),
                ("model", estimators[ENSEMBLE_MODEL_NAME]),
            ]
        )
        pipeline.fit(train[feature_columns], y_train)
        prob_raw = pipeline.predict_proba(test[feature_columns])[:, 1]

        fold_records = _records_from_oos_fold(
            fold,
            test,
            prob_raw,
            prob_raw,  # nessuna calibrazione: probabilità raw dell'ensemble, come Fase 5.
            model_version="v4_voting_ensemble",
            model_name=ENSEMBLE_MODEL_NAME,
        )
        all_records.extend(fold_records)
        entry["status"] = "completed"
        entry["records_collected"] = len(fold_records)
        fold_coverage.append(entry)

    coverage = {
        "dataset_path": str(dataset_path),
        "dataset_rows": int(len(dataframe)),
        "folds_planned": len(folds),
        "folds_completed": sum(1 for item in fold_coverage if item["status"] == "completed"),
        "folds_skipped": sum(1 for item in fold_coverage if item["status"] != "completed"),
        "total_records": len(all_records),
        "per_fold": fold_coverage,
    }
    return all_records, coverage


def run_v4_segment_roi_analysis(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    segment_dimension: SegmentDimension = DEFAULT_SEGMENT_DIMENSION,
    min_segment_samples: int = DEFAULT_MIN_SEGMENT_SAMPLES,
    group_by_fold: bool = True,
    quick: bool = False,
    mature: bool = False,
) -> dict[str, Any]:
    if quick and mature:
        raise ValueError("--quick e --mature sono mutuamente esclusivi.")
    if segment_dimension not in VALID_SEGMENT_DIMENSIONS:
        raise ValueError(
            f"Dimensione segmento non supportata: {segment_dimension}. "
            f"Valori validi: {VALID_SEGMENT_DIMENSIONS}"
        )

    config_kwargs: dict[str, Any] = {}
    if quick:
        config_kwargs.update(QUICK_CONFIG_OVERRIDES)
    elif mature:
        config_kwargs.update(MATURE_CONFIG_OVERRIDES)
    config = WalkForwardConfig(**config_kwargs)

    logger.info(
        "Avvio analisi segmento '%s' per ensemble v4 (quick=%s, mature=%s, initial_train_days=%s)",
        segment_dimension,
        quick,
        mature,
        config.initial_train_days,
    )

    records, coverage = collect_v4_ensemble_segment_records(
        config, processed_dir=processed_dir, reports_dir=reports_dir
    )

    analysis = analyze_segment_records(
        records,
        source="walk_forward",
        segment_dimension=segment_dimension,
        min_segment_samples=min_segment_samples,
        group_by_fold=group_by_fold,
    )

    dynamic_notes: list[str] = []
    if segment_dimension == "level" and analysis.predictions_total:
        unknown_bucket = next(
            (item for item in analysis.segments if item.key == "unknown"), None
        )
        if unknown_bucket is not None and unknown_bucket.predictions_total > 0:
            unknown_pct = round(
                (unknown_bucket.predictions_total / analysis.predictions_total) * 100, 2
            )
            dynamic_notes.append(
                f"Segmento 'Sconosciuto' (level mancante) = {unknown_pct}% dei record "
                f"({unknown_bucket.predictions_total}/{analysis.predictions_total}): "
                "atp_tourney_level è NaN esattamente quando atp_match_found=0, cioè quando "
                "l'arricchimento ATP (match dei nomi giocatore/torneo con i file storici) non "
                "ha trovato corrispondenza — perlopiù partite ITF/qualifiche/tornei minori. "
                "Non è un difetto di questo script: è un limite noto di copertura del dataset v3 "
                "(circa 1/3 delle righe totali ha atp_match_found=1). I ROI per livello sono "
                "quindi calcolati solo sul sottoinsieme con match ATP trovato."
            )

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "ml04_ext_v4_segment_roi",
        "model_version": SEARCH_MODEL_VERSION,
        "ensemble_model_name": ENSEMBLE_MODEL_NAME,
        "base_algorithms": BASE_ALGORITHMS,
        "segment_dimension": segment_dimension,
        "min_segment_samples": min_segment_samples,
        "quick_mode": quick,
        "mature_mode": mature,
        "config": {
            "mode": config.mode,
            "initial_train_days": config.initial_train_days,
            "test_days": config.test_days,
            "step_days": config.step_days,
            "min_train_rows": config.min_train_rows,
            "min_test_rows": config.min_test_rows,
            "embargo_days": config.embargo_days,
            "random_state": config.random_state,
        },
        "coverage": coverage,
        "analysis": analysis.to_dict(),
        "notes": [
            "Script esplorativo (estensione ML-04): NON allena/salva modelli in produzione, "
            "NON tocca model_registry.json/model_comparison.json/walk_forward_latest.json.",
            "L'ensemble v4 è ricostruito fold-per-fold in memoria con "
            "train_v4_walk_forward.make_v4_voting_estimators_factory (stessi iperparametri "
            "tunati in Fase 1-3): nessuna nuova ricerca di iperparametri, nessun nuovo training "
            "'ufficiale'.",
            "'level' = colonna atp_tourney_level (Grand Slam=G, Masters 1000=M, ATP=A, "
            "Challenger=C, ITF/Futures=..., a seconda dei codici presenti nel dataset v3).",
            "Se un segmento ha insufficient_sample=true (< min_segment_samples bet chiuse), "
            "il suo ROI/hit-rate è statisticamente poco affidabile: da leggere come indicativo, "
            "non come conferma.",
            "Se emerge un segmento con ROI positivo e campione sufficiente, il passo successivo "
            "naturale è un modello SPECIALIZZATO su quel segmento (dataset filtrato), da validare "
            "e promuovere formalmente (Fase 6) come nuovo artefatto versionato (es. v4.1/v5) — "
            "non una modifica di questo script né del modello v4 esistente.",
            *dynamic_notes,
        ],
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    results_path = reports_path / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def format_segment_roi_summary(report: dict[str, Any]) -> str:
    analysis = report["analysis"]
    lines = [
        f"ML-04 ext - ROI ensemble v4 per '{report['segment_dimension']}'",
        f"Ensemble: {report['ensemble_model_name']} (base: {', '.join(report['base_algorithms'])})",
        (
            f"Config: initial_train_days={report['config']['initial_train_days']} "
            f"test_days={report['config']['test_days']} step_days={report['config']['step_days']}"
        ),
        (
            f"Fold: pianificati={report['coverage']['folds_planned']} "
            f"completati={report['coverage']['folds_completed']} "
            f"skipped={report['coverage']['folds_skipped']}"
        ),
        f"Record OOS totali: {analysis['predictions_total']} (chiusi={analysis['closed']}, void={analysis['void']})",
        "",
        f"--- Segmenti per '{report['segment_dimension']}' ---",
    ]
    for segment in analysis["segments"]:
        if segment["closed"] == 0:
            continue
        flag = " [CAMPIONE INSUFFICIENTE]" if segment["insufficient_sample"] else ""
        lines.append(
            f"  {segment['label']} (n={segment['closed']}): "
            f"hit_rate={segment['hit_rate_pct']}% roi={segment['roi_pct']}% "
            f"avg_odds={segment['avg_odds']} avg_edge={segment['avg_edge_pct']}%{flag}"
        )
    lines.append("")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Estensione ML-04: ROI/hit-rate dell'ensemble v4 (Fase 3) per segmento "
            "(default: livello torneo), su previsioni OOS walk-forward."
        )
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument(
        "--segment-dimension",
        default=DEFAULT_SEGMENT_DIMENSION,
        choices=VALID_SEGMENT_DIMENSIONS,
    )
    parser.add_argument("--min-segment-samples", type=int, default=DEFAULT_MIN_SEGMENT_SAMPLES)
    parser.add_argument(
        "--no-group-by-fold",
        action="store_true",
        help="Disattiva il breakdown per fold (attivo di default) nel report.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Finestre piu' corte (smoke test): initial_train_days/test_days/step_days ridotti.",
    )
    parser.add_argument(
        "--mature",
        action="store_true",
        help="initial_train_days alzato a ~3 anni (stile Fase 5.2), esclude i fold immaturi.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    report = run_v4_segment_roi_analysis(
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        segment_dimension=args.segment_dimension,
        min_segment_samples=args.min_segment_samples,
        group_by_fold=not args.no_group_by_fold,
        quick=args.quick,
        mature=args.mature,
    )
    print(format_segment_roi_summary(report))


if __name__ == "__main__":
    main()



