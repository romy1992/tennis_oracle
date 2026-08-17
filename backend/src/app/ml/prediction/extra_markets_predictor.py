"""Inferenza per i mercati "extra" (oltre al match winner): Vincitore 1° set,
Over/Under Games.

Riusa integralmente ``PreMatchFeatureBuilder`` e ``_clean_features`` da
``predictor.py`` (le feature Elo/rank/forma/H2H/quote match-winner sono
GENERICHE rispetto al target — lo stesso feature-set v3 e' usato da
match-winner, vincitore 1 set ed Over/Under games): NESSUNA duplicazione
della logica di costruzione feature. Carica pero' modelli DEDICATI (allenati
da ``train_first_set_winner_odds_final_model.py`` / ``train_over_under_games_final_model.py``),
MAI i modelli match-winner v1-v4, in cartelle separate sotto ``MODELS_DIR``.

Output generico (``probability``/``selection``), pensato per essere pubblicato
nel ledger ``PublishedPrediction`` (gia' generico via campo ``selection``
string — vedi ``generate_extra_market_predictions.py``), NON nella tabella
``MatchPrediction`` (hardcoded su ``prob_player_1_win``, resta esclusiva del
match winner).
"""

from __future__ import annotations

import logging
import pickle
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.src.app.ml.datasets.first_set_winner_odds_builder import first_set_winner_feature_row
from backend.src.app.ml.datasets.over_under_games_odds_builder import DEFAULT_LINE, over_under_games_feature_row
from backend.src.app.ml.model_versioning import MODELS_DIR
from backend.src.app.ml.prediction.predictor import PreMatchFeatureBuilder, _clean_features
from backend.src.entity import NextFixture

logger = logging.getLogger(__name__)

FIRST_SET_WINNER_MODEL_VERSION = "first_set_winner_v2"
FIRST_SET_WINNER_ARCHIVED_VERSION = "first_set_winner_v1"
FIRST_SET_WINNER_MODEL_NAME = "logistic_regression"
OVER_UNDER_GAMES_MODEL_VERSION = "over_under_games_v1"
OVER_UNDER_GAMES_MODEL_NAME = "random_forest"


def _alias_numpy_pickle_modules() -> bool:
    try:
        import numpy.core as np_core
        import numpy.core.numeric as np_numeric
    except ModuleNotFoundError:
        return False
    sys.modules.setdefault("numpy._core", np_core)
    sys.modules.setdefault("numpy._core.numeric", np_numeric)
    return True


@lru_cache(maxsize=8)
def _load_extra_model_artifact(model_dir_name: str, model_name: str, models_dir: str) -> dict[str, Any]:
    """Stesso pattern di ``predictor._load_model_artifact`` ma con path
    dedicato (fuori da ``MODEL_VERSIONS``/``ModelVersion``, che restano
    riservati ai modelli match-winner ufficiali v1-v4)."""
    model_path = Path(models_dir) / model_dir_name / f"{model_name}.pkl"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Modello non trovato: {model_path}. Esegui prima lo script di training finale "
            f"dedicato (train_{model_dir_name.rsplit('_v', 1)[0]}_final_model.py)."
        )
    with model_path.open("rb") as handle:
        try:
            return pickle.load(handle)
        except ModuleNotFoundError as exc:
            if not (exc.name or "").startswith("numpy._core"):
                raise
            if not _alias_numpy_pickle_modules():
                raise
            logger.warning("Recovered model loading by aliasing NumPy internals (%s).", exc.name)
            handle.seek(0)
            return pickle.load(handle)


def clear_extra_markets_model_cache() -> None:
    _load_extra_model_artifact.cache_clear()


def _missing_required_fields(fixture: NextFixture) -> bool:
    return not fixture.first_player_key or not fixture.second_player_key or not fixture.event_date


def predict_first_set_winner(
    fixture: NextFixture,
    *,
    feature_builder: PreMatchFeatureBuilder,
    models_dir: str | Path = MODELS_DIR,
) -> dict[str, Any]:
    """Predizione Vincitore 1° set per una fixture futura.

    Ritorna sempre un dict con le stesse chiavi; ``probability``/``selection``
    sono ``None`` quando mancano le feature v3 (quote match-winner) o le quote
    dedicate ``Home/Away (1st Set)``. ``market_odds`` e' la media bookmaker
    sulla selezione scelta."""
    base: dict[str, Any] = {
        "event_key": fixture.event_key,
        "market": "first_set_winner",
        "model_version": FIRST_SET_WINNER_MODEL_VERSION,
        "model_name": FIRST_SET_WINNER_MODEL_NAME,
        "probability": None,
        "selection": None,
        "prob_player_1": None,
        "confidence": None,
        "market_odds": None,
        "features_available": False,
        "warnings": [],
    }
    if _missing_required_fields(fixture):
        base["warnings"] = ["missing_player_keys_or_date"]
        return base

    raw_row, warnings, features_available = feature_builder.build_feature_row(
        event_key=fixture.event_key,
        match_date=fixture.event_date,
        surface=fixture.surface,
        player_1_id=fixture.first_player_key,
        player_2_id=fixture.second_player_key,
        model_version="v3",
        odds=fixture.odds,
    )
    base["warnings"] = warnings
    if "missing_odds" in warnings:
        return base

    fs_features = first_set_winner_feature_row(
        event_key=fixture.event_key, match_date=fixture.event_date, odds=fixture.odds,
    )
    if fs_features is None:
        base["warnings"] = [*warnings, "missing_first_set_odds"]
        return base
    raw_row.update(fs_features)

    cleaned = _clean_features(raw_row, "v3")
    for column, value in fs_features.items():
        cleaned[column] = value
    try:
        artifact = _load_extra_model_artifact(
            FIRST_SET_WINNER_MODEL_VERSION, FIRST_SET_WINNER_MODEL_NAME, str(models_dir),
        )
    except FileNotFoundError as exc:
        base["warnings"] = [*warnings, str(exc)]
        return base

    feature_columns: list[str] = artifact["feature_columns"]
    pipeline = artifact["pipeline"]
    missing_columns = [column for column in feature_columns if column not in cleaned.columns]
    for column in missing_columns:
        cleaned[column] = 0
    if missing_columns:
        base["warnings"] = [*warnings, f"missing_feature_columns:{','.join(missing_columns)}"]

    probabilities = pipeline.predict_proba(cleaned[feature_columns])[0]
    prob_player_1 = float(probabilities[1])
    selection = "First Player" if prob_player_1 >= 0.5 else "Second Player"
    market_odds = (
        fs_features["avg_first_set_player_1_odds"]
        if selection == "First Player"
        else fs_features["avg_first_set_player_2_odds"]
    )

    base.update(
        {
            "probability": prob_player_1 if prob_player_1 >= 0.5 else 1.0 - prob_player_1,
            "prob_player_1": prob_player_1,
            "selection": selection,
            "confidence": max(prob_player_1, 1.0 - prob_player_1),
            "market_odds": market_odds,
            "features_available": features_available,
        }
    )
    return base


def predict_over_under_games(
    fixture: NextFixture,
    *,
    feature_builder: PreMatchFeatureBuilder,
    line: float = DEFAULT_LINE,
    models_dir: str | Path = MODELS_DIR,
) -> dict[str, Any]:
    """Predizione Over/Under sul totale game (linea di riferimento 20.5) per
    una fixture futura. Stesse regole di ``predict_first_set_winner``: dict
    sempre presente, ``probability``/``selection`` None se feature/quote O/U
    mancanti per questa linea."""
    base: dict[str, Any] = {
        "event_key": fixture.event_key,
        "market": "over_under_games",
        "line": line,
        "model_version": OVER_UNDER_GAMES_MODEL_VERSION,
        "model_name": OVER_UNDER_GAMES_MODEL_NAME,
        "probability": None,
        "selection": None,
        "prob_over": None,
        "confidence": None,
        "market_odds": None,
        "avg_over_odds": None,
        "avg_under_odds": None,
        "features_available": False,
        "warnings": [],
    }
    if _missing_required_fields(fixture):
        base["warnings"] = ["missing_player_keys_or_date"]
        return base

    raw_row, warnings, features_available = feature_builder.build_feature_row(
        event_key=fixture.event_key,
        match_date=fixture.event_date,
        surface=fixture.surface,
        player_1_id=fixture.first_player_key,
        player_2_id=fixture.second_player_key,
        model_version="v3",
        odds=fixture.odds,
    )
    base["warnings"] = warnings
    if "missing_odds" in warnings:
        return base

    ou_features = over_under_games_feature_row(
        event_key=fixture.event_key, match_date=fixture.event_date, odds=fixture.odds, line=line,
    )
    if ou_features is None:
        base["warnings"] = [*warnings, "missing_over_under_odds"]
        return base
    raw_row.update(ou_features)

    cleaned = _clean_features(raw_row, "v3")
    for column, value in ou_features.items():
        cleaned[column] = value
    try:
        artifact = _load_extra_model_artifact(
            OVER_UNDER_GAMES_MODEL_VERSION, OVER_UNDER_GAMES_MODEL_NAME, str(models_dir),
        )
    except FileNotFoundError as exc:
        base["warnings"] = [*warnings, str(exc)]
        return base

    feature_columns: list[str] = artifact["feature_columns"]
    pipeline = artifact["pipeline"]
    missing_columns = [column for column in feature_columns if column not in cleaned.columns]
    for column in missing_columns:
        cleaned[column] = 0
    if missing_columns:
        base["warnings"] = [*warnings, f"missing_feature_columns:{','.join(missing_columns)}"]

    probabilities = pipeline.predict_proba(cleaned[feature_columns])[0]
    prob_over = float(probabilities[1])
    is_over = prob_over >= 0.5
    selection = f"Over {line}" if is_over else f"Under {line}"
    market_odds = ou_features["avg_over_odds"] if is_over else ou_features["avg_under_odds"]

    base.update(
        {
            "probability": prob_over if is_over else 1.0 - prob_over,
            "prob_over": prob_over,
            "selection": selection,
            "confidence": max(prob_over, 1.0 - prob_over),
            "market_odds": market_odds,
            "avg_over_odds": ou_features["avg_over_odds"],
            "avg_under_odds": ou_features["avg_under_odds"],
            "features_available": features_available,
        }
    )
    return base

