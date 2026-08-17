"""Training del modello FINALE (produzione) per il mercato Over/Under Games.

Analogo a ``train_first_set_winner_final_model.py`` ma per il mercato
Over/Under sul totale game in partita (linea di riferimento 20.5 — la piu'
diffusa, vedi ``over_under_games_odds_builder.py``). Alleva su TUTTO lo
storico disponibile con quote O/U valide per questa linea (in pratica il
periodo maturo: la copertura sistematica esiste solo da fine 2024, vedi
``over_under_games_walk_forward_mature_results.json``) e salva il pickle.

Modello scelto: ``random_forest`` (walk-forward periodo maturo: ROC AUC
0.570-0.583 a seconda della finestra, sostanzialmente alla pari col mercato
reale — vedi ``data/reports/over_under_games_walk_forward_mature_results.json``
e ``over_under_games_walk_forward_results.json``).

NON tocca train_baseline.py ne' model_registry.json: cartella dedicata
(``MODELS_DIR / "over_under_games_v1"``), separata dai modelli match-winner.

Uso (da repo root, richiede DB)::

    python -m backend.src.app.ml.training.train_over_under_games_final_model
    python -m backend.src.app.ml.training.train_over_under_games_final_model --line 20.5
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

from backend.src.app.ml.datasets.over_under_games_odds_builder import DEFAULT_LINE, OVER_UNDER_ODDS_FEATURE_COLUMNS
from backend.src.app.ml.model_versioning import MODELS_DIR, PROCESSED_DATA_DIR
from backend.src.app.ml.training.train_baseline import build_preprocessor, selected_feature_columns
from backend.src.app.ml.training.train_over_under_games import (
    OVER_UNDER_TARGET_COLUMN,
    build_over_under_games_dataframe,
)
from backend.src.app.ml.training.walk_forward import _date_max, _date_min, _estimators, prepare_temporal_dataframe

logger = logging.getLogger(__name__)

FINAL_MODEL_NAME = "random_forest"
FINAL_MODEL_DIR_NAME = "over_under_games_v1"
FINAL_MODEL_METADATA_FILENAME = "model_metadata.json"


def train_final_over_under_games_model(
    db: Session,
    *,
    line: float = DEFAULT_LINE,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    models_dir: str | Path = MODELS_DIR,
    random_state: int = 42,
) -> dict[str, Any]:
    """Alleva random_forest su tutte le righe con quote O/U valide per
    ``line`` e salva il pickle. Ritorna il dict di metadata (persistito anche
    come JSON accanto al .pkl)."""
    from sklearn.pipeline import Pipeline

    merged, dataset_path = build_over_under_games_dataframe(db, line=line, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=OVER_UNDER_TARGET_COLUMN, model_version="v3",
    )
    if "avg_over_odds" in dataframe.columns and "avg_under_odds" in dataframe.columns:
        has_odds = (
            pd.to_numeric(dataframe["avg_over_odds"], errors="coerce").notna()
            & pd.to_numeric(dataframe["avg_under_odds"], errors="coerce").notna()
        )
        dataframe = dataframe.loc[has_odds].reset_index(drop=True)
    if dataframe.empty:
        raise ValueError("Nessuna riga valida per allenare il modello finale (over/under games).")

    feature_columns = selected_feature_columns(dataframe, model_version="v3") + [
        column for column in OVER_UNDER_ODDS_FEATURE_COLUMNS if column in dataframe.columns
    ]
    if not feature_columns:
        raise ValueError("Nessuna feature pre-match disponibile.")

    x = dataframe[feature_columns]
    y = dataframe[OVER_UNDER_TARGET_COLUMN].astype(int)

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
                "line": line,
            },
            model_file,
        )

    metadata: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": "over_under_games",
        "line": line,
        "model_dir_name": FINAL_MODEL_DIR_NAME,
        "model_name": FINAL_MODEL_NAME,
        "target_column": OVER_UNDER_TARGET_COLUMN,
        "base_feature_set_version": "v3",
        "feature_columns": feature_columns,
        "feature_columns_count": len(feature_columns),
        "training_rows": int(len(dataframe)),
        "date_min": _date_min(dataframe),
        "date_max": _date_max(dataframe),
        "model_path": str(model_path),
        "dataset_path": str(dataset_path),
        "walk_forward_reference": (
            "data/reports/over_under_games_walk_forward_mature_results.json "
            "(random_forest ROC AUC ~0.57 medio sui fold del periodo maturo; "
            "market_no_vig, quote reali, ~0.58)"
        ),
        "notes": [
            "Allenato su tutto lo storico con quote O/U valide per questa linea "
            "(in pratica il periodo maturo: copertura sistematica solo da fine "
            "2024, vedi over_under_games_odds_builder.py). Nessun holdout: "
            "questo e' il modello di produzione, la stima di performance attesa "
            "resta quella del report walk-forward citato sopra.",
            "NON tocca train_baseline.py ne' model_registry.json: cartella "
            "dedicata separata dai modelli match-winner ufficiali (v1-v4).",
        ],
    }
    metadata_path = output_dir / FINAL_MODEL_METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, ensure_ascii=False, default=str)
    metadata["metadata_path"] = str(metadata_path)
    return metadata


def format_final_model_summary(metadata: dict[str, Any]) -> str:
    lines = [
        f"Modello finale allenato — {metadata['market']} (linea {metadata['line']})",
        f"  Modello: {metadata['model_name']} (feature-set {metadata['base_feature_set_version']})",
        f"  Righe di training: {metadata['training_rows']} ({metadata['date_min']} - {metadata['date_max']})",
        f"  Feature usate: {metadata['feature_columns_count']}",
        f"  Salvato in: {metadata['model_path']}",
        f"  Metadata: {metadata['metadata_path']}",
        f"  Riferimento walk-forward: {metadata['walk_forward_reference']}",
    ]
    return "\n".join(lines)


def main() -> None:
    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Allena e salva il modello FINALE (produzione) per il mercato Over/Under Games."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--models-dir", default=str(MODELS_DIR))
    parser.add_argument("--line", type=float, default=DEFAULT_LINE)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with SessionLocal() as db:
        metadata = train_final_over_under_games_model(
            db, line=args.line, processed_dir=args.processed_dir, models_dir=args.models_dir,
        )
    print(format_final_model_summary(metadata))


if __name__ == "__main__":
    main()

