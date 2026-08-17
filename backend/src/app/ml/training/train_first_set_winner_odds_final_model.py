"""Training del modello FINALE (produzione) Vincitore 1° set con quote dedicate.

Alleva logistic_regression su tutto lo storico con quote ``Home/Away (1st Set)``
valide e salva in ``MODELS_DIR / "first_set_winner_v2"``. Non sovrascrive
``first_set_winner_v1`` (classificazione senza quote dedicate). Scelta
algoritmo: walk-forward quick (AUC ~0.732 / ROI ~-4.9% vs RF ~0.728 / ~-5.9%).

Uso (da repo root, richiede DB)::

    python -m backend.src.app.ml.training.train_first_set_winner_odds_final_model
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.first_set_winner_odds_builder import FIRST_SET_ODDS_FEATURE_COLUMNS
from backend.src.app.ml.model_versioning import MODELS_DIR, PROCESSED_DATA_DIR
from backend.src.app.ml.training.train_baseline import build_preprocessor, selected_feature_columns
from backend.src.app.ml.training.train_first_set_winner import FIRST_SET_TARGET_COLUMN
from backend.src.app.ml.training.train_first_set_winner_odds import (
    FIRST_SET_ODDS_MODEL_VERSION_LABEL,
    build_first_set_winner_odds_dataframe,
)
from backend.src.app.ml.training.walk_forward import _date_max, _date_min, _estimators, prepare_temporal_dataframe

logger = logging.getLogger(__name__)

FINAL_MODEL_NAME = "logistic_regression"
FINAL_MODEL_DIR_NAME = FIRST_SET_ODDS_MODEL_VERSION_LABEL
FINAL_MODEL_METADATA_FILENAME = "model_metadata.json"


def train_final_first_set_winner_odds_model(
    db: Session,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    models_dir: str | Path = MODELS_DIR,
    random_state: int = 42,
) -> dict[str, Any]:
    from sklearn.pipeline import Pipeline

    merged, dataset_path = build_first_set_winner_odds_dataframe(db, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=FIRST_SET_TARGET_COLUMN, model_version="v3",
    )
    if (
        "avg_first_set_player_1_odds" in dataframe.columns
        and "avg_first_set_player_2_odds" in dataframe.columns
    ):
        has_odds = (
            pd.to_numeric(dataframe["avg_first_set_player_1_odds"], errors="coerce").notna()
            & pd.to_numeric(dataframe["avg_first_set_player_2_odds"], errors="coerce").notna()
        )
        dataframe = dataframe.loc[has_odds].reset_index(drop=True)
    if dataframe.empty:
        raise ValueError("Nessuna riga valida per allenare first_set_winner_v2 (quote 1° set assenti).")

    feature_columns = selected_feature_columns(dataframe, model_version="v3") + [
        column for column in FIRST_SET_ODDS_FEATURE_COLUMNS if column in dataframe.columns
    ]
    if not feature_columns:
        raise ValueError("Nessuna feature pre-match disponibile.")

    x = dataframe[feature_columns]
    y = dataframe[FIRST_SET_TARGET_COLUMN].astype(int)

    estimators = _estimators(random_state)
    pipeline = Pipeline(
        steps=[
            ("preprocessor", build_preprocessor(dataframe, feature_columns)),
            ("model", estimators[FINAL_MODEL_NAME]),
        ]
    )
    pipeline.fit(x, y)

    output_dir = Path(models_dir) / FINAL_MODEL_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / f"{FINAL_MODEL_NAME}.pkl"
    with model_path.open("wb") as model_file:
        pickle.dump(
            {
                "pipeline": pipeline,
                "feature_columns": feature_columns,
                "dataset_path": str(dataset_path),
                "model_version": FINAL_MODEL_DIR_NAME,
            },
            model_file,
        )

    metadata: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": "first_set_winner",
        "provider_market": "Home/Away (1st Set)",
        "model_dir_name": FINAL_MODEL_DIR_NAME,
        "model_name": FINAL_MODEL_NAME,
        "target_column": FIRST_SET_TARGET_COLUMN,
        "base_feature_set_version": "v3",
        "feature_columns": feature_columns,
        "feature_columns_count": len(feature_columns),
        "training_rows": int(len(dataframe)),
        "date_min": _date_min(dataframe),
        "date_max": _date_max(dataframe),
        "model_path": str(model_path),
        "dataset_path": str(dataset_path),
        "walk_forward_reference": (
            "data/reports/first_set_winner_odds_walk_forward_results.json "
            "(quick expanding: logistic_regression AUC ~0.732, ROI ~-4.9% — "
            "scelto in produzione; random_forest AUC ~0.728, ROI ~-5.9%; "
            "market_no_vig 1st-set AUC ~0.736, ROI ~-5.7%)"
        ),
        "notes": [
            "Allenato su tutto lo storico con quote Home/Away (1st Set) valide. "
            "Nessun holdout: modello di produzione. La stima OOS resta il report "
            "walk-forward citato sopra.",
            "Produzione: logistic_regression (miglior AUC/ROI sul WF quick vs RF).",
            "Non sovrascrive first_set_winner_v1 (senza quote dedicate).",
        ],
    }
    metadata_path = output_dir / FINAL_MODEL_METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, ensure_ascii=False, default=str)
    metadata["metadata_path"] = str(metadata_path)
    return metadata


def format_final_model_summary(metadata: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Modello finale allenato — {metadata['market']} ({metadata['provider_market']})",
            f"  Modello: {metadata['model_name']} (feature-set {metadata['base_feature_set_version']})",
            f"  Righe di training: {metadata['training_rows']} ({metadata['date_min']} - {metadata['date_max']})",
            f"  Feature usate: {metadata['feature_columns_count']}",
            f"  Salvato in: {metadata['model_path']}",
            f"  Metadata: {metadata['metadata_path']}",
            f"  Riferimento walk-forward: {metadata['walk_forward_reference']}",
        ]
    )


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Allena e salva first_set_winner_v2 (quote 1° set dedicate)."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--models-dir", default=str(MODELS_DIR))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with SessionLocal() as db:
        metadata = train_final_first_set_winner_odds_model(
            db, processed_dir=args.processed_dir, models_dir=args.models_dir,
        )
    print(format_final_model_summary(metadata))


if __name__ == "__main__":
    main()
