import argparse
import json
import logging
import pickle
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.src.app.ml.datasets.odds_builder import roi  # noqa: E402
from backend.src.app.ml.model_versioning import (  # noqa: E402
    COMPARISON_PATH,
    MODEL_VERSIONS,
    PROCESSED_DATA_DIR,
    REGISTRY_PATH,
    REPORTS_DIR,
    select_training_dataset_path,
)
from backend.src.app.ml.training.value_bet_metrics import (  # noqa: E402
    DEFAULT_EDGE_THRESHOLD,
    compute_value_bet_metrics,
)


logger = logging.getLogger(__name__)

TARGET_COLUMN = "target_player_1_win"
DEFAULT_TEST_SIZE = 0.2

ALLOWED_FEATURE_COLUMNS_V1 = [
    "surface",
    "rank_diff",
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "player_1_surface_last_10_win_rate",
    "player_2_surface_last_10_win_rate",
    "player_1_matches_last_14_days",
    "player_2_matches_last_14_days",
    "player_1_days_since_last_match",
    "player_2_days_since_last_match",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "h2h_surface_player_1_wins",
    "h2h_surface_player_2_wins",
    "player_1_atp_rank",
    "player_2_atp_rank",
    "atp_rank_diff",
    "player_1_atp_rank_points",
    "player_2_atp_rank_points",
    "atp_rank_points_diff",
    "player_1_age",
    "player_2_age",
    "age_diff",
    "player_1_height",
    "player_2_height",
    "height_diff",
    "player_1_hand",
    "player_2_hand",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
    "atp_best_of",
    "atp_match_found",
]

ALLOWED_FEATURE_COLUMNS_V2 = [
    "surface",
    "rank_diff",
    "rank_points_diff",
    "elo_diff",
    "surface_elo_diff",
    "player_1_last_5_win_rate",
    "player_2_last_5_win_rate",
    "player_1_last_10_win_rate",
    "player_2_last_10_win_rate",
    "player_1_surface_last_10_win_rate",
    "player_2_surface_last_10_win_rate",
    "player_1_matches_last_14_days",
    "player_2_matches_last_14_days",
    "player_1_days_since_last_match",
    "player_2_days_since_last_match",
    "h2h_player_1_wins",
    "h2h_player_2_wins",
    "h2h_surface_player_1_wins",
    "h2h_surface_player_2_wins",
    "player_1_age",
    "player_2_age",
    "age_diff",
    "player_1_height",
    "player_2_height",
    "height_diff",
    "player_1_hand",
    "player_2_hand",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
    "atp_best_of",
    "atp_match_found",
]

ODDS_FEATURE_COLUMNS = [
    "avg_player_1_odds",
    "avg_player_2_odds",
    "avg_market_prob_player_1",
    "avg_market_prob_player_2",
    "avg_bookmaker_margin",
    "odds_bookmaker_count",
]

ALLOWED_FEATURE_COLUMNS_V3 = [
    *ALLOWED_FEATURE_COLUMNS_V2,
    *ODDS_FEATURE_COLUMNS,
]

LEAKAGE_EXCLUDED_COLUMNS = {
    TARGET_COLUMN,
    "match_id",
    "match_date",
    "player_1_id",
    "player_2_id",
    "player_1_rank",
    "player_2_rank",
    "player_1_rank_points",
    "player_2_rank_points",
    "player_1_elo",
    "player_2_elo",
    "player_1_surface_elo",
    "player_2_surface_elo",
    "player_1_atp_rank",
    "player_2_atp_rank",
    "atp_rank_diff",
    "player_1_atp_rank_points",
    "player_2_atp_rank_points",
    "atp_rank_points_diff",
    "atp_score",
    "atp_minutes",
    "avg_player_1_odds",
    "avg_player_2_odds",
    "market_prob_player_1",
    "market_prob_player_2",
    "avg_market_prob_player_1",
    "avg_market_prob_player_2",
    "avg_bookmaker_margin",
    "odds_bookmaker_count",
    "market_edge_baseline_player_1",
    "player_1_profit_if_bet",
    "player_2_profit_if_bet",
    "event_final_result",
    "event_game_result",
    "event_winner",
    "winner",
    "loser",
    "score",
    "result",
}

CATEGORICAL_FEATURES = {
    "surface",
    "player_1_hand",
    "player_2_hand",
    "atp_surface",
    "atp_tourney_level",
    "atp_round",
}


@dataclass(frozen=True)
class TemporalSplit:
    train: pd.DataFrame
    test: pd.DataFrame
    train_start: str | None
    train_end: str | None
    test_start: str | None
    test_end: str | None


@dataclass(frozen=True)
class TrainingResult:
    metrics_path: Path
    model_paths: dict[str, Path]
    metrics: dict[str, Any]
    model_version: str


def allowed_feature_columns(model_version: str) -> list[str]:
    if model_version in ("v3", "v4"):
        # v4 riusa esattamente lo stesso feature-set di v3 (ensemble, non nuove feature).
        return ALLOWED_FEATURE_COLUMNS_V3
    if model_version == "v2":
        return ALLOWED_FEATURE_COLUMNS_V2
    return ALLOWED_FEATURE_COLUMNS_V1


def leakage_excluded_columns(model_version: str = "v2") -> set[str]:
    if model_version in ("v3", "v4"):
        return LEAKAGE_EXCLUDED_COLUMNS.difference(ODDS_FEATURE_COLUMNS)
    return LEAKAGE_EXCLUDED_COLUMNS


def select_training_dataset(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    model_version: str = "v2",
) -> Path:
    return select_training_dataset_path(processed_dir, version=model_version)  # type: ignore[arg-type]


def temporal_train_test_split(
    dataframe: pd.DataFrame,
    date_column: str = "match_date",
    target_column: str = TARGET_COLUMN,
    test_size: float = DEFAULT_TEST_SIZE,
) -> TemporalSplit:
    if date_column not in dataframe.columns:
        raise ValueError(f"Colonna data mancante: {date_column}")
    if target_column not in dataframe.columns:
        raise ValueError(f"Colonna target mancante: {target_column}")
    if not 0 < test_size < 1:
        raise ValueError("test_size deve essere tra 0 e 1.")

    clean = dataframe.copy()
    clean[date_column] = pd.to_datetime(clean[date_column], errors="coerce")
    clean[target_column] = pd.to_numeric(clean[target_column], errors="coerce")
    clean = clean.dropna(subset=[date_column, target_column]).sort_values(date_column).reset_index(drop=True)
    clean[target_column] = clean[target_column].astype(int)
    if len(clean) < 2:
        raise ValueError("Dataset troppo piccolo per split train/test.")

    cutoff = int(len(clean) * (1 - test_size))
    cutoff = max(1, min(cutoff, len(clean) - 1))
    train = clean.iloc[:cutoff].copy()
    test = clean.iloc[cutoff:].copy()
    return TemporalSplit(
        train=train,
        test=test,
        train_start=_date_min(train, date_column),
        train_end=_date_max(train, date_column),
        test_start=_date_min(test, date_column),
        test_end=_date_max(test, date_column),
    )


def selected_feature_columns(
    dataframe: pd.DataFrame,
    model_version: str = "v2",
) -> list[str]:
    allowed = allowed_feature_columns(model_version)
    excluded = leakage_excluded_columns(model_version)
    return [
        column
        for column in allowed
        if column in dataframe.columns and column not in excluded
    ]


def excluded_feature_columns(
    dataframe: pd.DataFrame,
    selected_features: list[str],
    model_version: str = "v2",
) -> list[str]:
    allowed = set(allowed_feature_columns(model_version))
    selected = set(selected_features)
    excluded = leakage_excluded_columns(model_version)
    return [
        column
        for column in dataframe.columns
        if column not in selected and (column in excluded or column not in allowed)
    ]


def build_preprocessor(dataframe: pd.DataFrame, feature_columns: list[str]):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    categorical_columns = [
        column
        for column in feature_columns
        if column in CATEGORICAL_FEATURES or pd.api.types.is_object_dtype(dataframe[column])
    ]
    numeric_columns = [column for column in feature_columns if column not in categorical_columns]

    transformers = []
    if numeric_columns:
        transformers.append(
            (
                "numeric",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scaler", StandardScaler()),
                    ]
                ),
                numeric_columns,
            )
        )
    if categorical_columns:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    steps=[
                        ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
                        ("onehot", _one_hot_encoder()),
                    ]
                ),
                categorical_columns,
            )
        )
    return ColumnTransformer(transformers=transformers, remainder="drop")


def filter_rows_with_valid_odds(dataframe: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [column for column in ODDS_FEATURE_COLUMNS if column not in dataframe.columns]
    if missing_columns:
        raise ValueError(f"Dataset v3 senza colonne odds richieste: {missing_columns}")

    clean = dataframe.copy()
    numeric_odds = clean[ODDS_FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    mask = numeric_odds.notna().all(axis=1)
    mask &= numeric_odds["avg_player_1_odds"] > 1.0
    mask &= numeric_odds["avg_player_2_odds"] > 1.0
    mask &= numeric_odds["avg_market_prob_player_1"].between(0.0, 1.0)
    mask &= numeric_odds["avg_market_prob_player_2"].between(0.0, 1.0)
    mask &= numeric_odds["avg_bookmaker_margin"] >= 0.0
    mask &= numeric_odds["odds_bookmaker_count"] > 0
    return clean.loc[mask].reset_index(drop=True)


def train_baseline(
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    models_dir: str | Path | None = None,
    reports_dir: str | Path = REPORTS_DIR,
    test_size: float = DEFAULT_TEST_SIZE,
    model_version: str = "v2",
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
) -> TrainingResult:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    version_paths = MODEL_VERSIONS[model_version]  # type: ignore[index]
    dataset_path = select_training_dataset(processed_dir, model_version=model_version)
    dataframe = pd.read_csv(dataset_path, low_memory=False)
    rows_before_odds_filter = len(dataframe)
    if model_version in ("v3", "v4"):
        dataframe = filter_rows_with_valid_odds(dataframe)
        if dataframe.empty:
            raise ValueError(f"Dataset {model_version} senza righe con odds valide.")
    split = temporal_train_test_split(dataframe, test_size=test_size)
    feature_columns = selected_feature_columns(split.train, model_version=model_version)
    if not feature_columns:
        raise ValueError("Nessuna feature pre-match disponibile per il training baseline.")

    excluded_columns = excluded_feature_columns(dataframe, feature_columns, model_version=model_version)
    x_train = split.train[feature_columns]
    y_train = split.train[TARGET_COLUMN].astype(int)
    x_test = split.test[feature_columns]
    y_test = split.test[TARGET_COLUMN].astype(int)

    resolved_models_dir = Path(models_dir) if models_dir is not None else version_paths.models_dir
    reports_path = Path(reports_dir)
    resolved_models_dir.mkdir(parents=True, exist_ok=True)
    reports_path.mkdir(parents=True, exist_ok=True)

    estimators = {
        "logistic_regression": LogisticRegression(max_iter=2000, solver="lbfgs"),
        "random_forest": RandomForestClassifier(
            n_estimators=100,
            max_depth=14,
            min_samples_leaf=20,
            random_state=42,
            n_jobs=-1,
        ),
    }

    model_metrics: dict[str, Any] = {}
    model_paths: dict[str, Path] = {}
    for name, estimator in estimators.items():
        pipeline = Pipeline(
            steps=[
                ("preprocessor", build_preprocessor(split.train, feature_columns)),
                ("model", estimator),
            ]
        )
        pipeline.fit(x_train, y_train)
        probabilities = pipeline.predict_proba(x_test)[:, 1]
        predictions = (probabilities >= 0.5).astype(int)
        model_metrics[name] = classification_metrics(
            y_train,
            y_test,
            predictions,
            probabilities,
            split.test,
            edge_threshold=edge_threshold,
        )

        model_path = resolved_models_dir / f"{name}.pkl"
        with model_path.open("wb") as model_file:
            pickle.dump(
                {
                    "pipeline": pipeline,
                    "feature_columns": feature_columns,
                    "dataset_path": str(dataset_path),
                    "model_version": model_version,
                },
                model_file,
            )
        model_paths[name] = model_path

    metrics_filename = version_paths.metrics_filename
    metrics = {
        "model_version": model_version,
        "dataset_used": str(dataset_path),
        "rows_total": int(len(dataframe)),
        "rows_before_odds_filter": int(rows_before_odds_filter),
        "columns_total": int(len(dataframe.columns)),
        "date_min": _date_min(dataframe, "match_date"),
        "date_max": _date_max(dataframe, "match_date"),
        "split": {
            "strategy": "temporal",
            "test_size": test_size,
            "train_rows": int(len(split.train)),
            "test_rows": int(len(split.test)),
            "train_date_min": split.train_start,
            "train_date_max": split.train_end,
            "test_date_min": split.test_start,
            "test_date_max": split.test_end,
        },
        "features_used": feature_columns,
        "features_excluded": excluded_columns,
        "rank_features_note": version_paths.rank_features_note,
        "models": model_metrics,
        "market_benchmark": market_benchmark_metrics(split.test),
        "model_paths": {name: str(path) for name, path in model_paths.items()},
        "metrics_path": str(reports_path / metrics_filename),
    }
    if model_version in ("v3", "v4"):
        metrics["odds_filter"] = {
            "required": True,
            "rows_removed": int(rows_before_odds_filter - len(dataframe)),
            "required_columns": ODDS_FEATURE_COLUMNS,
        }

    metrics_path = reports_path / metrics_filename
    with metrics_path.open("w", encoding="utf-8") as metrics_file:
        json.dump(metrics, metrics_file, indent=2, ensure_ascii=False)

    write_model_comparison(reports_path)
    update_model_registry_entry(model_version, metrics_path, dataset_path, resolved_models_dir)

    return TrainingResult(
        metrics_path=metrics_path,
        model_paths=model_paths,
        metrics=metrics,
        model_version=model_version,
    )


def classification_metrics(
    y_train: pd.Series,
    y_test: pd.Series,
    predictions: Any,
    probabilities: Any,
    test_dataframe: pd.DataFrame,
    edge_threshold: float = DEFAULT_EDGE_THRESHOLD,
) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
    )

    probability_series = pd.Series(probabilities, index=test_dataframe.index)
    value_bets_overall = compute_value_bet_metrics(
        test_dataframe,
        probability_series,
        edge_threshold=edge_threshold,
    )
    odds_mask = _odds_available_mask(test_dataframe)
    value_bets_with_odds = compute_value_bet_metrics(
        test_dataframe.loc[odds_mask],
        probability_series.loc[odds_mask],
        edge_threshold=edge_threshold,
    )

    return {
        "accuracy": _round_metric(accuracy_score(y_test, predictions)),
        "precision": _round_metric(precision_score(y_test, predictions, zero_division=0)),
        "recall": _round_metric(recall_score(y_test, predictions, zero_division=0)),
        "f1": _round_metric(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": _safe_roc_auc(y_test, probabilities),
        "log_loss": _safe_log_loss(y_test, probabilities),
        "confusion_matrix": confusion_matrix(y_test, predictions, labels=[0, 1]).tolist(),
        "class_distribution_train": _class_distribution(y_train),
        "class_distribution_test": _class_distribution(y_test),
        "value_bet_overall": value_bets_overall,
        "value_bet_with_odds": value_bets_with_odds,
    }


def market_benchmark_metrics(test_dataframe: pd.DataFrame) -> dict[str, Any] | None:
    from sklearn.metrics import accuracy_score

    if "market_prob_player_1" in test_dataframe.columns:
        market_probability_column = "market_prob_player_1"
    elif "avg_market_prob_player_1" in test_dataframe.columns:
        market_probability_column = "avg_market_prob_player_1"
    else:
        return None

    required_columns = {TARGET_COLUMN, market_probability_column, "player_1_profit_if_bet"}
    if not required_columns.issubset(test_dataframe.columns):
        return None

    benchmark = test_dataframe[list(required_columns)].copy()
    benchmark[TARGET_COLUMN] = pd.to_numeric(benchmark[TARGET_COLUMN], errors="coerce")
    benchmark[market_probability_column] = pd.to_numeric(
        benchmark[market_probability_column],
        errors="coerce",
    )
    benchmark["player_1_profit_if_bet"] = pd.to_numeric(
        benchmark["player_1_profit_if_bet"],
        errors="coerce",
    )
    benchmark = benchmark.dropna(subset=[TARGET_COLUMN, market_probability_column])
    if benchmark.empty:
        return {
            "market_accuracy": None,
            "market_log_loss": None,
            "market_roc_auc": None,
            "market_profit_if_bet_player_1_all": 0.0,
            "market_roi_if_bet_player_1_all": 0.0,
            "odds_coverage_rows": 0,
            "odds_coverage_pct": 0.0,
        }

    y_test = benchmark[TARGET_COLUMN].astype(int)
    probabilities = benchmark[market_probability_column]
    predictions = (probabilities >= 0.5).astype(int)
    profits = benchmark["player_1_profit_if_bet"].dropna().tolist()

    return {
        "market_accuracy": _round_metric(accuracy_score(y_test, predictions)),
        "market_log_loss": _safe_log_loss(y_test, probabilities),
        "market_roc_auc": _safe_roc_auc(y_test, probabilities),
        "market_profit_if_bet_player_1_all": _round_metric(sum(profits)),
        "market_roi_if_bet_player_1_all": _round_metric(roi(profits)),
        "odds_coverage_rows": int(len(benchmark)),
        "odds_coverage_pct": _round_metric((len(benchmark) / len(test_dataframe)) * 100 if len(test_dataframe) else 0),
    }


def write_model_comparison(reports_dir: str | Path = REPORTS_DIR) -> Path:
    reports_path = Path(reports_dir)
    comparison: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "versions": {}}

    for version, version_paths in MODEL_VERSIONS.items():
        metrics_path = reports_path / version_paths.metrics_filename
        if not metrics_path.exists():
            continue
        with metrics_path.open("r", encoding="utf-8") as metrics_file:
            metrics = json.load(metrics_file)
        comparison["versions"][version] = {
            "metrics_path": str(metrics_path),
            "dataset_used": metrics.get("dataset_used"),
            "features_used": metrics.get("features_used", []),
            "rank_features_note": metrics.get("rank_features_note"),
            "models": metrics.get("models", {}),
            "market_benchmark": metrics.get("market_benchmark"),
        }

    comparison_path = reports_path / COMPARISON_PATH.name
    with comparison_path.open("w", encoding="utf-8") as comparison_file:
        json.dump(comparison, comparison_file, indent=2, ensure_ascii=False)
    return comparison_path


def update_model_registry_entry(
    model_version: str,
    metrics_path: Path,
    dataset_path: Path,
    models_dir: Path,
    registry_path: Path | None = None,
) -> None:
    resolved_registry_path = registry_path or REGISTRY_PATH
    registry = _load_registry(resolved_registry_path)
    now = datetime.now(timezone.utc).isoformat()
    version_paths = MODEL_VERSIONS[model_version]  # type: ignore[index]
    labels = {
        "v1": "Baseline form+H2H+ATP parziale",
        "v2": "Elo + ranking storico",
        "v3": "Odds-aware",
        "v4": "Ensemble voting (v3 features)",
    }
    descriptions = {
        "v1": "Primo baseline senza Elo/rank reali. Odds solo benchmark.",
        "v2": "Elo overall/surface pre-match + rank ATP storico. Odds benchmark/value bet.",
        "v3": (
            "Elo/rank/form/H2H come v2 con odds match-winner aggregate come feature ML. "
            "Training e inferenza solo su match con odds."
        ),
        "v4": (
            "Stesse feature di v3 (Elo/rank/form/H2H + odds). Modello: soft-voting ensemble "
            "di logistic_regression + xgboost + hist_gradient_boosting, iperparametri tunati "
            "via grid search (Fasi 1-2) e combinati in Fase 3. Validato con walk-forward "
            "multi-finestra (Fase 5/5.2): ROC AUC marginalmente superiore a v3, ROI value-bet "
            "piu' stabile nel tempo su finestre con storia matura (>=3 anni)."
        ),
    }
    entry = {
        "id": model_version,
        "label": labels.get(model_version, model_version),
        "description": descriptions.get(model_version, ""),
        "dataset": str(dataset_path),
        "features_summary": version_paths.rank_features_note,
        "models_path": str(models_dir),
        "metrics_path": str(metrics_path),
        "created_at": now,
        "updated_at": now,
    }

    versions = [item for item in registry.get("versions", []) if item.get("id") != model_version]
    versions.append(entry)
    versions.sort(key=lambda item: item.get("id", ""))
    registry["versions"] = versions
    if model_version == "v2":
        registry["planned_versions"] = [{"id": "v3", "label": "Boosting/tuning", "status": "planned"}]
    if model_version == "v3":
        registry["planned_versions"] = [
            item for item in registry.get("planned_versions", []) if item.get("id") != "v3"
        ]
    if model_version == "v4":
        registry["planned_versions"] = [
            item for item in registry.get("planned_versions", []) if item.get("id") != "v4"
        ]

    resolved_registry_path.parent.mkdir(parents=True, exist_ok=True)
    with resolved_registry_path.open("w", encoding="utf-8") as registry_file:
        json.dump(registry, registry_file, indent=2, ensure_ascii=False)


def _load_registry(registry_path: Path | None = None) -> dict[str, Any]:
    resolved = registry_path or REGISTRY_PATH
    if resolved.exists():
        with resolved.open("r", encoding="utf-8") as registry_file:
            return json.load(registry_file)
    return {"versions": []}


def format_training_summary(metrics: dict[str, Any]) -> str:
    lines = [
        f"Versione modello: {metrics.get('model_version')}",
        f"Dataset usato: {metrics['dataset_used']}",
        f"Righe totali: {metrics['rows_total']}",
        f"Colonne totali: {metrics['columns_total']}",
        f"Date min/max: {metrics['date_min']} / {metrics['date_max']}",
        f"Rank features: {metrics.get('rank_features_note')}",
        (
            "Split train/test: "
            f"{metrics['split']['train_rows']} / {metrics['split']['test_rows']} "
            f"({metrics['split']['train_date_min']} - {metrics['split']['train_date_max']} / "
            f"{metrics['split']['test_date_min']} - {metrics['split']['test_date_max']})"
        ),
        f"Feature usate: {metrics['features_used']}",
        f"Feature escluse: {metrics['features_excluded']}",
        f"Metriche finali: {metrics['models']}",
        f"Benchmark mercato: {metrics['market_benchmark']}",
        f"Path modelli salvati: {metrics['model_paths']}",
        f"Path report salvato: {metrics['metrics_path']}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Addestra baseline ML tennis winner con split temporale."
    )
    parser.add_argument(
        "--processed-dir",
        default=str(PROCESSED_DATA_DIR),
        help="Cartella dei dataset processati.",
    )
    parser.add_argument(
        "--models-dir",
        default=None,
        help="Cartella output modelli (default da --model-version).",
    )
    parser.add_argument(
        "--reports-dir",
        default=str(REPORTS_DIR),
        help="Cartella output report.",
    )
    parser.add_argument(
        "--test-size",
        type=float,
        default=DEFAULT_TEST_SIZE,
        help="Quota finale temporale usata come test set.",
    )
    parser.add_argument(
        "--model-version",
        choices=["v1", "v2", "v3"],
        default="v2",
        help="Versione modello/dataset da addestrare.",
    )
    parser.add_argument(
        "--edge-threshold",
        type=float,
        default=DEFAULT_EDGE_THRESHOLD,
        help="Soglia minima model_prob - market_prob per value bet.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    logger.info("Avvio training baseline (%s)", args.model_version)

    result = train_baseline(
        processed_dir=args.processed_dir,
        models_dir=args.models_dir,
        reports_dir=args.reports_dir,
        test_size=args.test_size,
        model_version=args.model_version,
        edge_threshold=args.edge_threshold,
    )
    print(format_training_summary(result.metrics))


def _odds_available_mask(test_dataframe: pd.DataFrame) -> pd.Series:
    if "market_prob_player_1" in test_dataframe.columns:
        market_column = "market_prob_player_1"
    elif "avg_market_prob_player_1" in test_dataframe.columns:
        market_column = "avg_market_prob_player_1"
    else:
        return pd.Series(False, index=test_dataframe.index)
    odds_column = "avg_player_1_odds" if "avg_player_1_odds" in test_dataframe.columns else None
    if odds_column is None:
        return pd.Series(False, index=test_dataframe.index)
    return test_dataframe[market_column].notna() & test_dataframe[odds_column].notna()


def _one_hot_encoder():
    from sklearn.preprocessing import OneHotEncoder

    try:
        return OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    except TypeError:
        return OneHotEncoder(handle_unknown="ignore", sparse=False)


def _safe_roc_auc(y_true: pd.Series, probabilities: Any) -> float | None:
    from sklearn.metrics import roc_auc_score

    if len(set(pd.Series(y_true).dropna().astype(int))) < 2:
        return None
    return _round_metric(roc_auc_score(y_true, probabilities))


def _safe_log_loss(y_true: pd.Series, probabilities: Any) -> float | None:
    from sklearn.metrics import log_loss

    try:
        return _round_metric(log_loss(y_true, probabilities, labels=[0, 1]))
    except ValueError:
        return None


def _class_distribution(values: pd.Series) -> dict[str, int]:
    counts = pd.Series(values).value_counts(dropna=False).to_dict()
    return {str(int(key)): int(value) for key, value in counts.items()}


def _date_min(dataframe: pd.DataFrame, column: str) -> str | None:
    if column not in dataframe.columns:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.min().date().isoformat()


def _date_max(dataframe: pd.DataFrame, column: str) -> str | None:
    if column not in dataframe.columns:
        return None
    dates = pd.to_datetime(dataframe[column], errors="coerce")
    if dates.dropna().empty:
        return None
    return dates.max().date().isoformat()


def _round_metric(value: Any) -> float:
    return round(float(value), 6)


# Backward-compatible aliases used by existing tests/imports.
ALLOWED_FEATURE_COLUMNS = ALLOWED_FEATURE_COLUMNS_V1
DATASET_CANDIDATES = [
    "tennis_winner_dataset_with_odds.csv",
    "tennis_winner_dataset_atp_enriched.csv",
    "tennis_winner_dataset.csv",
]
METRICS_FILENAME = "baseline_metrics.json"
MODELS_DIR = MODEL_VERSIONS["v1"].models_dir


if __name__ == "__main__":
    main()
