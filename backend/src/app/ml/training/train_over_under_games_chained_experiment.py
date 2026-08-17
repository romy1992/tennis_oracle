"""Esperimento: coerenza tra mercati via "chaining" della predizione match-winner.

Richiesta esplicita dell'utente (design del sistema): garantire che le
predizioni sui vari mercati per la stessa partita siano tra loro coerenti
(es. se il modello prevede che il Giocatore A vinca il match, gli altri
eventi dovrebbero riflettere questa forza relativa), costruendo gli eventi in
ordine e passando ad ognuno, come nuova feature, la predizione del
match-winner.

Finora (``train_over_under_games.py``) il modello O/U Games vede solo le
QUOTE DI MERCATO del match winner (``avg_market_prob_player_1/2``, gia'
incluse nel feature-set v3 standard) — un proxy della forza relativa, non la
predizione del NOSTRO modello. Questo esperimento verifica se aggiungere la
vera predizione del modello (non la quota) porta un miglioramento reale.

Per evitare leakage temporale, il modello match-winner "chained" NON e' il
modello pubblico (allenato una tantum su tutto lo storico): viene riallenato
PER OGNI FOLD walk-forward usando SOLO il train di quel fold (stesso schema
random_forest v3 ufficiale, stesse feature Elo/rank/forma/H2H+odds), poi
usato per generare ``predict_proba`` sia sul train sia sul test dello stesso
fold — esattamente come gia' avviene per gli altri modelli in questa
infrastruttura (nessun modello vede mai dati futuri rispetto al fold).

Riusa ``evaluate_fold_models_over_under_games`` (stessa infrastruttura fold/
leakage/metriche di ``train_over_under_games.py``) tramite
``feature_columns_override``, per non duplicare la logica. Script
esplorativo: NON tocca ``train_over_under_games.py`` ne' il suo report
ufficiale. Report dedicato:
``data/reports/over_under_games_chained_experiment_results.json``.

Uso (da repo root, richiede DB)::

    python -m backend.src.app.ml.training.train_over_under_games_chained_experiment
    python -m backend.src.app.ml.training.train_over_under_games_chained_experiment --quick
    python -m backend.src.app.ml.training.train_over_under_games_chained_experiment --min-date 2024-12-01
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
)
from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR
from backend.src.app.ml.training.train_baseline import build_preprocessor, selected_feature_columns
from backend.src.app.ml.training.train_over_under_games import (
    OVER_UNDER_BENCHMARK_NAMES,
    OVER_UNDER_MODEL_NAMES,
    OVER_UNDER_TARGET_COLUMN,
    QUICK_CONFIG_OVERRIDES,
    RESULTS_FILENAME as BASELINE_RESULTS_FILENAME,
    build_over_under_games_dataframe,
    evaluate_fold_models_over_under_games,
)
from backend.src.app.ml.training.walk_forward import (
    WalkForwardConfig,
    WalkForwardFoldOutcome,
    _date_max,
    _date_min,
    _estimators,
    _fold_test_overlaps,
    _mean_metrics,
    generate_walk_forward_folds,
    prepare_temporal_dataframe,
    slice_fold_frames,
)

logger = logging.getLogger(__name__)

MATCH_WINNER_TARGET_COLUMN = "target_player_1_win"
CHAINED_FEATURE_COLUMN = "chained_match_winner_prob"
RESULTS_FILENAME = "over_under_games_chained_experiment_results.json"
MIN_ROWS_FOR_CHAINED_MODEL = 20


def _train_chained_match_winner_model(
    train: pd.DataFrame,
    *,
    random_state: int,
) -> tuple[Any, list[str]] | None:
    """Random forest match-winner (stessi iperparametri ufficiali v3) allenato
    SOLO sul train di questo fold. ``None`` se non allenabile (colonna target
    assente, righe insufficienti o classe singola): nessun leakage, MAI un
    fallback sul modello pubblico allenato su tutto lo storico."""
    if MATCH_WINNER_TARGET_COLUMN not in train.columns:
        return None
    y = pd.to_numeric(train[MATCH_WINNER_TARGET_COLUMN], errors="coerce")
    mask = y.notna()
    if mask.sum() < MIN_ROWS_FOR_CHAINED_MODEL or y.loc[mask].nunique() < 2:
        return None

    feature_columns = selected_feature_columns(train.loc[mask], model_version="v3")
    if not feature_columns:
        return None

    from sklearn.pipeline import Pipeline

    estimators = _estimators(random_state)
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(train.loc[mask], feature_columns)),
            ("model", estimators["random_forest"]),
        ]
    )
    pipeline.fit(train.loc[mask, feature_columns], y.loc[mask].astype(int))
    return pipeline, feature_columns


def add_chained_match_winner_feature(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    random_state: int,
) -> tuple[pd.DataFrame, pd.DataFrame, bool]:
    """Aggiunge ``chained_match_winner_prob`` a train/test di UN fold: la
    probabilita' di vittoria player_1 secondo un modello allenato SOLO sul
    train di quello stesso fold (mai il modello pubblico, per evitare che il
    modello "veda" partite future rispetto al fold in valutazione)."""
    result = _train_chained_match_winner_model(train, random_state=random_state)
    train_out = train.copy()
    test_out = test.copy()
    if result is None:
        train_out[CHAINED_FEATURE_COLUMN] = float("nan")
        test_out[CHAINED_FEATURE_COLUMN] = float("nan")
        return train_out, test_out, False

    pipeline, feature_columns = result
    train_out[CHAINED_FEATURE_COLUMN] = pipeline.predict_proba(train_out[feature_columns])[:, 1]
    test_out[CHAINED_FEATURE_COLUMN] = pipeline.predict_proba(test_out[feature_columns])[:, 1]
    return train_out, test_out, True


def _load_baseline_comparison(reports_dir: str | Path) -> dict[str, Any] | None:
    """Estratto in sola lettura dell'ultimo report ufficiale SENZA chaining
    (``train_over_under_games.py``), per confronto diretto. Non e' una nuova
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


def run_over_under_games_chained_experiment(
    db: Session,
    *,
    line: float = DEFAULT_LINE,
    config: WalkForwardConfig | None = None,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    min_date: str | None = None,
) -> dict[str, Any]:
    resolved_config = config or WalkForwardConfig()
    resolved_config.validate()

    merged, dataset_path = build_over_under_games_dataframe(db, line=line, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=OVER_UNDER_TARGET_COLUMN, model_version="v3",
    )
    if "avg_over_odds" in dataframe.columns and "avg_under_odds" in dataframe.columns:
        has_odds = (
            pd.to_numeric(dataframe["avg_over_odds"], errors="coerce").notna()
            & pd.to_numeric(dataframe["avg_under_odds"], errors="coerce").notna()
        )
        dataframe = dataframe.loc[has_odds].reset_index(drop=True)
    if min_date is not None:
        cutoff = pd.to_datetime(min_date).date()
        dataframe = dataframe.loc[pd.to_datetime(dataframe["match_date"]).dt.date >= cutoff].reset_index(
            drop=True
        )

    folds = generate_walk_forward_folds(dataframe, resolved_config)
    outcomes: list[WalkForwardFoldOutcome] = []
    leakage_flags = list(_fold_test_overlaps(folds))
    if not folds:
        leakage_flags.append("no_folds_generated_insufficient_date_span")

    chained_feature_folds = 0
    for fold in folds:
        train, test = slice_fold_frames(dataframe, fold)
        train_chained, test_chained, chained_ok = add_chained_match_winner_feature(
            train, test, random_state=resolved_config.random_state,
        )
        if chained_ok:
            chained_feature_folds += 1

        base_features = selected_feature_columns(train_chained, model_version="v3") + [
            column for column in OVER_UNDER_ODDS_FEATURE_COLUMNS if column in train_chained.columns
        ]
        fold_features = [*base_features, CHAINED_FEATURE_COLUMN]
        outcomes.extend(
            evaluate_fold_models_over_under_games(
                train_chained, test_chained, dataset_path=str(dataset_path), fold=fold, config=resolved_config,
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
        "phase": "over_under_games_chained_experiment",
        "target_column": OVER_UNDER_TARGET_COLUMN,
        "over_under_line": line,
        "min_date": min_date,
        "chained_feature_column": CHAINED_FEATURE_COLUMN,
        "chained_source_target": MATCH_WINNER_TARGET_COLUMN,
        "model_names": list(OVER_UNDER_MODEL_NAMES),
        "benchmark_names": list(OVER_UNDER_BENCHMARK_NAMES),
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
        "coverage": {
            "folds_planned": len(folds),
            "fold_outcomes": len(outcomes),
            "completed": len(completed),
            "skipped": len(skipped),
            "errors": len(errors),
            "folds_with_chained_feature_trained": chained_feature_folds,
        },
        "leakage_flags": unique_leakage,
        "aggregate_metrics": aggregate_metrics,
        "baseline_no_chaining": baseline_comparison,
        "folds": [outcome.to_dict() for outcome in outcomes],
        "notes": [
            "Script esplorativo: NON tocca train_over_under_games.py ne' il suo report "
            "ufficiale. Report dedicato separato.",
            f"Feature aggiuntiva testata: '{CHAINED_FEATURE_COLUMN}' — predict_proba di un "
            "random_forest match-winner (stesse feature/iperparametri v3 ufficiali) allenato "
            "PER OGNI FOLD solo sul train di quel fold (mai il modello pubblico, per evitare "
            "leakage temporale).",
            "'baseline_no_chaining' e' un estratto in sola lettura dell'ultimo report "
            "ufficiale (train_over_under_games.py, SENZA chaining): non e' una nuova "
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


def format_chained_experiment_summary(report: dict[str, Any]) -> str:
    lines = [
        "Esperimento chaining — Over/Under Games (predizione match-winner come feature)",
        f"Dataset: {report['dataset_path']}",
        f"  {report['dataset_rows']} righe ({report['date_min']} - {report['date_max']})",
        (
            f"Fold: pianificati={report['coverage']['folds_planned']} "
            f"completati={report['coverage']['completed']} "
            f"skipped={report['coverage']['skipped']} errors={report['coverage']['errors']} "
            f"(chained-model allenato in {report['coverage']['folds_with_chained_feature_trained']} fold)"
        ),
        "",
    ]
    for name in (*report["model_names"], *report["benchmark_names"]):
        agg = report["aggregate_metrics"].get(name, {})
        if not agg:
            lines.append(f"--- {name}: nessun fold completato ---")
            continue
        roc = agg.get("roc_auc", {})
        lines.append(f"--- {name} (CON chaining): roc_auc mean={roc.get('mean')} n={roc.get('n')} ---")

    baseline = report.get("baseline_no_chaining")
    lines.append("")
    if baseline:
        lines.append(f"Confronto SENZA chaining ({baseline.get('source')}):")
        for model_name in report["model_names"]:
            base_roc = (baseline.get("aggregate_metrics") or {}).get(model_name, {}).get("roc_auc", {})
            lines.append(f"  {model_name}: roc_auc mean={base_roc.get('mean')} n={base_roc.get('n')}")
    else:
        lines.append("Nessun report ufficiale trovato per il confronto (esegui prima train_over_under_games.py).")

    lines.append("")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Esperimento esplorativo: chaining match-winner -> Over/Under Games."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--line", type=float, default=DEFAULT_LINE)
    parser.add_argument("--min-date", default=None)
    parser.add_argument("--quick", action="store_true", help="Finestre piu' corte (smoke test).")
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
        report = run_over_under_games_chained_experiment(
            db, line=args.line, config=config, processed_dir=args.processed_dir,
            reports_dir=args.reports_dir, min_date=args.min_date,
        )
    print(format_chained_experiment_summary(report))


if __name__ == "__main__":
    main()

