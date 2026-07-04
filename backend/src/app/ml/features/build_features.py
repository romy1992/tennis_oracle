import argparse
import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.core.logging import configure_logging
from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.features.feature_builder import build_feature_snapshots_report


logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calcola FeatureSnapshot pre-match per i match storici."
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Cancella le feature esistenti prima di ricalcolarle.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di match da processare.",
    )
    args = parser.parse_args()

    configure_logging()
    logger.info("Avvio feature engineering tennis_oracle")
    logger.info("Reset feature esistenti: %s", args.reset)

    with SessionLocal() as db:
        result = build_feature_snapshots_report(
            db=db,
            limit=args.limit,
            reset=args.reset,
        )

    print(f"Match processati: {result.matches_processed}")
    print(f"Feature create: {result.features_created}")
    print(f"Match saltati: {result.matches_skipped}")
    if result.skip_reasons:
        print("Motivi skip:")
        for reason, count in sorted(result.skip_reasons.items()):
            print(f"  - {reason}: {count}")
    else:
        print("Motivi skip: nessuno")


if __name__ == "__main__":
    main()
