"""Central paths and metadata for versioned ML artifacts."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ModelVersion = Literal["v1", "v2", "v3"]

REPO_ROOT = Path(__file__).resolve().parents[4]
PROCESSED_DATA_DIR = REPO_ROOT / "backend" / "data" / "processed"
MODELS_DIR = REPO_ROOT / "backend" / "data" / "models"
REPORTS_DIR = REPO_ROOT / "backend" / "data" / "reports"
ATP_DATA_DIR = PROCESSED_DATA_DIR / "tennis_atp-master"
MATCH_MAPPING_PATH = PROCESSED_DATA_DIR / "atp_singles_match_mapping.csv"
REGISTRY_PATH = REPORTS_DIR / "model_registry.json"
COMPARISON_PATH = REPORTS_DIR / "model_comparison.json"


@dataclass(frozen=True)
class DatasetVersionPaths:
    base_dataset: str
    atp_enriched_dataset: str
    with_odds_dataset: str


@dataclass(frozen=True)
class ModelVersionPaths:
    version: ModelVersion
    datasets: DatasetVersionPaths
    models_dir: Path
    metrics_filename: str
    rank_features_note: str


DATASET_VERSIONS: dict[ModelVersion, DatasetVersionPaths] = {
    "v1": DatasetVersionPaths(
        base_dataset="tennis_winner_dataset.csv",
        atp_enriched_dataset="tennis_winner_dataset_atp_enriched.csv",
        with_odds_dataset="tennis_winner_dataset_with_odds.csv",
    ),
    "v2": DatasetVersionPaths(
        base_dataset="tennis_winner_dataset_v2.csv",
        atp_enriched_dataset="tennis_winner_dataset_atp_enriched_v2.csv",
        with_odds_dataset="tennis_winner_dataset_with_odds_v2.csv",
    ),
    "v3": DatasetVersionPaths(
        base_dataset="tennis_winner_dataset_v3.csv",
        atp_enriched_dataset="tennis_winner_dataset_atp_enriched_v3.csv",
        with_odds_dataset="tennis_winner_dataset_with_odds_v3.csv",
    ),
}

MODEL_VERSIONS: dict[ModelVersion, ModelVersionPaths] = {
    "v1": ModelVersionPaths(
        version="v1",
        datasets=DATASET_VERSIONS["v1"],
        models_dir=MODELS_DIR,
        metrics_filename="baseline_metrics.json",
        rank_features_note="Uses rank_diff placeholder (9999) and ATP enrichment ranks when available.",
    ),
    "v2": ModelVersionPaths(
        version="v2",
        datasets=DATASET_VERSIONS["v2"],
        models_dir=MODELS_DIR / "v2",
        metrics_filename="baseline_v2_metrics.json",
        rank_features_note=(
            "Uses historical ATP rank columns player_*_rank and rank_diff/rank_points_diff. "
            "ATP enrichment rank columns are excluded from v2 training."
        ),
    ),
    "v3": ModelVersionPaths(
        version="v3",
        datasets=DATASET_VERSIONS["v3"],
        models_dir=MODELS_DIR / "v3",
        metrics_filename="baseline_v3_metrics.json",
        rank_features_note=(
            "Uses v2 historical ATP rank/Elo/form/H2H features plus pre-match "
            "match-winner odds aggregates. Trains and predicts only when odds are available."
        ),
    ),
}


def dataset_candidates(version: ModelVersion) -> list[str]:
    paths = DATASET_VERSIONS[version]
    return [
        paths.with_odds_dataset,
        paths.atp_enriched_dataset,
        paths.base_dataset,
    ]


def select_training_dataset_path(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    version: ModelVersion = "v2",
) -> Path:
    base_path = Path(processed_dir)
    for filename in dataset_candidates(version):
        candidate = base_path / filename
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"Nessun dataset training trovato per versione {version} in {base_path}."
    )
