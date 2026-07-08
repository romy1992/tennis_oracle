import argparse
import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.datasets.odds_builder import (  # noqa: E402
    build_and_export_odds_dataset,
    format_odds_summary,
)
from backend.src.app.ml.model_versioning import DATASET_VERSIONS  # noqa: E402
from backend.src.repository.base.repository_db import SessionLocal  # noqa: E402


logger = logging.getLogger(__name__)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "processed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Estrae e normalizza le odds match winner da fixture.odds."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Cartella di output CSV.",
    )
    parser.add_argument(
        "--odds-filename",
        default="tennis_match_winner_odds.csv",
        help="Nome file CSV odds normalizzate.",
    )
    parser.add_argument(
        "--with-odds-filename",
        default=None,
        help="Nome file CSV dataset arricchito con odds aggregate.",
    )
    parser.add_argument(
        "--version",
        choices=["v1", "v2", "v3"],
        default="v1",
        help="Versione dataset sorgente/destinazione odds.",
    )
    args = parser.parse_args()

    version = args.version
    with_odds_filename = args.with_odds_filename or DATASET_VERSIONS[version].with_odds_dataset

    logging.basicConfig(level=logging.INFO)
    logger.info("Avvio odds dataset builder (%s)", version)

    with SessionLocal() as db:
        result = build_and_export_odds_dataset(
            db=db,
            output_dir=args.output_dir,
            odds_filename=args.odds_filename,
            with_odds_filename=with_odds_filename,
            dataset_version=version,
        )

    print(f"Odds match winner salvate in: {result.odds_csv_path}")
    if result.with_odds_dataset_path:
        print(f"Dataset con odds salvato in: {result.with_odds_dataset_path}")
    else:
        print("Dataset con odds: non creato, dataset sorgente non trovato")
    print(format_odds_summary(result.summary))


if __name__ == "__main__":
    main()
