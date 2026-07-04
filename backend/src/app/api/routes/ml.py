import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.src.app.core.config import ROOT_DIR
from backend.src.app.db.session import get_db
from backend.src.app.ml.model_versioning import (
    COMPARISON_PATH,
    DATASET_VERSIONS,
    MODEL_VERSIONS,
    REGISTRY_PATH,
)
from backend.src.entity import Fixture


router = APIRouter(prefix="/ml", tags=["ml"])

PROCESSED_DATA_DIR = ROOT_DIR / "data" / "processed"
BASE_DATASET_PATH = PROCESSED_DATA_DIR / "tennis_winner_dataset.csv"
ATP_DATASET_PATH = PROCESSED_DATA_DIR / "tennis_winner_dataset_atp_enriched.csv"
ATP_NORMALIZED_MATCHES_PATH = PROCESSED_DATA_DIR / "atp_singles_matches_normalized.csv"
ATP_MATCH_MAPPING_PATH = PROCESSED_DATA_DIR / "atp_singles_match_mapping.csv"
ATP_PLAYER_MAPPING_PATH = PROCESSED_DATA_DIR / "atp_singles_player_mapping.csv"
ODDS_DATASET_PATH = PROCESSED_DATA_DIR / "tennis_match_winner_odds.csv"
DATASET_WITH_ODDS_PATH = PROCESSED_DATA_DIR / "tennis_winner_dataset_with_odds.csv"
MODELS_DIR = ROOT_DIR / "data" / "models"
REPORTS_DIR = ROOT_DIR / "data" / "reports"
BASELINE_METRICS_PATH = REPORTS_DIR / "baseline_metrics.json"
BASELINE_V2_METRICS_PATH = REPORTS_DIR / "baseline_v2_metrics.json"

DatasetType = Literal["base", "atp_enriched", "v2", "v2_atp_enriched"]
ModelVersion = Literal["v1", "v2"]
V2_DATASET_PATH = PROCESSED_DATA_DIR / DATASET_VERSIONS["v2"].base_dataset
V2_ATP_DATASET_PATH = PROCESSED_DATA_DIR / DATASET_VERSIONS["v2"].atp_enriched_dataset
V2_WITH_ODDS_PATH = PROCESSED_DATA_DIR / DATASET_VERSIONS["v2"].with_odds_dataset
PREVIEW_COLUMNS = [
    "match_id",
    "match_date",
    "surface",
    "player_1_id",
    "player_2_id",
    "rank_diff",
    "elo_diff",
    "surface_elo_diff",
    "rank_points_diff",
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "target_player_1_win",
    "atp_match_found",
    "player_1_atp_rank",
    "player_2_atp_rank",
    "atp_rank_diff",
]


def _completed_singles_filter():
    return and_(
        Fixture.event_date.is_not(None),
        Fixture.first_player_key.is_not(None),
        Fixture.second_player_key.is_not(None),
        Fixture.event_winner.in_(["First Player", "Second Player"]),
        Fixture.event_final_result.is_not(None),
        Fixture.event_final_result != "-",
        Fixture.event_type_type.ilike("%singles%"),
        ~Fixture.event_type_type.ilike("%doubles%"),
        ~Fixture.event_type_type.ilike("%teams%"),
    )


def _path_payload(path: Path) -> str:
    return f"backend/{path.relative_to(ROOT_DIR).as_posix()}"


def _dataset_path(dataset_type: DatasetType) -> Path:
    if dataset_type == "v2":
        return V2_DATASET_PATH
    if dataset_type == "v2_atp_enriched":
        return V2_ATP_DATASET_PATH
    if dataset_type == "atp_enriched":
        return ATP_DATASET_PATH
    return BASE_DATASET_PATH


def _select_dataset_type(dataset: DatasetType | None = None) -> DatasetType:
    if dataset:
        return dataset
    if V2_ATP_DATASET_PATH.exists():
        return "v2_atp_enriched"
    if ATP_DATASET_PATH.exists():
        return "atp_enriched"
    if V2_DATASET_PATH.exists():
        return "v2"
    return "base"


def _metrics_path_for_version(version: ModelVersion) -> Path:
    return REPORTS_DIR / MODEL_VERSIONS[version].metrics_filename


def _models_dir_for_version(version: ModelVersion) -> Path:
    return MODEL_VERSIONS[version].models_dir


def _count_csv_rows(path: Path) -> int | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return max(sum(1 for _ in csv_file) - 1, 0)


def _read_csv_columns(path: Path) -> list[str]:
    if not path.exists():
        return []
    return list(pd.read_csv(path, nrows=0).columns)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _records_json_safe(dataframe: pd.DataFrame) -> list[dict[str, Any]]:
    clean = dataframe.astype(object).where(pd.notna(dataframe), None)
    return [
        {key: _json_safe(value) for key, value in row.items()}
        for row in clean.to_dict(orient="records")
    ]


def _target_distribution(dataframe: pd.DataFrame) -> dict[str, int]:
    if "target_player_1_win" not in dataframe.columns:
        return {}

    counts = dataframe["target_player_1_win"].value_counts(dropna=False).to_dict()
    return {
        "null" if pd.isna(key) else str(int(key) if isinstance(key, float) and key.is_integer() else key): int(value)
        for key, value in counts.items()
    }


def _date_range(dataframe: pd.DataFrame) -> tuple[str | None, str | None]:
    if "match_date" not in dataframe.columns:
        return None, None

    dates = pd.to_datetime(dataframe["match_date"], errors="coerce")
    if dates.dropna().empty:
        return None, None

    return dates.min().date().isoformat(), dates.max().date().isoformat()


def _date_max_from_csv(path: Path) -> str | None:
    if not path.exists() or "match_date" not in _read_csv_columns(path):
        return None

    dates = pd.read_csv(path, usecols=["match_date"])
    parsed_dates = pd.to_datetime(dates["match_date"], errors="coerce")
    if parsed_dates.dropna().empty:
        return None
    return parsed_dates.max().date().isoformat()


def _date_min_max_from_csv(path: Path) -> tuple[str | None, str | None]:
    if not path.exists() or "match_date" not in _read_csv_columns(path):
        return None, None

    dates = pd.read_csv(path, usecols=["match_date"])
    parsed_dates = pd.to_datetime(dates["match_date"], errors="coerce")
    if parsed_dates.dropna().empty:
        return None, None
    return parsed_dates.min().date().isoformat(), parsed_dates.max().date().isoformat()


def _last_modified(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as json_file:
        return json.load(json_file)


def _atp_matched_rows(path: Path = ATP_DATASET_PATH) -> int | None:
    if not path.exists() or "atp_match_found" not in _read_csv_columns(path):
        return None

    matches = pd.read_csv(path, usecols=["atp_match_found"])
    return int(pd.to_numeric(matches["atp_match_found"], errors="coerce").fillna(0).sum())


def _coverage_pct(matched_rows: int | None, total_rows: int | None) -> float | None:
    if matched_rows is None or not total_rows:
        return None
    return round((matched_rows / total_rows) * 100, 2)


def _top_bookmakers_from_csv(path: Path, limit: int = 10) -> dict[str, int]:
    if not path.exists() or "bookmaker" not in _read_csv_columns(path):
        return {}
    bookmakers = pd.read_csv(path, usecols=["bookmaker"])
    return {
        str(bookmaker): int(count)
        for bookmaker, count in bookmakers["bookmaker"].value_counts().head(limit).items()
    }


def _baseline_comparison(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    model_labels = {
        "logistic_regression": "Logistic Regression",
        "random_forest": "Random Forest",
    }
    for key, label in model_labels.items():
        model_metrics = metrics.get("models", {}).get(key)
        if not model_metrics:
            continue
        rows.append({"model": label, **model_metrics})

    market = metrics.get("market_benchmark")
    if market:
        rows.append(
            {
                "model": "Market benchmark",
                "accuracy": market.get("market_accuracy"),
                "precision": None,
                "recall": None,
                "f1": None,
                "roc_auc": market.get("market_roc_auc"),
                "log_loss": market.get("market_log_loss"),
            }
        )
    return rows


def _metrics_payload(metrics_path: Path) -> dict[str, Any]:
    metrics = _read_json(metrics_path)
    if metrics is None:
        return {
            "exists": False,
            "metrics_path": _path_payload(metrics_path),
            "dataset_used": None,
            "split": None,
            "logistic_regression": None,
            "random_forest": None,
            "market_benchmark": None,
            "comparison": [],
            "warnings": [f"Report {metrics_path.name} mancante."],
        }

    return {
        "exists": True,
        "metrics_path": _path_payload(metrics_path),
        "last_modified": _last_modified(metrics_path),
        "model_version": metrics.get("model_version"),
        "dataset_used": metrics.get("dataset_used"),
        "rows_total": metrics.get("rows_total"),
        "columns_total": metrics.get("columns_total"),
        "date_min": metrics.get("date_min"),
        "date_max": metrics.get("date_max"),
        "split": metrics.get("split"),
        "features_used": metrics.get("features_used", []),
        "features_excluded": metrics.get("features_excluded", []),
        "rank_features_note": metrics.get("rank_features_note"),
        "logistic_regression": metrics.get("models", {}).get("logistic_regression"),
        "random_forest": metrics.get("models", {}).get("random_forest"),
        "market_benchmark": metrics.get("market_benchmark"),
        "comparison": _baseline_comparison(metrics),
        "warnings": [],
    }


@router.get("/pipeline/summary")
def read_ml_pipeline_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    warnings = [
        "Odds non ancora integrate nel dataset ML.",
        "Ranking legacy non usato perché non storico.",
    ]

    try:
        fixture_total = db.scalar(select(func.count()).select_from(Fixture))
        fixture_completed_singles = db.scalar(
            select(func.count()).select_from(Fixture).where(_completed_singles_filter())
        )
    except SQLAlchemyError as exc:
        fixture_total = None
        fixture_completed_singles = None
        warnings.append(f"Impossibile leggere la tabella fixture: {exc.__class__.__name__}.")

    dataset_base_exists = BASE_DATASET_PATH.exists()
    dataset_atp_exists = ATP_DATASET_PATH.exists()
    if not dataset_base_exists:
        warnings.append("Dataset base mancante.")
    if not dataset_atp_exists:
        warnings.append("Dataset ATP enriched mancante.")

    dataset_base_rows = _count_csv_rows(BASE_DATASET_PATH)
    dataset_atp_rows = _count_csv_rows(ATP_DATASET_PATH)
    atp_matched_rows = _atp_matched_rows()
    atp_coverage_pct = _coverage_pct(atp_matched_rows, dataset_base_rows)
    selected_dataset_path = ATP_DATASET_PATH if dataset_atp_exists else BASE_DATASET_PATH

    return {
        "fixture_total": fixture_total,
        "fixture_completed_singles": fixture_completed_singles,
        "dataset_base_exists": dataset_base_exists,
        "dataset_base_path": _path_payload(BASE_DATASET_PATH),
        "dataset_base_rows": dataset_base_rows,
        "dataset_atp_exists": dataset_atp_exists,
        "dataset_atp_path": _path_payload(ATP_DATASET_PATH),
        "dataset_atp_rows": dataset_atp_rows,
        "dataset_latest_match_date": _date_max_from_csv(selected_dataset_path),
        "atp_matched_rows": atp_matched_rows,
        "atp_coverage_pct": atp_coverage_pct,
        "atp_singles_matches_exists": ATP_NORMALIZED_MATCHES_PATH.exists(),
        "atp_singles_matches_path": _path_payload(ATP_NORMALIZED_MATCHES_PATH),
        "atp_singles_matches_rows": _count_csv_rows(ATP_NORMALIZED_MATCHES_PATH),
        "atp_match_mapping_exists": ATP_MATCH_MAPPING_PATH.exists(),
        "atp_match_mapping_path": _path_payload(ATP_MATCH_MAPPING_PATH),
        "atp_match_mapping_rows": _count_csv_rows(ATP_MATCH_MAPPING_PATH),
        "atp_player_mapping_exists": ATP_PLAYER_MAPPING_PATH.exists(),
        "atp_player_mapping_path": _path_payload(ATP_PLAYER_MAPPING_PATH),
        "atp_player_mapping_rows": _count_csv_rows(ATP_PLAYER_MAPPING_PATH),
        "warnings": warnings,
    }


@router.get("/dataset/summary")
def read_ml_dataset_summary(
    dataset: DatasetType | None = Query(default=None),
) -> dict[str, Any]:
    dataset_type = _select_dataset_type(dataset)
    path = _dataset_path(dataset_type)

    if not path.exists():
        return {
            "dataset_type": dataset_type,
            "path": _path_payload(path),
            "exists": False,
            "rows": 0,
            "columns": 0,
            "date_min": None,
            "date_max": None,
            "target_distribution": {},
            "null_counts": {},
            "available_columns": [],
            "warnings": [f"Dataset {dataset_type} mancante."],
        }

    dataframe = pd.read_csv(path, low_memory=False)
    date_min, date_max = _date_range(dataframe)

    return {
        "dataset_type": dataset_type,
        "path": _path_payload(path),
        "exists": True,
        "rows": int(len(dataframe)),
        "columns": int(len(dataframe.columns)),
        "date_min": date_min,
        "date_max": date_max,
        "target_distribution": _target_distribution(dataframe),
        "null_counts": {column: int(count) for column, count in dataframe.isna().sum().items()},
        "available_columns": list(dataframe.columns),
        "warnings": [],
    }


@router.get("/dataset/preview")
def read_ml_dataset_preview(
    limit: int = Query(default=50, ge=1, le=200),
    dataset: DatasetType | None = Query(default=None),
) -> dict[str, Any]:
    dataset_type = _select_dataset_type(dataset)
    path = _dataset_path(dataset_type)

    if not path.exists():
        return {
            "dataset_type": dataset_type,
            "rows": 0,
            "columns": [],
            "data": [],
            "warnings": [f"Dataset {dataset_type} mancante."],
        }

    available_columns = _read_csv_columns(path)
    preview_columns = [column for column in PREVIEW_COLUMNS if column in available_columns]
    if not preview_columns:
        return {
            "dataset_type": dataset_type,
            "rows": 0,
            "columns": [],
            "data": [],
            "warnings": ["Nessuna colonna preview disponibile nel dataset selezionato."],
        }

    dataframe = pd.read_csv(path, nrows=limit, usecols=preview_columns)

    return {
        "dataset_type": dataset_type,
        "rows": int(len(dataframe)),
        "columns": preview_columns,
        "data": _records_json_safe(dataframe),
        "warnings": [],
    }


@router.get("/odds/summary")
def read_ml_odds_summary() -> dict[str, Any]:
    odds_csv_exists = ODDS_DATASET_PATH.exists()
    with_odds_dataset_exists = DATASET_WITH_ODDS_PATH.exists()
    odds_rows = _count_csv_rows(ODDS_DATASET_PATH)
    with_odds_dataset_rows = _count_csv_rows(DATASET_WITH_ODDS_PATH)
    date_min, date_max = _date_min_max_from_csv(ODDS_DATASET_PATH)

    if odds_csv_exists:
        columns = _read_csv_columns(ODDS_DATASET_PATH)
        unique_matches = None
        unique_bookmakers = None
        if {"match_id", "bookmaker"}.issubset(columns):
            summary_columns = pd.read_csv(ODDS_DATASET_PATH, usecols=["match_id", "bookmaker"])
            unique_matches = int(summary_columns["match_id"].nunique())
            unique_bookmakers = int(summary_columns["bookmaker"].nunique())
        top_bookmakers = _top_bookmakers_from_csv(ODDS_DATASET_PATH)
    else:
        unique_matches = None
        unique_bookmakers = None
        top_bookmakers = {}

    coverage_pct = _coverage_pct(unique_matches, _count_csv_rows(DATASET_WITH_ODDS_PATH))

    return {
        "odds_csv_exists": odds_csv_exists,
        "odds_csv_path": _path_payload(ODDS_DATASET_PATH),
        "odds_rows": odds_rows,
        "unique_matches": unique_matches,
        "unique_bookmakers": unique_bookmakers,
        "top_bookmakers": top_bookmakers,
        "date_min": date_min,
        "date_max": date_max,
        "with_odds_dataset_exists": with_odds_dataset_exists,
        "with_odds_dataset_path": _path_payload(DATASET_WITH_ODDS_PATH),
        "with_odds_dataset_rows": with_odds_dataset_rows,
        "odds_coverage_pct": coverage_pct,
        "warnings": [] if odds_csv_exists else ["CSV odds match winner mancante."],
    }


@router.get("/models")
def read_ml_models() -> dict[str, Any]:
    versions = []
    for version in ("v1", "v2"):
        models_dir = _models_dir_for_version(version)  # type: ignore[arg-type]
        metrics_path = _metrics_path_for_version(version)  # type: ignore[arg-type]
        model_specs = {
            "logistic_regression": models_dir / "logistic_regression.pkl",
            "random_forest": models_dir / "random_forest.pkl",
        }
        versions.append(
            {
                "version": version,
                "models": [
                    {
                        "name": name,
                        "available": path.exists(),
                        "path": _path_payload(path),
                        "last_modified": _last_modified(path),
                    }
                    for name, path in model_specs.items()
                ],
                "metrics_path": _path_payload(metrics_path),
                "metrics_exists": metrics_path.exists(),
            }
        )

    legacy_models = versions[0]["models"] if versions else []
    return {
        "versions": versions,
        "models": legacy_models,
        "baseline_metrics_path": _path_payload(BASELINE_METRICS_PATH),
        "baseline_metrics_exists": BASELINE_METRICS_PATH.exists(),
        "baseline_v2_metrics_path": _path_payload(BASELINE_V2_METRICS_PATH),
        "baseline_v2_metrics_exists": BASELINE_V2_METRICS_PATH.exists(),
        "model_registry_path": _path_payload(REGISTRY_PATH),
        "model_registry_exists": REGISTRY_PATH.exists(),
        "model_comparison_path": _path_payload(COMPARISON_PATH),
        "model_comparison_exists": COMPARISON_PATH.exists(),
    }


@router.get("/models/registry")
def read_ml_model_registry() -> dict[str, Any]:
    registry = _read_json(REGISTRY_PATH)
    if registry is None:
        return {
            "exists": False,
            "versions": [],
            "planned_versions": [{"id": "v3", "label": "Boosting/tuning", "status": "planned"}],
            "warnings": ["model_registry.json mancante."],
        }
    return {
        "exists": True,
        "versions": registry.get("versions", []),
        "planned_versions": registry.get("planned_versions", []),
        "warnings": [],
    }


@router.get("/models/{version}/metrics")
def read_ml_version_metrics(version: ModelVersion) -> dict[str, Any]:
    metrics_path = _metrics_path_for_version(version)
    payload = _metrics_payload(metrics_path)
    payload["version"] = version
    return payload


@router.get("/models/baseline/metrics")
def read_ml_baseline_metrics(
    version: ModelVersion = Query(default="v1"),
) -> dict[str, Any]:
    metrics_path = _metrics_path_for_version(version)
    payload = _metrics_payload(metrics_path)
    payload["version"] = version
    return payload


@router.get("/models/comparison")
def read_ml_model_comparison() -> dict[str, Any]:
    comparison = _read_json(COMPARISON_PATH)
    if comparison is None:
        return {
            "exists": False,
            "versions": {},
            "warnings": ["model_comparison.json mancante."],
        }
    return {
        "exists": True,
        "generated_at": comparison.get("generated_at"),
        "versions": comparison.get("versions", {}),
        "warnings": [],
    }
