"""Feature esplorative (non in produzione): medie storiche di dominanza al
servizio per giocatore, dal corpus ATP storico (tour_main + qual_chall — i
livelli "futures"/ITF hanno 0% di copertura, gia' verificato, quindi esclusi).

Riusa lo stesso principio anti-leakage di
``app.ml.features.feature_builder.calculate_win_rate_last_n``: solo partite
STRETTAMENTE precedenti alla data del match da prevedere.

Non tocca ``atp_singles_enrichment.py``/``feature_builder.py`` (pipeline di
produzione): e' un modulo satellite, pensato per essere usato solo da script
esplorativi (es. ``train_v4_serve_stats_experiment.py``).

Metriche calcolate per singolo giocatore (dalla sua prospettiva, sia che
abbia vinto sia che abbia perso quel match storico):

- ``serve_pts_won_pct``: (1stWon + 2ndWon) / svpt — % punti di servizio vinti.
- ``bp_saved_pct``: bpSaved / bpFaced (NaN se bpFaced == 0, non 0/1 forzato).
- ``ace_rate``: ace / svpt.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# Confermato empiricamente (analisi 2026-08-10): "futures" (ITF/satellite,
# livelli 15/25/S) ha 0% di copertura per queste colonne nei file Sackmann;
# tour_main + qual_chall (A/M/G/F/D/Challenger) ha 94-99.6% di copertura.
SERVE_STAT_SOURCE_KINDS = ("atp_matches", "atp_matches_qual_chall")

RAW_STAT_COLUMNS = [
    "w_ace", "w_df", "w_svpt", "w_1stIn", "w_1stWon", "w_2ndWon", "w_SvGms", "w_bpSaved", "w_bpFaced",
    "l_ace", "l_df", "l_svpt", "l_1stIn", "l_1stWon", "l_2ndWon", "l_SvGms", "l_bpSaved", "l_bpFaced",
]

METRIC_NAMES = ("serve_pts_won_pct", "bp_saved_pct", "ace_rate")
DEFAULT_WINDOW = 10


def _metrics_from_prefix(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    ace = frame[f"{prefix}_ace"]
    svpt = frame[f"{prefix}_svpt"]
    first_won = frame[f"{prefix}_1stWon"]
    second_won = frame[f"{prefix}_2ndWon"]
    bp_saved = frame[f"{prefix}_bpSaved"]
    bp_faced = frame[f"{prefix}_bpFaced"]

    serve_pts_won_pct = (first_won + second_won) / svpt.replace(0, np.nan)
    bp_saved_pct = bp_saved / bp_faced.replace(0, np.nan)
    ace_rate = ace / svpt.replace(0, np.nan)
    return pd.DataFrame(
        {
            "serve_pts_won_pct": serve_pts_won_pct,
            "bp_saved_pct": bp_saved_pct,
            "ace_rate": ace_rate,
        }
    )


def load_serve_stats_corpus(atp_data_dir: str | Path, *, year_start: int = 1990, year_end: int = 2024) -> pd.DataFrame:
    """Corpus 'long' (una riga per giocatore per match): atp_id, date, metriche.

    Combina la prospettiva vincitore (colonne ``w_*``) e perdente (``l_*``):
    ogni giocatore vede le PROPRIE statistiche di quel match, indipendentemente
    dall'esito. Righe senza tutte le colonne statistiche richieste vengono
    scartate (stesso criterio usato per misurare la copertura).
    """
    atp_dir = Path(atp_data_dir)
    frames: list[pd.DataFrame] = []
    for year in range(year_start, year_end + 1):
        for kind in SERVE_STAT_SOURCE_KINDS:
            path = atp_dir / f"{kind}_{year}.csv"
            if not path.exists():
                continue
            needed = ["tourney_date", "winner_id", "loser_id", *RAW_STAT_COLUMNS]
            raw = pd.read_csv(path, low_memory=False)
            missing = [c for c in needed if c not in raw.columns]
            if missing:
                continue
            sub = raw[needed].copy()
            has_stats = sub[RAW_STAT_COLUMNS].notna().all(axis=1)
            sub = sub.loc[has_stats]
            if sub.empty:
                continue
            date = pd.to_datetime(sub["tourney_date"], format="%Y%m%d", errors="coerce")

            winner_metrics = _metrics_from_prefix(sub, "w")
            winner_metrics["atp_id"] = sub["winner_id"]
            winner_metrics["date"] = date

            loser_metrics = _metrics_from_prefix(sub, "l")
            loser_metrics["atp_id"] = sub["loser_id"]
            loser_metrics["date"] = date

            frames.append(winner_metrics)
            frames.append(loser_metrics)

    if not frames:
        return pd.DataFrame(columns=["atp_id", "date", *METRIC_NAMES])

    corpus = pd.concat(frames, ignore_index=True)
    corpus = corpus.dropna(subset=["atp_id", "date"])
    corpus["atp_id"] = corpus["atp_id"].astype(int)
    return corpus.sort_values(["atp_id", "date"]).reset_index(drop=True)


class PlayerServeStatIndex:
    """Indice per player (atp_id) -> array ordinato di date + medie cumulative
    per query O(log n) di "media delle ultime N partite prima di una data"."""

    def __init__(self, corpus: pd.DataFrame, window: int = DEFAULT_WINDOW) -> None:
        self.window = window
        self._dates: dict[int, np.ndarray] = {}
        self._values: dict[int, dict[str, np.ndarray]] = {}
        for atp_id, group in corpus.groupby("atp_id"):
            self._dates[atp_id] = group["date"].to_numpy()
            self._values[atp_id] = {metric: group[metric].to_numpy(dtype=float) for metric in METRIC_NAMES}

    def rolling_averages(self, atp_id: int | None, before_date) -> dict[str, float | None]:
        if atp_id is None or atp_id not in self._dates:
            return {metric: None for metric in METRIC_NAMES}
        dates = self._dates[atp_id]
        idx = int(np.searchsorted(dates, np.datetime64(before_date), side="left"))
        start = max(0, idx - self.window)
        if idx <= start:
            return {metric: None for metric in METRIC_NAMES}
        result: dict[str, float | None] = {}
        for metric in METRIC_NAMES:
            window_values = self._values[atp_id][metric][start:idx]
            window_values = window_values[~np.isnan(window_values)]
            result[metric] = float(window_values.mean()) if len(window_values) else None
        return result


def build_internal_id_to_atp_id_crosswalk(dataframe: pd.DataFrame) -> dict[int, int]:
    """Stesso approccio validato nell'analisi di densita' 2026-08-10: usa
    QUALUNQUE riga in cui quel giocatore (player_1_id/player_2_id, id interno
    sempre popolato) e' stato risolto con successo a un atp_id, anche se la
    riga corrente non lo e'."""
    matched = dataframe[dataframe["atp_match_found"] == 1]
    cw1 = matched[["player_1_id", "player_1_atp_id"]].dropna().rename(
        columns={"player_1_id": "internal_id", "player_1_atp_id": "atp_id"}
    )
    cw2 = matched[["player_2_id", "player_2_atp_id"]].dropna().rename(
        columns={"player_2_id": "internal_id", "player_2_atp_id": "atp_id"}
    )
    combined = pd.concat([cw1, cw2], ignore_index=True).drop_duplicates(subset=["internal_id"])
    return dict(zip(combined["internal_id"].astype(int), combined["atp_id"].astype(int)))


EXTRA_FEATURE_COLUMNS: list[str] = [
    *[f"player_1_{metric}_last{DEFAULT_WINDOW}" for metric in METRIC_NAMES],
    *[f"player_2_{metric}_last{DEFAULT_WINDOW}" for metric in METRIC_NAMES],
    *[f"{metric}_diff" for metric in METRIC_NAMES],
]


def add_serve_stat_features(
    dataframe: pd.DataFrame,
    atp_data_dir: str | Path,
    *,
    window: int = DEFAULT_WINDOW,
) -> pd.DataFrame:
    """Ritorna una COPIA di ``dataframe`` con le colonne extra in
    ``EXTRA_FEATURE_COLUMNS`` aggiunte. Non modifica l'input, non tocca alcun
    file di produzione."""
    result = dataframe.copy()
    match_dates = pd.to_datetime(result["match_date"], errors="coerce")

    corpus = load_serve_stats_corpus(atp_data_dir)
    index = PlayerServeStatIndex(corpus, window=window)
    crosswalk = build_internal_id_to_atp_id_crosswalk(result)

    p1_atp_ids = result["player_1_id"].map(crosswalk)
    p2_atp_ids = result["player_2_id"].map(crosswalk)

    p1_rows = [index.rolling_averages(atp_id, date) for atp_id, date in zip(p1_atp_ids, match_dates)]
    p2_rows = [index.rolling_averages(atp_id, date) for atp_id, date in zip(p2_atp_ids, match_dates)]

    for metric in METRIC_NAMES:
        p1_col = f"player_1_{metric}_last{window}"
        p2_col = f"player_2_{metric}_last{window}"
        result[p1_col] = [row[metric] for row in p1_rows]
        result[p2_col] = [row[metric] for row in p2_rows]
        result[f"{metric}_diff"] = result[p1_col] - result[p2_col]

    return result

