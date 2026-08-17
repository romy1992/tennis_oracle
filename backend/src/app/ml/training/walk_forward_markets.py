"""Registry connecting the official walk-forward engine to the extra-market
(non match-winner) walk-forward logic already built in
``train_first_set_winner_odds.py`` / ``train_over_under_games.py``.

Kept as a separate module (not merged into ``walk_forward.py``) because those
two training modules already import shared primitives FROM ``walk_forward.py``
(``generate_walk_forward_folds``, ``slice_fold_frames``, ``_estimators``, ...).
Importing them back from ``walk_forward.py`` at module load time would create
a circular import; ``walk_forward.py`` instead imports this registry lazily,
inside the functions that dispatch to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
from sqlalchemy.orm import Session

from backend.src.app.ml.datasets.first_set_winner_odds_builder import (
    FIRST_SET_ODDS_FEATURE_COLUMNS,
)
from backend.src.app.ml.datasets.over_under_games_odds_builder import (
    DEFAULT_LINE,
    OVER_UNDER_ODDS_FEATURE_COLUMNS,
)
from backend.src.app.ml.model_versioning import (
    ACTIVE_MATCH_WINNER_VERSIONS,
    MODEL_VERSIONS,
    PROCESSED_DATA_DIR,
)
from backend.src.app.ml.training.train_first_set_winner import FIRST_SET_TARGET_COLUMN
from backend.src.app.ml.training.train_first_set_winner_odds import (
    FIRST_SET_ODDS_MODEL_VERSION_LABEL,
    build_first_set_winner_odds_dataframe,
    evaluate_fold_models_first_set_odds,
)
from backend.src.app.ml.training.train_over_under_games import (
    OVER_UNDER_MODEL_VERSION_LABEL,
    OVER_UNDER_TARGET_COLUMN,
    build_over_under_games_dataframe,
    evaluate_fold_models_over_under_games,
)
from backend.src.app.ml.training.walk_forward import (
    WalkForwardFoldOutcome,
    prepare_temporal_dataframe,
)

LoadDataframe = Callable[[Session, "str | Path"], "tuple[pd.DataFrame, Path]"]
EvaluateFold = Callable[..., list[WalkForwardFoldOutcome]]


@dataclass(frozen=True)
class WalkForwardMarketSpec:
    """A non match-winner market pluggable into the official walk-forward engine."""

    version_label: str
    target_column: str
    feature_columns_extra: tuple[str, ...]
    load_dataframe: LoadDataframe
    evaluate_fold: EvaluateFold


def _load_first_set_winner_dataframe(
    db: Session, processed_dir: str | Path = PROCESSED_DATA_DIR,
) -> tuple[pd.DataFrame, Path]:
    """Same data-prep as ``train_first_set_winner_odds_final_model.py``:
    v3 dataset + 1st-set target/odds, rows without 1st-set odds dropped."""
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
    return dataframe, dataset_path


def _load_over_under_games_dataframe(
    db: Session, processed_dir: str | Path = PROCESSED_DATA_DIR,
) -> tuple[pd.DataFrame, Path]:
    """Same data-prep as ``train_over_under_games_final_model.py``:
    v3 dataset + O/U-games target/odds (default line), rows without O/U odds dropped."""
    merged, dataset_path = build_over_under_games_dataframe(
        db, line=DEFAULT_LINE, processed_dir=processed_dir,
    )
    dataframe = prepare_temporal_dataframe(
        merged, target_column=OVER_UNDER_TARGET_COLUMN, model_version="v3",
    )
    if "avg_over_odds" in dataframe.columns and "avg_under_odds" in dataframe.columns:
        has_odds = (
            pd.to_numeric(dataframe["avg_over_odds"], errors="coerce").notna()
            & pd.to_numeric(dataframe["avg_under_odds"], errors="coerce").notna()
        )
        dataframe = dataframe.loc[has_odds].reset_index(drop=True)
    return dataframe, dataset_path


EXTRA_MARKET_SPECS: dict[str, WalkForwardMarketSpec] = {
    FIRST_SET_ODDS_MODEL_VERSION_LABEL: WalkForwardMarketSpec(
        version_label=FIRST_SET_ODDS_MODEL_VERSION_LABEL,
        target_column=FIRST_SET_TARGET_COLUMN,
        feature_columns_extra=tuple(FIRST_SET_ODDS_FEATURE_COLUMNS),
        load_dataframe=_load_first_set_winner_dataframe,
        evaluate_fold=evaluate_fold_models_first_set_odds,
    ),
    OVER_UNDER_MODEL_VERSION_LABEL: WalkForwardMarketSpec(
        version_label=OVER_UNDER_MODEL_VERSION_LABEL,
        target_column=OVER_UNDER_TARGET_COLUMN,
        feature_columns_extra=tuple(OVER_UNDER_ODDS_FEATURE_COLUMNS),
        load_dataframe=_load_over_under_games_dataframe,
        evaluate_fold=evaluate_fold_models_over_under_games,
    ),
}

# Every currently "live" walk-forward target: the active match-winner
# version(s) plus every extra market above. Default scope for a new
# walk-forward run ("tutti i mercati attivi"), not just match-winner.
ACTIVE_WALK_FORWARD_MARKET_VERSIONS: tuple[str, ...] = tuple(
    sorted({*ACTIVE_MATCH_WINNER_VERSIONS, *EXTRA_MARKET_SPECS})
)

# Every version/label a walk-forward run may be explicitly pointed at,
# including archived match-winner tags (v1-v3) for historical backtests.
ALL_WALK_FORWARD_VERSIONS: tuple[str, ...] = tuple(
    sorted({*MODEL_VERSIONS, *EXTRA_MARKET_SPECS})
)
