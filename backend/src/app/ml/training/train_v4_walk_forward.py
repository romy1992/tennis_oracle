"""Fase 5 — Walk-forward multi-finestra del vincitore Fase 3 (voting soft v4).

Valida, su piu' finestre temporali (non solo sull'ultimo holdout usato in Fase 1-4),
l'ensemble vincitore trovato in Fase 3 (``train_v4_ensemble``): ``voting_soft`` con
media delle probabilita' di ``logistic_regression`` + ``xgboost`` +
``hist_gradient_boosting`` (i best_params tunati in Fase 1+2, letti da
``data/reports/v4_grid_search_results.json``).

Riusa integralmente l'infrastruttura di ``walk_forward.py`` (generazione fold,
controlli anti-leakage temporale, metriche, benchmark di mercato/ATP/Elo) tramite
il nuovo parametro opzionale ``estimators_factory`` di
``run_walk_forward_for_version``/``evaluate_fold_models``: NON duplica alcuna logica
di split/fold, si limita a iniettare l'ensemble come "modello" aggiuntivo.

Questo script e' **esplorativo** (Fase 5 del piano v4): NON sovrascrive
``walk_forward_latest.json`` (il file ufficiale letto dalla dashboard), NON tocca
``model_registry.json``/``model_comparison.json`` e non modifica il modello
pubblico. Produce un report dedicato: ``data/reports/v4_walk_forward_results.json``.

Fase 5.2 (``--mature``, NON sostituisce la Fase 5 standard): la Fase 5 originale
mostrava un ROI cumulativo multi-fold nettamente peggiore del singolo holdout
Fase 1-4, ma l'analisi per-fold ha rivelato che la perdita era concentrata nei
primi fold "immaturi" (2023, con solo 1-1.75 anni di storia per il training,
essendo ``initial_train_days`` di default 365). La Fase 5.2 rialza la soglia di
maturita' del training storico (``initial_train_days=1095``, ~3 anni) per stimare
il ROI "a regime" escludendo i fold immaturi, che in produzione non si
ripresenteranno mai (la storia disponibile cresce solo nel tempo). Salva un
report **separato** (``v4_walk_forward_mature_results.json``): la Fase 5
standard resta intatta e consultabile per il confronto.

Uso (da repo root)::

    python -m backend.src.app.ml.training.train_v4_walk_forward --quick   # smoke test
    python -m backend.src.app.ml.training.train_v4_walk_forward           # run completa (Fase 5)
    python -m backend.src.app.ml.training.train_v4_walk_forward --mature  # Fase 5.2 (soglia maturita' alta)
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

from backend.src.app.ml.model_versioning import PROCESSED_DATA_DIR, REPORTS_DIR  # noqa: E402
from backend.src.app.ml.training.train_v4_ensemble import (  # noqa: E402
    BASE_ALGORITHMS,
    build_base_estimators,
)
from backend.src.app.ml.training.value_bet_metrics import DEFAULT_EDGE_THRESHOLD  # noqa: E402
from backend.src.app.ml.training.walk_forward import (  # noqa: E402
    WalkForwardConfig,
    run_walk_forward_for_version,
)

logger = logging.getLogger(__name__)

# L'ensemble e' costruito sulle feature v3 (Elo/rank/form/H2H + quote di mercato):
# non ha senso validarlo su v1/v2, che non hanno le feature di mercato usate in Fase 1-4.
SEARCH_MODEL_VERSION = "v3"
ENSEMBLE_MODEL_NAME = "voting_ensemble_v4"
RESULTS_FILENAME = "v4_walk_forward_results.json"
MATURE_RESULTS_FILENAME = "v4_walk_forward_mature_results.json"
OFFICIAL_WALK_FORWARD_LATEST_FILENAME = "walk_forward_latest.json"

# Finestre ridotte per uno smoke-test end-to-end veloce (usato dai test unitari e da
# ``--quick``): con dataset piccoli genera comunque un paio di fold completi.
QUICK_CONFIG_OVERRIDES: dict[str, Any] = {
    "initial_train_days": 60,
    "test_days": 30,
    "step_days": 30,
    "min_train_rows": 20,
    "min_test_rows": 10,
}

# Fase 5.2 (``--mature``): stessa finestra test/step della Fase 5 standard, ma
# richiede molta piu' storia iniziale (~3 anni invece di 1) prima del primo fold,
# per escludere i fold "immaturi" che nella Fase 5 avevano il ROI peggiore (poco
# training storico -> hit-rate basso). In produzione questa condizione (poca
# storia) non si ripresenta mai: la storia disponibile cresce solo nel tempo.
MATURE_CONFIG_OVERRIDES: dict[str, Any] = {
    "initial_train_days": 1095,
}


def make_v4_voting_estimators_factory(reports_dir: str | Path) -> Callable[[int], dict[str, Any]]:
    """Costruisce una ``estimators_factory`` (firma compatibile con
    ``walk_forward.evaluate_fold_models``) che ad ogni fold ricrea da zero un
    ``VotingClassifier`` soft sui 3 modelli base Fase 1+2, con gli stessi
    iperparametri tunati usati in Fase 3 (``train_v4_ensemble.build_base_estimators``).

    Ricostruire gli stimatori ad ogni chiamata (anziche' riutilizzare le stesse
    istanze tra i fold) evita qualunque rischio di stato residuo tra finestre
    temporali diverse; il costo aggiuntivo e' trascurabile (sola istanziazione,
    il fit vero avviene comunque dentro la Pipeline per ogni fold).
    """

    def factory(_random_state: int) -> dict[str, Any]:
        from sklearn.ensemble import VotingClassifier

        base_estimators, _provenance = build_base_estimators(reports_dir)
        return {
            ENSEMBLE_MODEL_NAME: VotingClassifier(
                estimators=list(base_estimators), voting="soft", n_jobs=1
            )
        }

    return factory


def _round(value: Any, digits: int = 6) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def _aggregate_value_bet_across_folds(folds: list[dict[str, Any]], model_name: str) -> dict[str, Any]:
    """Aggrega manualmente il ROI/value-bet dell'ensemble attraverso i fold.

    ``walk_forward._mean_metrics``/``_aggregate_official_benchmarks`` aggregano solo
    le metriche standard (accuracy/roc_auc/log_loss/...) e il ROI dei soli
    "contendenti ufficiali" fissi (mercato/ATP/Elo/logistic_regression/random_forest):
    un ``model_name`` custom come l'ensemble v4 non rientra in quella lista fissa, ma
    il suo ``value_bet_overall`` per-fold e' comunque calcolato e disponibile in
    ``fold['metrics']`` da ``classification_metrics`` (stessa funzione usata in Fase 1-4).
    Questa funzione lo aggrega qui, senza dover estendere ulteriormente ``walk_forward.py``.
    """
    rois: list[float] = []
    hit_rates: list[float] = []
    bets_counts: list[int] = []
    total_profits: list[float] = []
    per_fold: list[dict[str, Any]] = []

    for fold_dict in folds:
        if fold_dict.get("model_name") != model_name or fold_dict.get("status") != "completed":
            continue
        value_bet = ((fold_dict.get("metrics") or {}).get("value_bet_overall")) or {}
        roi = value_bet.get("roi")
        bets_count = value_bet.get("bets_count")
        per_fold.append(
            {
                "fold_index": fold_dict["fold"]["fold_index"],
                "test_start": fold_dict["fold"]["test_start"],
                "test_end": fold_dict["fold"]["test_end"],
                "roi": roi,
                "hit_rate": value_bet.get("hit_rate"),
                "bets_count": bets_count,
                "total_profit": value_bet.get("total_profit"),
            }
        )
        if roi is not None:
            rois.append(float(roi))
        if value_bet.get("hit_rate") is not None:
            hit_rates.append(float(value_bet["hit_rate"]))
        if bets_count is not None:
            bets_counts.append(int(bets_count))
        if value_bet.get("total_profit") is not None:
            total_profits.append(float(value_bet["total_profit"]))

    import pandas as pd

    def _stat(values: list[float]) -> dict[str, Any]:
        if not values:
            return {"mean": None, "std": None, "min": None, "max": None, "n": 0}
        series = pd.Series(values, dtype=float)
        return {
            "mean": _round(series.mean()),
            "std": _round(series.std(ddof=0)) if len(values) > 1 else 0.0,
            "min": _round(series.min()),
            "max": _round(series.max()),
            "n": len(values),
        }

    return {
        "folds_with_bets": len(per_fold),
        "roi_per_fold_stats": _stat(rois),
        "hit_rate_per_fold_stats": _stat(hit_rates),
        "total_bets_all_folds": int(sum(bets_counts)) if bets_counts else 0,
        "cumulative_profit_all_folds": _round(sum(total_profits)) if total_profits else None,
        "cumulative_roi_all_folds": (
            _round(sum(total_profits) / sum(bets_counts)) if total_profits and sum(bets_counts) else None
        ),
        "per_fold": per_fold,
    }


def _load_historical_lr_rf_comparison(
    reports_dir: str | Path, model_version: str = SEARCH_MODEL_VERSION
) -> dict[str, Any] | None:
    """Legge in sola lettura l'ultimo walk-forward ufficiale (logistic_regression/
    random_forest, v1/v2/v3) e ne estrae solo le ``aggregate_metrics`` della versione
    richiesta, per un confronto multi-fold con l'ensemble v4 senza duplicare l'intero
    report ufficiale (che puo' essere molto grande) e senza mai scriverci sopra.
    """
    path = Path(reports_dir) / "walk_forward" / OFFICIAL_WALK_FORWARD_LATEST_FILENAME
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        for version in payload.get("versions", []):
            if version.get("model_version") == model_version:
                return {
                    "source": str(path),
                    "official_run_started_at": payload.get("started_at"),
                    "aggregate_metrics": version.get("aggregate_metrics"),
                    "folds_planned": (version.get("coverage") or {}).get("folds_planned"),
                }
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Impossibile leggere %s per il confronto storico: %s", path, exc)
    return None


def run_v4_walk_forward(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    reports_dir: str | Path = REPORTS_DIR,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
    quick: bool = False,
    mature: bool = False,
) -> dict[str, Any]:
    if quick and mature:
        raise ValueError("--quick e --mature sono mutuamente esclusivi.")

    config_kwargs: dict[str, Any] = {"edge_threshold": edge_threshold}
    if quick:
        config_kwargs.update(QUICK_CONFIG_OVERRIDES)
    elif mature:
        config_kwargs.update(MATURE_CONFIG_OVERRIDES)
    config = WalkForwardConfig(**config_kwargs)

    estimators_factory = make_v4_voting_estimators_factory(reports_dir)

    phase_name = "fase_5_2_walk_forward_mature_winner" if mature else "fase_5_walk_forward_winner"
    logger.info(
        "Avvio walk-forward %s per %s (ensemble=%s, mode=%s, quick=%s, mature=%s, initial_train_days=%s)",
        phase_name,
        SEARCH_MODEL_VERSION,
        ENSEMBLE_MODEL_NAME,
        config.mode,
        quick,
        mature,
        config.initial_train_days,
    )
    version_result = run_walk_forward_for_version(
        SEARCH_MODEL_VERSION,
        config,
        processed_dir=processed_dir,
        reports_dir=reports_dir,
        model_names=(ENSEMBLE_MODEL_NAME,),
        estimators_factory=estimators_factory,
    )

    fold_dicts = [fold.to_dict() for fold in version_result.folds]
    value_bet_aggregate = _aggregate_value_bet_across_folds(fold_dicts, ENSEMBLE_MODEL_NAME)
    historical_comparison = _load_historical_lr_rf_comparison(reports_dir)

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": phase_name,
        "model_version": SEARCH_MODEL_VERSION,
        "ensemble_model_name": ENSEMBLE_MODEL_NAME,
        "base_algorithms": BASE_ALGORITHMS,
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
            "edge_threshold": config.edge_threshold,
            "random_state": config.random_state,
        },
        "dataset_path": version_result.dataset_path,
        "dataset_rows": version_result.dataset_rows,
        "date_min": version_result.date_min,
        "date_max": version_result.date_max,
        "feature_set": version_result.feature_set,
        "coverage": version_result.coverage,
        "leakage_flags": version_result.leakage_flags,
        "aggregate_metrics": version_result.aggregate_metrics,
        "value_bet_aggregate_across_folds": value_bet_aggregate,
        "folds": fold_dicts,
        "historical_lr_rf_comparison": historical_comparison,
        "notes": [
            "Script esplorativo Fase 5/5.2: NON sovrascrive walk_forward_latest.json ne' model_registry.json.",
            "Valida SOLO il vincitore Fase 3 (voting_soft: logistic_regression + xgboost + "
            "hist_gradient_boosting) su piu' finestre temporali, non solo sull'ultimo holdout "
            "usato in Fase 1-4: verifica se la vittoria e' consistente nel tempo o dipende dal "
            "particolare periodo di test finale.",
            "'value_bet_aggregate_across_folds' e' calcolato qui (non da walk_forward.py) perche' "
            "l'ensemble non fa parte della lista fissa OFFICIAL_CONTENDERS usata per i benchmark "
            "ufficiali: usa comunque la stessa logica di value-bet (edge_threshold) delle Fasi 1-4.",
            "'historical_lr_rf_comparison' e' un estratto in sola lettura dell'ultimo walk-forward "
            "ufficiale gia' calcolato: non e' una nuova esecuzione, quindi puo' usare fold "
            "leggermente diversi se la config e' cambiata nel frattempo.",
            "Se l'ensemble e' consistentemente competitivo/migliore su (quasi) tutti i fold, non "
            "solo in media, e' il candidato naturale per la promozione formale a v4 (Fase 6).",
        ]
        + (
            [
                "FASE 5.2 (mature_mode=true): initial_train_days alzato a "
                f"{MATURE_CONFIG_OVERRIDES['initial_train_days']} giorni per escludere i fold "
                "\"immaturi\" (poco training storico) identificati nella Fase 5 standard come "
                "principale causa del ROI cumulativo negativo. Report separato: NON sostituisce "
                f"{RESULTS_FILENAME}, che resta la validazione di riferimento con la config standard "
                "(initial_train_days=365, coerente con il walk-forward ufficiale v1/v2/v3).",
            ]
            if mature
            else []
        ),
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    resolved_results_filename = MATURE_RESULTS_FILENAME if mature else RESULTS_FILENAME
    results_path = reports_path / resolved_results_filename
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def format_walk_forward_summary(report: dict[str, Any]) -> str:
    ensemble_name = report["ensemble_model_name"]
    phase_label = "Fase 5.2 (soglia maturita' alta)" if report.get("mature_mode") else "Fase 5"
    lines = [
        f"{phase_label} - Walk-forward vincitore v4 ({ensemble_name})",
        f"Base algorithms: {', '.join(report['base_algorithms'])}",
        f"Dataset: {report['dataset_path']}",
        f"  {report['dataset_rows']} righe ({report['date_min']} - {report['date_max']})",
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

    ensemble_agg = report["aggregate_metrics"].get(ensemble_name, {})
    lines.append(f"--- {ensemble_name} (media sui fold completati) ---")
    for key in ("roc_auc", "log_loss", "accuracy", "f1"):
        stat = ensemble_agg.get(key, {})
        lines.append(f"  {key}: mean={stat.get('mean')} std={stat.get('std')} n={stat.get('n')}")

    value_bet_agg = report.get("value_bet_aggregate_across_folds", {})
    lines.append("  value-bet ROI attraverso i fold (edge_threshold>=%s, Fase 1-4 style):" % report["config"]["edge_threshold"])
    lines.append(
        f"    roi_per_fold: mean={value_bet_agg.get('roi_per_fold_stats', {}).get('mean')} "
        f"std={value_bet_agg.get('roi_per_fold_stats', {}).get('std')} "
        f"n={value_bet_agg.get('roi_per_fold_stats', {}).get('n')}"
    )
    lines.append(
        f"    roi_cumulativo (tutte le bet di tutti i fold): "
        f"{value_bet_agg.get('cumulative_roi_all_folds')} "
        f"(bets totali={value_bet_agg.get('total_bets_all_folds')}, "
        f"profit totale={value_bet_agg.get('cumulative_profit_all_folds')})"
    )

    official = report["aggregate_metrics"].get("official_benchmarks", {})
    ensemble_official = official.get(ensemble_name, {})
    if ensemble_official:
        roi_stat = ensemble_official.get("roi", {})
        lines.append(
            "  official_benchmark ROI (bet-always sul predetto, stessa metodologia storica LR/RF): "
            f"mean={roi_stat.get('mean')} std={roi_stat.get('std')} n={roi_stat.get('n')}"
        )
    market_official = official.get("market_no_vig", {})
    if market_official:
        lines.append("  market_no_vig benchmark (stesso periodo/fold):")
        for key in ("roi", "accuracy", "log_loss"):
            stat = market_official.get(key, {})
            lines.append(f"    {key}: mean={stat.get('mean')} std={stat.get('std')} n={stat.get('n')}")

    historical = report.get("historical_lr_rf_comparison")
    if historical:
        lines.append("")
        lines.append(f"Confronto storico (ultimo walk-forward ufficiale, {historical.get('source')}):")
        for model_name in ("logistic_regression", "random_forest"):
            agg = (historical.get("aggregate_metrics") or {}).get(model_name)
            if agg:
                roc = agg.get("roc_auc", {})
                lines.append(f"  {model_name}: roc_auc mean={roc.get('mean')} n={roc.get('n')}")
            official_hist = (historical.get("aggregate_metrics") or {}).get("official_benchmarks", {}).get(model_name, {})
            if official_hist:
                roi_hist = official_hist.get("roi", {})
                lines.append(
                    f"  {model_name}: official_benchmark roi mean={roi_hist.get('mean')} "
                    f"std={roi_hist.get('std')} n={roi_hist.get('n')}"
                )
    else:
        lines.append("")
        lines.append("Nessun walk-forward ufficiale storico trovato per il confronto.")

    lines.append("")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fase 5: walk-forward multi-finestra del vincitore v4 (voting soft)."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--edge-threshold", type=float, default=DEFAULT_EDGE_THRESHOLD)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Finestre piu' corte (smoke test): initial_train_days/test_days/step_days ridotti.",
    )
    parser.add_argument(
        "--mature",
        action="store_true",
        help=(
            "Fase 5.2: initial_train_days alzato a ~3 anni per escludere i fold immaturi "
            "(NON sostituisce il report della Fase 5 standard, salva in un file separato)."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Avvio Fase 5 walk-forward v4 (quick=%s, mature=%s)", args.quick, args.mature)

    report = run_v4_walk_forward(
        processed_dir=args.processed_dir,
        reports_dir=args.reports_dir,
        edge_threshold=args.edge_threshold,
        quick=args.quick,
        mature=args.mature,
    )
    print(format_walk_forward_summary(report))


if __name__ == "__main__":
    main()






