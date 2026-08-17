"""CLI entry point: genera e pubblica (nel ledger generico ``PublishedPrediction``)
le predizioni per i mercati "extra": Vincitore 1° set, Over/Under Games.

La logica vive in ``app.services.extra_market_predictions`` (chiamata anche
dall'orchestratore ``global_update`` come fase regolare della pipeline, non
solo da questo script standalone). Questo modulo resta un thin wrapper CLI e
re-esporta i simboli storici per compatibilità import (test/script esistenti).

Uso (da repo root, richiede DB)::

    python -m backend.src.jobs.generate_extra_market_predictions
    python -m backend.src.jobs.generate_extra_market_predictions --days-forward 5 --dry-run
"""

from __future__ import annotations

import argparse
import logging

from backend.src.app.services.extra_market_predictions import (
    DEFAULT_PUBLICATION_SOURCE,
    EXTRA_MARKET_PREDICTORS,
    PUBLICATION_SOURCE_CHOICES,
    _already_published as _already_published,
    _publish_result as _publish_result,
    format_summary,
    run_extra_market_predictions_generation,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_PUBLICATION_SOURCE",
    "EXTRA_MARKET_PREDICTORS",
    "PUBLICATION_SOURCE_CHOICES",
    "format_summary",
    "run_extra_market_predictions_generation",
    "main",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera e pubblica predizioni per i mercati extra (1 set winner, O/U games)."
    )
    parser.add_argument("--days-forward", type=int, default=10)
    parser.add_argument(
        "--publication-source", choices=PUBLICATION_SOURCE_CHOICES, default=DEFAULT_PUBLICATION_SOURCE,
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    summary = run_extra_market_predictions_generation(
        days_forward=args.days_forward,
        publication_source=args.publication_source,
        dry_run=args.dry_run,
    )
    print(format_summary(summary))


if __name__ == "__main__":
    main()


