"""Training del modello FINALE (produzione) per il mercato Vincitore 1° set.

A differenza di ``train_first_set_winner.py`` (validazione walk-forward, MAI
salva nulla su disco), questo script alleva il modello su TUTTO lo storico
disponibile e lo salva come artifact pronto per l'inferenza — stesso formato
pickle di ``train_baseline.train_baseline`` (``{pipeline, feature_columns,
dataset_path, model_version}``), cosi' e' caricabile con lo stesso pattern di
``predictor._load_model_artifact`` (vedi ``extra_markets_predictor.py``).

Modello scelto: ``random_forest`` (walk-forward: ROC AUC 0.733, leggermente
migliore di logistic_regression 0.728 — vedi
``data/reports/first_set_winner_walk_forward_results.json``). Il benchmark
``market_no_vig`` (0.736, quote match-winner come proxy) resta lievemente
superiore ma non e' un modello allenabile/servibile in autonomia.

NON tocca ``train_baseline.py``, ``model_registry.json`` ne' i modelli
match-winner pubblici (v1-v4): salva in una cartella dedicata
(``MODELS_DIR / "first_set_winner_v1"``), separata da ``MODEL_VERSIONS``.

Uso (da repo root, richiede DB)::

    python -m backend.src.app.ml.training.train_first_set_winner_final_model
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.src.app.ml.model_versioning import MODELS_DIR, PROCESSED_DATA_DIR
from backend.src.app.ml.training.train_baseline import build_preprocessor, selected_feature_columns
from backend.src.app.ml.training.train_first_set_winner import (
    FIRST_SET_TARGET_COLUMN,
    build_first_set_winner_dataframe,
)
from backend.src.app.ml.training.walk_forward import _date_max, _date_min, _estimators, prepare_temporal_dataframe

logger = logging.getLogger(__name__)

FINAL_MODEL_NAME = "random_forest"
FINAL_MODEL_DIR_NAME = "first_set_winner_v1"
FINAL_MODEL_METADATA_FILENAME = "model_metadata.json"


def train_final_first_set_winner_model(
    db: Session,
    *,
    processed_dir: str | Path = PROCESSED_DATA_DIR,
    models_dir: str | Path = MODELS_DIR,
    random_state: int = 42,
) -> dict[str, Any]:
    """Alleva random_forest su TUTTO lo storico valido e salva il pickle.

    Ritorna il dict di metadata (anche persistito come JSON accanto al .pkl).
    """
    from sklearn.pipeline import Pipeline

    merged, dataset_path = build_first_set_winner_dataframe(db, processed_dir=processed_dir)
    dataframe = prepare_temporal_dataframe(
        merged, target_column=FIRST_SET_TARGET_COLUMN, model_version="v3",
    )
    if dataframe.empty:
        raise ValueError("Nessuna riga valida per allenare il modello finale (vincitore 1 set).")

    feature_columns = selected_feature_columns(dataframe, model_version="v3")
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
            "data/reports/first_set_winner_walk_forward_results.json "
            "(random_forest ROC AUC 0.733 medio sui fold completati; "
            "market_no_vig, proxy quote match-winner, 0.736)"
        ),
        "notes": [
            "Allenato su TUTTO lo storico disponibile (nessun holdout): questo e' il "
            "modello di produzione, non una validazione. La stima di performance "
            "attesa resta quella del report walk-forward citato sopra.",
            "NON tocca train_baseline.py ne' model_registry.json: cartella dedicata "
            "separata dai modelli match-winner ufficiali (v1-v4).",
        ],
    }
    metadata_path = output_dir / FINAL_MODEL_METADATA_FILENAME
    with metadata_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, ensure_ascii=False, default=str)
    metadata["metadata_path"] = str(metadata_path)
    return metadata


def format_final_model_summary(metadata: dict[str, Any]) -> str:
    lines = [
        f"Modello finale allenato — {metadata['market']}",
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
        description="Allena e salva il modello FINALE (produzione) per il mercato Vincitore 1 set."
    )
    parser.add_argument("--processed-dir", default=str(PROCESSED_DATA_DIR))
    parser.add_argument("--models-dir", default=str(MODELS_DIR))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    with SessionLocal() as db:
        metadata = train_final_first_set_winner_model(
            db, processed_dir=args.processed_dir, models_dir=args.models_dir,
        )
    print(format_final_model_summary(metadata))


if __name__ == "__main__":
    main()


