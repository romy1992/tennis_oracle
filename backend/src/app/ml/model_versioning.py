"""Central paths and metadata for versioned ML artifacts."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

# Match-winner tags (v1-v4) and extra-market labels such as first_set_winner_v2.
_SAFE_ARTIFACT_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

ModelVersion = Literal["v1", "v2", "v3", "v4"]

# Versions whose model trains/predicts only on fixtures with pre-match market
# odds available (v3 and v4 share the same odds-aware feature set).
ODDS_REQUIRED_VERSIONS: frozenset[str] = frozenset({"v3", "v4"})

# Match-winner versions that are still "live": triggered by the global-update
# orchestrator (cron/UI "Aggiorna tutto") and offered in the FE version pickers.
# v1-v3 are ARCHIVED, not deleted: code, training scripts, datasets and .pkl
# artifacts all stay on disk/in the repo for historical backtest/comparison,
# but they no longer run automatically and no longer appear as selectable
# options for new predictions. To bring one back temporarily (e.g. a
# side-by-side comparison), add it back here — no other code change needed,
# since `global_update.list_enabled_combinations` and the FE catalog
# (`GET /global-update/results` -> `catalog.versions`) both derive from this.
DEFAULT_ACTIVE_MATCH_WINNER_VERSION: ModelVersion = "v4"
ACTIVE_MATCH_WINNER_VERSIONS: frozenset[ModelVersion] = frozenset(
    {DEFAULT_ACTIVE_MATCH_WINNER_VERSION}
)

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
    # v4 riusa esattamente lo stesso dataset/feature-set di v3 (Elo/rank/form/H2H +
    # quote di mercato): non è un nuovo dataset, ma un nuovo modello (ensemble
    # voting soft: logistic_regression + xgboost + hist_gradient_boosting tunati
    # nelle Fasi 1-4) addestrato sugli stessi dati.
    "v4": DatasetVersionPaths(
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
    "v4": ModelVersionPaths(
        version="v4",
        datasets=DATASET_VERSIONS["v4"],
        models_dir=MODELS_DIR / "v4",
        metrics_filename="baseline_v4_metrics.json",
        rank_features_note=(
            "Same features as v3 (Elo/rank/form/H2H + pre-match odds aggregates). "
            "Model: soft-voting ensemble of tuned logistic_regression + xgboost + "
            "hist_gradient_boosting (grid search Fasi 1-2, voting Fase 3, validato "
            "con walk-forward multi-finestra in Fase 5/5.2). Trains and predicts "
            "only when odds are available, same as v3."
        ),
    ),
}


def _require_safe_artifact_token(value: str, *, label: str) -> str:
    text = str(value).strip()
    if not _SAFE_ARTIFACT_TOKEN.fullmatch(text):
        raise ValueError(f"{label} non valido per artefatto calibrazione: {value}")
    return text


def calibrator_artifact_path(
    *,
    model_version: str,
    model_name: str,
    method: str,
    run_id: int,
    reports_dir: str | Path = REPORTS_DIR,
) -> Path:
    """Versioned calibrator pickle under reports (writable in Docker via REPORTS_HOST_PATH).

    Accepts match-winner tags and extra-market walk-forward labels. Tokens are
    restricted to filesystem-safe characters so a version string cannot escape
    the artifacts directory.
    """
    safe_version = _require_safe_artifact_token(model_version, label="Versione modello")
    safe_model = _require_safe_artifact_token(model_name, label="Nome modello")
    safe_method = _require_safe_artifact_token(method, label="Metodo calibrazione")
    artifacts_dir = Path(reports_dir) / "calibration" / "artifacts"
    return artifacts_dir / (
        f"calibration_run_{run_id}_{safe_version}_{safe_model}_{safe_method}.pkl"
    )


def dataset_candidates(version: ModelVersion) -> list[str]:
    paths = DATASET_VERSIONS[version]
    filenames = [
        paths.with_odds_dataset,
        paths.atp_enriched_dataset,
        paths.base_dataset,
    ]
    # Prefer the ordinary CSV during local development, while also accepting
    # its gzip-compressed equivalent in lean cloud images. pandas.read_csv
    # infers gzip compression from the suffix transparently.
    return [
        candidate
        for filename in filenames
        for candidate in (filename, f"{filename}.gz")
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
        f"Nessun dataset training trovato per versione {version} in {base_path}. "
        "Genera i CSV (build_dataset) oppure, in Docker, monta "
        "PROCESSED_HOST_PATH=./backend/data/processed sul servizio api/job."
    )
