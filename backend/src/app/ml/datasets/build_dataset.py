import argparse
import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.datasets.dataset_builder import (
    build_and_export_dataset_report,
    build_and_export_dataset_report_v2,
    format_dataset_summary,
    format_v2_dataset_summary,
)
from backend.src.app.ml.model_versioning import DATASET_VERSIONS
from backend.src.repository.base.repository_db import SessionLocal


logger = logging.getLogger(__name__)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "processed"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera un dataset CSV addestrabile da fixture legacy."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Cartella di output CSV.",
    )
    parser.add_argument(
        "--filename",
        default=None,
        help="Nome file CSV. Se omesso, deriva da --version.",
    )
    parser.add_argument(
        "--version",
        choices=["v1", "v2", "v3"],
        default="v1",
        help="Versione dataset da generare (v1 placeholder rank/elo, v2 reali).",
    )
    args = parser.parse_args()

    version = args.version
    filename = args.filename or DATASET_VERSIONS[version].base_dataset

    logging.basicConfig(level=logging.INFO)
    logger.info("Avvio dataset builder tennis_oracle (%s)", version)

    with SessionLocal() as db:
        if version in {"v2", "v3"}:
            result = build_and_export_dataset_report_v2(
                db=db,
                output_dir=args.output_dir,
                filename=filename,
            )
            summary_text = format_v2_dataset_summary(result.summary)
        else:
            result = build_and_export_dataset_report(
                db=db,
                output_dir=args.output_dir,
                filename=filename,
            )
            summary_text = format_dataset_summary(result.summary)

    print(f"Dataset salvato in: {result.csv_path}")
    print(summary_text)


if __name__ == "__main__":
    main()
