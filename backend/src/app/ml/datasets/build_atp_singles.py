import argparse
import logging
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.datasets.atp_singles_enrichment import build_atp_singles_outputs


logger = logging.getLogger(__name__)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "backend" / "data" / "processed"
DEFAULT_ATP_DATA_DIR = DEFAULT_OUTPUT_DIR / "tennis_atp-master"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea CSV di arricchimento ATP singles senza modificare il dataset base."
    )
    parser.add_argument(
        "--atp-data-dir",
        default=str(DEFAULT_ATP_DATA_DIR),
        help="Cartella del dump tennis_atp-master.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Cartella di output CSV.",
    )
    parser.add_argument(
        "--base-dataset-filename",
        default="tennis_winner_dataset.csv",
        help="Dataset base da arricchire, se presente nella cartella output.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logger.info("Avvio ATP singles enrichment")

    result = build_atp_singles_outputs(
        atp_data_dir=Path(args.atp_data_dir),
        output_dir=Path(args.output_dir),
        base_dataset_filename=args.base_dataset_filename,
    )

    print(f"ATP singles normalizzati: {result.atp_matches_csv}")
    print(f"Mapping match ATP: {result.atp_match_mapping_csv}")
    print(f"Mapping player ATP: {result.atp_player_mapping_csv}")
    if result.enriched_dataset_csv:
        print(f"Dataset arricchito ATP: {result.enriched_dataset_csv}")
    else:
        print("Dataset arricchito ATP: non creato, dataset base non trovato")
    print(f"Righe ATP singles: {result.atp_rows}")
    print(f"Fixture ATP candidate: {result.fixture_rows}")
    print(f"Match incrociati: {result.matched_rows}")
    print(f"Righe dataset arricchito: {result.enriched_rows}")


if __name__ == "__main__":
    main()
