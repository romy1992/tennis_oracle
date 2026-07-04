import argparse
import logging

from backend.src.app.db.session import SessionLocal
from backend.src.app.ml.datasets.dataset_builder import build_and_export_dataset
from backend.src.app.ml.features.feature_builder import build_feature_snapshots


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genera FeatureSnapshot e CSV dataset ML senza fare training."
    )
    parser.add_argument(
        "--build-features",
        action="store_true",
        help="Calcola e salva FeatureSnapshot prima di esportare il dataset.",
    )
    parser.add_argument(
        "--overwrite-features",
        action="store_true",
        help="Rigenera FeatureSnapshot già esistenti.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Numero massimo di match da usare per il calcolo feature.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed",
        help="Cartella di output CSV.",
    )
    parser.add_argument(
        "--filename",
        default="tennis_features.csv",
        help="Nome file CSV.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        if args.build_features:
            created = build_feature_snapshots(
                db=db,
                limit=args.limit,
                overwrite=args.overwrite_features,
            )
            logger.info("FeatureSnapshot generate: %s", created)

        csv_path = build_and_export_dataset(
            db=db,
            output_dir=args.output_dir,
            filename=args.filename,
        )
        logger.info("Dataset esportato in %s", csv_path)


if __name__ == "__main__":
    main()
