import argparse
import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.datasets.dataset_builder import (
    build_and_export_dataset_report,
    format_dataset_summary,
)
from backend.src.repository.base.repository_db import SessionLocal


logger = logging.getLogger(__name__)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "processed"
DEFAULT_FILENAME = "tennis_winner_dataset.csv"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera un dataset CSV addestrabile da FeatureSnapshot."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Cartella di output CSV.",
    )
    parser.add_argument(
        "--filename",
        default=DEFAULT_FILENAME,
        help="Nome file CSV.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logger.info("Avvio dataset builder tennis_oracle")

    with SessionLocal() as db:
        result = build_and_export_dataset_report(
            db=db,
            output_dir=args.output_dir,
            filename=args.filename,
        )

    print(f"Dataset salvato in: {result.csv_path}")
    print(format_dataset_summary(result.summary))


if __name__ == "__main__":
    main()
