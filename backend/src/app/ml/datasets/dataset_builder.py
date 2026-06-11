from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models import FeatureSnapshot


TARGET_COLUMN = "target_player_1_win"
EXCLUDED_FEATURE_COLUMNS = {
    "id",
    "match_id",
    "player_1_id",
    "player_2_id",
    "feature_date",
    "created_at",
    TARGET_COLUMN,
}


def load_feature_snapshots(db: Session) -> list[FeatureSnapshot]:
    stmt = select(FeatureSnapshot).order_by(
        FeatureSnapshot.feature_date.asc(),
        FeatureSnapshot.match_id.asc(),
    )
    return list(db.scalars(stmt).all())


def feature_snapshots_to_dataframe(snapshots: list[FeatureSnapshot]) -> pd.DataFrame:
    rows = [
        {
            column.name: getattr(snapshot, column.name)
            for column in FeatureSnapshot.__table__.columns
        }
        for snapshot in snapshots
    ]
    return pd.DataFrame(rows)


def build_dataset_dataframe(db: Session) -> pd.DataFrame:
    return feature_snapshots_to_dataframe(load_feature_snapshots(db))


def split_features_target(
    dataframe: pd.DataFrame,
    target_column: str = TARGET_COLUMN,
) -> tuple[pd.DataFrame, pd.Series]:
    if target_column not in dataframe.columns:
        raise ValueError(f"Target column '{target_column}' not found in dataframe.")
    feature_columns = [
        column
        for column in dataframe.columns
        if column not in EXCLUDED_FEATURE_COLUMNS
    ]
    return dataframe[feature_columns], dataframe[target_column]


def export_dataset_csv(
    dataframe: pd.DataFrame,
    output_dir: str | Path = "data/processed",
    filename: str = "tennis_features.csv",
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    csv_path = output_path / filename
    dataframe.to_csv(csv_path, index=False)
    return csv_path


def build_and_export_dataset(
    db: Session,
    output_dir: str | Path = "data/processed",
    filename: str = "tennis_features.csv",
) -> Path:
    dataframe = build_dataset_dataframe(db)
    return export_dataset_csv(dataframe, output_dir=output_dir, filename=filename)
