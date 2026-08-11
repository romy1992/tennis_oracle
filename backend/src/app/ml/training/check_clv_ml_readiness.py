"""Diagnostica ricorrente (non training): c'e' abbastanza CLV storico per
pensare a un target ML "CLV invece di esito"?

Contesto: il CLV oggi e' sigillato in modo opportunistico
(``seal_closing_from_last_prematch``), NON da un polling dedicato pre-kickoff —
vedi ``docs/SCHEDULING.md`` sezione "Closing odds (job futuro)" per il limite
strutturale noto e la misurazione di riferimento (2026-08-10: 9/92 tip con CLV,
0/48 in una settimana intera). Questo script e' pensato per essere rieseguito
periodicamente per capire QUANDO (se mai, prima che il job dedicato esista)
il volume diventa sufficiente per riconsiderare l'idea.

Non duplica calcoli: riusa integralmente ``compute_published_live_stats``
(stessa fonte dei KPI CLV gia' mostrati nel dashboard live:
``clv_count``/``clv_coverage_pct``/``clv_avg_pct``/``clv_positive_pct``/...) e
``settle_published_tips`` (stessa lista di tip assestate). Aggiunge solo:

- un breakdown settimanale di copertura (per distinguere un gap strutturale
  da uno semplicemente temporaneo/in miglioramento);
- un verdetto esplicito "pronto per un training?" con soglia minima
  configurabile (default 200 bet chiuse con CLV disponibile — soglia
  arbitraria, pensata solo come primo semaforo, non come garanzia
  statistica piena).

Non allena/salva alcun modello, non tocca report ufficiali. Produce un report
JSON isolato: ``data/reports/clv_ml_readiness_check.json``.

Uso (da repo root, richiede DB raggiungibile)::

    python -m backend.src.app.ml.training.check_clv_ml_readiness
    python -m backend.src.app.ml.training.check_clv_ml_readiness --min-useful-samples 300
    python -m backend.src.app.ml.training.check_clv_ml_readiness --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.db.session import SessionLocal  # noqa: E402
from backend.src.app.ml.model_versioning import REPORTS_DIR  # noqa: E402
from backend.src.app.services.published_live_stats import (  # noqa: E402
    compute_published_live_stats,
    settle_published_tips,
)

logger = logging.getLogger(__name__)

RESULTS_FILENAME = "clv_ml_readiness_check.json"
DEFAULT_MIN_USEFUL_SAMPLES = 200
SCHEDULING_DOC_REF = "docs/SCHEDULING.md#closing-odds-job-futuro"


def _weekly_clv_breakdown(settled: list[Any]) -> list[dict[str, Any]]:
    """Copertura CLV per settimana ISO (anno, settimana): rivela se il gap e'
    strutturale (basso ovunque) o solo temporaneo (in miglioramento nel tempo)."""
    by_week: dict[tuple[int, int], dict[str, int]] = {}
    for item in settled:
        year, week, _ = item.sort_date.isocalendar()
        key = (year, week)
        bucket = by_week.setdefault(key, {"total": 0, "with_clv": 0, "closed": 0, "closed_with_clv": 0})
        bucket["total"] += 1
        if item.clv.clv_pct is not None:
            bucket["with_clv"] += 1
        if item.outcome in ("won", "lost"):
            bucket["closed"] += 1
            if item.clv.clv_pct is not None:
                bucket["closed_with_clv"] += 1

    breakdown: list[dict[str, Any]] = []
    for (year, week), counts in sorted(by_week.items()):
        breakdown.append(
            {
                "iso_year": year,
                "iso_week": week,
                **counts,
                "coverage_pct": round((counts["with_clv"] / counts["total"]) * 100, 2)
                if counts["total"]
                else None,
            }
        )
    return breakdown


def run_clv_ml_readiness_check(
    db: Any = None,
    *,
    min_useful_samples: int = DEFAULT_MIN_USEFUL_SAMPLES,
    reports_dir: str | Path = REPORTS_DIR,
) -> dict[str, Any]:
    """Calcola il report di readiness. ``db`` opzionale per testabilita' (stesso
    pattern di ``activate_v4_public_model.activate_v4``): se ``None`` apre una
    sessione reale con ``SessionLocal()``."""
    if db is not None:
        return _run_with_session(db, min_useful_samples=min_useful_samples, reports_dir=reports_dir)
    with SessionLocal() as session:
        return _run_with_session(session, min_useful_samples=min_useful_samples, reports_dir=reports_dir)


def _run_with_session(
    db: Any, *, min_useful_samples: int, reports_dir: str | Path
) -> dict[str, Any]:
    summary = compute_published_live_stats(db)
    settled = settle_published_tips(db)
    weekly_breakdown = _weekly_clv_breakdown(settled)

    closed_with_clv = sum(
        1 for item in settled if item.outcome in ("won", "lost") and item.clv.clv_pct is not None
    )
    weeks_total = len(weekly_breakdown)
    weeks_with_zero_coverage = sum(
        1 for week in weekly_breakdown if week["total"] > 0 and week["with_clv"] == 0
    )
    ready_for_target_design = closed_with_clv >= min_useful_samples

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Verifica se c'e' abbastanza CLV storico per un target ML 'CLV invece di esito'.",
        "min_useful_samples": min_useful_samples,
        "closed_bets_with_clv_available": closed_with_clv,
        "ready_for_target_design": ready_for_target_design,
        "summary": summary.model_dump(mode="json"),
        "weekly_breakdown": weekly_breakdown,
        "weeks_total": weeks_total,
        "weeks_with_zero_clv_coverage": weeks_with_zero_coverage,
        "notes": [
            "Script diagnostico (non training): NON allena/salva modelli, NON tocca report ufficiali.",
            "Riusa compute_published_live_stats/settle_published_tips (stessa fonte del dashboard live): "
            "nessun ricalcolo duplicato dei KPI CLV aggregati.",
            f"Limite strutturale noto (vedi {SCHEDULING_DOC_REF}): per default il 'closing' odds e' "
            "sigillato in modo opportunistico (solo se l'import gira mentre l'evento e' gia' live), non da "
            "un polling dedicato pre-kickoff. Se 'weeks_with_zero_clv_coverage' resta alto, il problema NON "
            "si risolve aspettando: il job dedicato ('run_closing_odds_capture') esiste gia' ma e' "
            "disabilitato di default — va abilitato ('CLOSING_ODDS_JOB_ENABLED=true') insieme a un cron "
            "frequente (ogni 1-5 minuti), poi lasciato accumulare dati per settimane/mesi.",
            f"'ready_for_target_design'=true significa solo closed_bets_with_clv_available >= "
            f"{min_useful_samples} (soglia arbitraria, primo semaforo): non e' una garanzia di significativita' "
            "statistica piena ne' sostituisce una valutazione onesta del volume/qualita' al momento in cui "
            "si rivaluta l'idea.",
        ],
    }

    reports_path = Path(reports_dir)
    reports_path.mkdir(parents=True, exist_ok=True)
    results_path = reports_path / RESULTS_FILENAME
    with results_path.open("w", encoding="utf-8") as results_file:
        json.dump(report, results_file, indent=2, ensure_ascii=False, default=str)
    report["results_path"] = str(results_path)
    return report


def format_readiness_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "CLV ML readiness check",
        f"Tip pubblicati (ultima versione): {summary['predictions_total']} "
        f"(chiuse={summary['closed']}, void={summary['void']}, open={summary['open']})",
        f"clv_count={summary['clv_count']} clv_coverage_pct={summary['clv_coverage_pct']}% "
        f"clv_avg_pct={summary['clv_avg_pct']} clv_positive_pct={summary['clv_positive_pct']}%",
        f"clv_avg_prob_delta_pct={summary.get('clv_avg_prob_delta_pct')}",
        "",
        f"Bet CHIUSE con CLV disponibile: {report['closed_bets_with_clv_available']} "
        f"(soglia minima configurata: {report['min_useful_samples']})",
        f"PRONTO per un target ML CLV? {report['ready_for_target_design']}",
        f"Settimane totali osservate: {report['weeks_total']} "
        f"(di cui a copertura CLV zero: {report['weeks_with_zero_clv_coverage']})",
        "",
        "--- Copertura per settimana ISO ---",
    ]
    for week in report["weekly_breakdown"]:
        lines.append(
            f"  {week['iso_year']}-W{week['iso_week']:02d}: totale={week['total']:>4} "
            f"con_clv={week['with_clv']:>4} ({week['coverage_pct']}%)"
        )
    lines.append("")
    lines.append(f"Report completo salvato in: {report['results_path']}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifica se c'e' abbastanza CLV storico per un target ML 'CLV invece di esito'."
    )
    parser.add_argument("--min-useful-samples", type=int, default=DEFAULT_MIN_USEFUL_SAMPLES)
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    parser.add_argument("--json", action="store_true", help="Stampa il report JSON completo su stdout.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    report = run_clv_ml_readiness_check(
        min_useful_samples=args.min_useful_samples,
        reports_dir=args.reports_dir,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_readiness_summary(report))


if __name__ == "__main__":
    main()


