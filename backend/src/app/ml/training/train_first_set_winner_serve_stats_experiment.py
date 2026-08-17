"""Esperimento esplorativo: feature di dominanza al servizio (serve stats,
gia' prototipate in ``app.ml.datasets.serve_stats_features`` per il match
winner) applicate al target ``target_first_set_winner``.

Domanda: il benchmark ``market_no_vig`` (quota di mercato del vincitore
MATCH usata come proxy) batte i modelli ML dedicati nella prima validazione
(``train_first_set_winner.py``, vedi ``first_set_winner_walk_forward_results.json``).
Le feature di dominanza al servizio (``serve_pts_won_pct``, ``bp_saved_pct``,
``ace_rate``, medie storiche per giocatore) sono un candidato naturale per
questo target specifico: chi domina di piu' al servizio ha, intuitivamente,
un vantaggio proprio nel PRIMO set (prima che l'avversario "legga" il servizio).

Riusa integralmente ``evaluate_fold_models_first_set`` (stessa infrastruttura
fold/leakage/metriche) tramite il suo parametro ``feature_columns_override``,
per non duplicare la logica. Script esplorativo: NON tocca
``train_first_set_winner.py`` ne' il suo report ufficiale. Report dedicato:
``data/reports/first_set_winner_serve_stats_experiment_results.json``.

Uso (da repo root, richiede DB)::

    python -m backend.src.app.ml.training.train_first_set_winner_serve_stats_experiment
    python -m backend.src.app.ml.training.train_first_set_winner_serve_stats_experiment --quick
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.src.app.ml.datasets.serve_stats_features import (
    DEFAULT_WINDOW,
    EXTRA_FEATURE_COLUMNS,
    add_serve_stat_features,
)
from backend.src.app.ml.model_versioning import ATP_DATA_DIR, PROCESSED_DATA_DIR, REPORTS_DIR
from backend.src.app.ml.training.train_baseline import ALLOWED_FEATURE_COLUMNS_V3, leakage_excluded_columns
from backend.src.app.ml.training.train_first_set_winner import (
    FIRST_SET_BENCHMARK_NAMES,
    FIRST_SET_MODEL_NAMES,
    QUICK_CONFIG_OVERRIDES,
    RESULTS_FILENAME as BASELINE_RESULTS_FILENAME,
    build_first_set_winner_dataframe,
    evaluate_fold_models_first_set,
)
from backend.src.app.ml.training.walk_forward import (
    WalkForwardConfig,
    WalkForwardFoldOutcome,
    _date_max,
    _date_min,
    _fold_test_overlaps,
    _mean_metrics,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

FIRST_SET_TARGET_COLUMN = "target_first_set_winner"
ALLOWED_FEATURE_COLUMNS_SERVE_STATS = [*ALLOWED_FEATURE_COLUMNS_V3, *EXTRA_FEATURE_COLUMNS]
RESULTS_FILENAME = "first_set_winner_serve_stats_experiment_results.json"


def selected_feature_columns_experiment(dataframe) -> list[str]:
    excluded = leakage_excluded_columns("v3")
    return [
        column
        for column in ALLOWED_FEATURE_COLUMNS_SERVE_STATS
        if column in dataframe.columns and column not in excluded
    ]


def _load_baseline_comparison(reports_dir: str | Path) -> dict[str, Any] | None:
    """Estratto in sola lettura dell'ultimo report ufficiale SENZA serve stats
    (``train_first_set_winner.py``), per confronto diretto. Non e' una nuova
    esecuzione."""
    path = Path(reports_dir) / BASELINE_RESULTS_FILENAME
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return {
            "source": str(path),
            "generated_at": payload.get("generated_at"),
            "aggregate_metrics": payload.get("aggregate_metrics"),
            "coverage": payload.get("coverage"),
        }
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Impossibile leggere %s per il confronto: %s", path, exc)
        return None


def run_serve_stats_experiment(
    db,
    *,
    config: WalkForwardConfig | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    atp_data_dir: str | Path = ATP_DATA_DIR,
    window: int = DEFAULT_WINDOW,
) -> dict[str, Any]:
    resolved_config = config or WalkForwardConfig()
    resolved_config.validate()

    merged, dataset_path = build_first_set_winner_dataframe(db, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=FIRST_SET_TARGET_COLUMN, model_version="v3",
    )
    dataframe = add_serve_stat_features(dataframe, atp_data_dir, window=window)

    folds = generate_walk_forward_folds(dataframe, resolved_config)
    feature_set = selected_feature_columns_experiment(dataframe)
    outcomes: list[WalkForwardFoldOutcome] = []
    leakage_flags = list(_fold_test_overlaps(folds))
    if not folds:
        leakage_flags.append("no_folds_generated_insufficient_date_span")

    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        fold_features = selected_feature_columns_experiment(train)
        outcomes.extend(
            evaluate_fold_models_first_set(
                train, test, dataset_path=str(dataset_path), fold=fold, config=resolved_config,
                feature_columns_override=fold_features,
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
    baseline_comparison = _load_baseline_comparison(reports_dir)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "first_set_winner_serve_stats_experiment",
        "target_column": FIRST_SET_TARGET_COLUMN,
        "extra_feature_columns": EXTRA_FEATURE_COLUMNS,
        "window": window,
        "model_names": list(FIRST_SET_MODEL_NAMES),
        "benchmark_names": list(FIRST_SET_BENCHMARK_NAMES),
        "config": {
            "mode": resolved_config.mode,
            "initial_train_days": resolved_config.initial_train_days,
            "test_days": resolved_config.test_days,
            "step_days": resolved_config.step_days,
            "min_train_rows": resolved_config.min_train_rows,
            "min_test_rows": resolved_config.min_test_rows,
        },
        "dataset_path": str(dataset_path),
        "dataset_rows": int(len(dataframe)),
        "date_min": _date_min(dataframe),
        "date_max": _date_max(dataframe),
        "feature_set_full": feature_set,
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
        "baseline_no_serve_stats": baseline_comparison,
        "folds": [outcome.to_dict() for outcome in outcomes],
        "notes": [
            "Script esplorativo: NON tocca train_first_set_winner.py ne' il suo report "
            "ufficiale. Report dedicato separato.",
            f"Feature aggiuntive testate ({len(EXTRA_FEATURE_COLUMNS)}): {EXTRA_FEATURE_COLUMNS}.",
            "'baseline_no_serve_stats' e' un estratto in sola lettura dell'ultimo report "
            "ufficiale (train_first_set_winner.py, SENZA serve stats): non e' una nuova "
            "esecuzione, i fold possono differire leggermente se il dataset e' cambiato.",
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
        "Esperimento serve-stats — Vincitore 1 set",
        f"Dataset: {report['dataset_path']}",
        f"  {report['dataset_rows']} righe ({report['date_min']} - {report['date_max']})",
        f"Feature totali usate: {report['feature_set_count']} (extra serve-stats: {len(report['extra_feature_columns'])})",
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
        roc = agg.get("roc_auc", {})
        lines.append(f"--- {name} (CON serve-stats): roc_auc mean={roc.get('mean')} n={roc.get('n')} ---")

    baseline = report.get("baseline_no_serve_stats")
    lines.append("")
    if baseline:
        lines.append(f"Confronto SENZA serve-stats ({baseline.get('source')}):")
        for model_name in report["model_names"]:
            base_roc = (baseline.get("aggregate_metrics") or {}).get(model_name, {}).get("roc_auc", {})
            lines.append(f"  {model_name}: roc_auc mean={base_roc.get('mean')} n={base_roc.get('n')}")
    else:
        lines.append("Nessun report ufficiale trovato per il confronto (esegui prima train_first_set_winner.py).")

    lines.append("")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Esperimento esplorativo: serve-stats sul target Vincitore 1 set."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--atp-data-dir", default=str(ATP_DATA_DIR))
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--quick", action="store_true", help="Finestre piu' corte (smoke test).")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config_kwargs: dict[str, Any] = {}
    if args.quick:
        config_kwargs.update(QUICK_CONFIG_OVERRIDES)
    config = WalkForwardConfig(**config_kwargs)

    with SessionLocal() as db:
        report = run_serve_stats_experiment(
            db,
            config=config,
            processed_dir=args.processed_dir,
            reports_dir=args.reports_dir,
            atp_data_dir=args.atp_data_dir,
            window=args.window,
        )
    print(format_experiment_summary(report))


if __name__ == "__main__":
    main()

