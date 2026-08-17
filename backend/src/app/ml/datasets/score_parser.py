"""Parsing dei punteggi set-by-set dai dati grezzi ``Fixture`` (partite completate).

Prerequisito ("Fase 0") per allenare nuovi mercati oltre al match winner:
vincitore 1 set, punteggio esatto in set, game totali giocati (Over/Under).
Nessuna di queste informazioni esiste oggi in forma strutturata:
``event_game_result`` e' solo una stringa grezza esplicitamente esclusa come
leakage in ``train_baseline.py`` (colonna post-match, mai trasformata in
target); ``scores`` (JSON) non viene mai letto da nessun modulo esistente.

Da non confondere con ``atp_singles_enrichment.set_score_from_atp_score``:
quello parsa la colonna ``score`` del corpus storico Sackmann (stringa
"winner_games-loser_games" per set, es. "6-4 3-6 6-2"), fonte e formato
diversi. Questo modulo lavora sui dati LIVE importati in ``fixture``
(convenzione ``player_1``/``player_2`` = ``first_player_key``/``second_player_key``,
la stessa di ``dataset_builder.load_legacy_match_rows``).

Fonte primaria (UNICA considerata affidabile senza verifica empirica):
``Fixture.scores`` (JSON strutturato, forma REALE confermata empiricamente sul
DB di produzione il 2026-08-12, vedi ``backend/scripts/diag_score_anomalies.py``)::

    [
        {"score_first": "6", "score_second": "4", "score_set": "1"},
        {"score_first": "7.7", "score_second": "6.2", "score_set": "2"},
        {"score_first": "0", "score_second": "0", "score_set": "3"}
    ]

Due particolarita' reali del formato, gestite esplicitamente dal parser:

1. **Slot placeholder non giocati**: l'array ha spesso lunghezza fissa (fino
   a 5 elementi, "1".."5"); i set oltre quelli realmente disputati sono
   riempiti con ``"0"``/``"0"``. Un set concluso non finisce mai 0-0: questi
   slot vengono ignorati silenziosamente (non contano come set, non
   invalidano il match).
2. **Set decisi al tiebreak**: codificati come ``"game.punti_tiebreak"``
   (es. ``"7.7"`` = 7 game vinti, tiebreak chiuso 7 punti per questo
   giocatore). Si estrae solo la parte intera (i punti del tiebreak non
   servono ai target attuali, tutti basati sui game).

``Fixture.event_game_result`` (stringa leggibile, es. "6-4, 7-5") e' anch'esso
parsabile (``parse_event_game_result_text``) ma NON e' confermato empiricamente
che contenga sempre il punteggio set-by-set finale per le partite completate
(alcuni feed tennis usano un campo con questo nome per il punteggio del game
IN CORSO durante il live, non per il riepilogo finale set-by-set; sul DB di
produzione risulta quasi sempre ``"-"`` o ``"0 - 0"`` per le fixture con
``scores`` gia' popolato). Per questo il fallback su questo campo e' marcato
``parse_source="event_game_result_regex"`` ed e' ESCLUSO di default dai target
di training (``is_valid_for_training`` ritorna sempre ``False`` per questa
fonte), finche' non verificato sui dati reali con ``summarize_score_parsing``
(CLI in fondo al file: ``python -m backend.src.app.ml.datasets.score_parser``).

Convenzione player_1/player_2: SEMPRE first_player_key/second_player_key,
nessuno shuffle. Si assume che ``score_first``/``score_second`` seguano la
stessa convenzione "First/Second" usata ovunque nel provider (coerente con
``event_winner in {"First Player", "Second Player"}``) — verificabile
empiricamente con ``summarize_score_parsing`` (confronta il vincitore
implicito dai set con ``event_winner``: un tasso di accordo vicino al 100%
conferma l'assunzione; vicino allo 0% segnala orientamento invertito).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.src.entity import Fixture

logger = logging.getLogger(__name__)

ParseSource = Literal["scores_json", "event_game_result_regex", "none"]
PlayerSide = Literal["player_1", "player_2"]

# Punteggi di set validi per il tennis professionistico standard (no-ad/match
# tiebreak-al-posto-del-3-set escluso, non gestito qui: assente/trascurabile
# su ATP main tour + qual/chall, vedi serve_stats_features.py). Un set che non
# rientra in questo elenco (es. "3-2" per un ritiro a meta' set) viene trattato
# come anomalia e l'intera partita esclusa dai target (mai un valore inventato).
_VALID_SET_SCORES = {(6, 0), (6, 1), (6, 2), (6, 3), (6, 4), (7, 5), (7, 6)}

# Combinazioni (set vinti dal vincitore, set vinti dal perdente) valide per un
# match concluso normalmente: best-of-3 o best-of-5. Serve a intercettare i
# casi in cui il provider omette del tutto l'ultimo set incompleto (ritiro):
# i singoli set risultano individualmente validi ma il "totale" no.
_VALID_MATCH_SET_COUNTS = {(2, 0), (2, 1), (3, 0), (3, 1), (3, 2)}

SCORE_TARGET_COLUMNS = [
    "target_first_set_winner",
    "target_sets_won_player_1",
    "target_sets_won_player_2",
    "target_correct_score_sets",
    "target_straight_sets",
    "target_total_games_player_1",
    "target_total_games_player_2",
    "target_total_games",
]


def _is_valid_set_score(player_1_games: int, player_2_games: int) -> bool:
    pair = (
        (player_1_games, player_2_games)
        if player_1_games > player_2_games
        else (player_2_games, player_1_games)
    )
    return pair in _VALID_SET_SCORES


@dataclass(frozen=True)
class SetScore:
    set_number: int
    player_1_games: int
    player_2_games: int

    @property
    def winner(self) -> PlayerSide | None:
        if self.player_1_games == self.player_2_games:
            return None
        return "player_1" if self.player_1_games > self.player_2_games else "player_2"

    @property
    def is_valid(self) -> bool:
        return _is_valid_set_score(self.player_1_games, self.player_2_games)


@dataclass(frozen=True)
class ParsedMatchScore:
    match_id: int
    parse_source: ParseSource
    sets: tuple[SetScore, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def sets_played(self) -> int:
        return len(self.sets)

    @property
    def sets_won_player_1(self) -> int:
        return sum(1 for set_score in self.sets if set_score.winner == "player_1")

    @property
    def sets_won_player_2(self) -> int:
        return sum(1 for set_score in self.sets if set_score.winner == "player_2")

    @property
    def total_games_player_1(self) -> int:
        return sum(set_score.player_1_games for set_score in self.sets)

    @property
    def total_games_player_2(self) -> int:
        return sum(set_score.player_2_games for set_score in self.sets)

    @property
    def total_games(self) -> int:
        return self.total_games_player_1 + self.total_games_player_2

    @property
    def first_set_winner(self) -> PlayerSide | None:
        return self.sets[0].winner if self.sets else None

    @property
    def correct_score_label(self) -> str | None:
        """Punteggio in set orientato player_1-player_2, es. "2-0", "1-2"."""
        if not self.sets:
            return None
        return f"{self.sets_won_player_1}-{self.sets_won_player_2}"

    @property
    def is_straight_sets(self) -> bool | None:
        if not self.sets:
            return None
        return self.sets_won_player_1 == 0 or self.sets_won_player_2 == 0

    @property
    def has_anomalous_set(self) -> bool:
        return any(not set_score.is_valid for set_score in self.sets)

    @property
    def has_valid_match_shape(self) -> bool:
        """False se il conteggio set vinti non corrisponde a un match concluso
        best-of-3/5 (es. il provider omette l'ultimo set incompleto in caso
        di ritiro: i set superstiti sembrano individualmente validi ma il
        totale no)."""
        if not self.sets:
            return False
        winner_sets = max(self.sets_won_player_1, self.sets_won_player_2)
        loser_sets = min(self.sets_won_player_1, self.sets_won_player_2)
        return (winner_sets, loser_sets) in _VALID_MATCH_SET_COUNTS

    @property
    def is_suspected_retirement(self) -> bool:
        """Segnale di ritiro/walkover/anomalia: da ESCLUDERE dai nuovi target
        (il match resta valido per il solo target match-winner, che non
        dipende dalla granularita' dei set)."""
        return (
            self.sets_played == 0
            or self.has_anomalous_set
            or not self.has_valid_match_shape
        )

    @property
    def is_valid_for_training(self) -> bool:
        """Gate finale per i nuovi target: SOLO fonte ``scores_json`` (il
        fallback testuale resta sperimentale/non verificato), set individuali
        tutti validi e conteggio set complessivo coerente con un match concluso.
        """
        return (
            self.parse_source == "scores_json"
            and self.sets_played > 0
            and not self.has_anomalous_set
            and self.has_valid_match_shape
        )


def _ordinal_from_set_label(label: Any) -> int | None:
    if not isinstance(label, str):
        return None
    match = re.search(r"(\d+)", label)
    return int(match.group(1)) if match else None


def _coerce_games(value: Any) -> int | None:
    """Game vinti in un set.

    Confermato empiricamente (2026-08-12, vedi ``diag_score_anomalies.py``):
    quando il set si decide al tiebreak il provider a volte codifica
    "game.punti_tiebreak" (es. ``"7.7"`` = 7 game vinti, tiebreak concluso
    7 punti per questo giocatore; ``"6.2"`` = 6 game, 2 punti tiebreak).
    Si prende solo la parte intera: i punti del tiebreak non servono ai
    target attuali (tutti basati sui game, non sui punti)."""
    text = str(value).strip()
    if not text:
        return None
    try:
        games = int(float(text))
    except (TypeError, ValueError):
        return None
    return games if games >= 0 else None


def parse_scores_json(payload: Any, *, match_id: int) -> ParsedMatchScore | None:
    """Fonte primaria: ``Fixture.scores``.

    Ritorna ``None`` se il payload non e' utilizzabile: assente, letterale
    JSON ``"null"`` (stesso caso limite di ``odds_builder.has_real_odds``:
    SQLAlchemy ``JSON`` puo' salvare ``None`` come testo ``"null"``), o lista
    vuota. Le voci senza ``score_first``/``score_second`` numerici vengono
    scartate con un warning: non fanno fallire l'intero parsing.
    """
    if payload is None or payload == "null":
        return None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, list) or not payload:
        return None

    warnings: list[str] = []
    raw_sets: list[tuple[int, int, int]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            warnings.append(f"entry_{index}_not_dict")
            continue
        player_1_games = _coerce_games(entry.get("score_first"))
        player_2_games = _coerce_games(entry.get("score_second"))
        if player_1_games is None or player_2_games is None:
            warnings.append(f"entry_{index}_non_numeric_games")
            continue
        if player_1_games == 0 and player_2_games == 0:
            # Slot placeholder per un set non giocato: il provider riempie
            # l'array a lunghezza fissa (fino a "5th Set") anche oltre i set
            # realmente disputati. Un set concluso non finisce mai 0-0: va
            # ignorato senza contarlo ne' invalidare il match (confermato
            # empiricamente il 2026-08-12: pattern sistematico sui trailing
            # slot, vedi backend/scripts/diag_score_anomalies.py).
            warnings.append(f"entry_{index}_zero_zero_unplayed_slot_skipped")
            continue
        ordinal = _ordinal_from_set_label(entry.get("score_set")) or (index + 1)
        raw_sets.append((ordinal, player_1_games, player_2_games))

    if not raw_sets:
        return ParsedMatchScore(
            match_id=match_id,
            parse_source="scores_json",
            sets=(),
            warnings=tuple(warnings) or ("no_usable_set_entries",),
        )

    raw_sets.sort(key=lambda item: item[0])
    sets = tuple(
        SetScore(set_number=position + 1, player_1_games=p1, player_2_games=p2)
        for position, (_ordinal, p1, p2) in enumerate(raw_sets)
    )
    return ParsedMatchScore(
        match_id=match_id,
        parse_source="scores_json",
        sets=sets,
        warnings=tuple(warnings),
    )


_SET_TOKEN_RE = re.compile(r"(\d{1,2})\s*-\s*(\d{1,2})(?:\s*\(\d{1,2}\))?")


def parse_event_game_result_text(text: Any, *, match_id: int) -> ParsedMatchScore | None:
    """Fallback SPERIMENTALE/NON VERIFICATO su ``Fixture.event_game_result``.

    Sempre marcato ``parse_source="event_game_result_regex"``: escluso di
    default dai target di training (vedi ``ParsedMatchScore.is_valid_for_training``)
    finche' non confermato sui dati reali con ``summarize_score_parsing``.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    tokens = _SET_TOKEN_RE.findall(text)
    if not tokens:
        return ParsedMatchScore(
            match_id=match_id,
            parse_source="event_game_result_regex",
            sets=(),
            warnings=("no_set_tokens_found",),
        )
    sets = tuple(
        SetScore(set_number=position + 1, player_1_games=int(p1), player_2_games=int(p2))
        for position, (p1, p2) in enumerate(tokens)
    )
    return ParsedMatchScore(match_id=match_id, parse_source="event_game_result_regex", sets=sets)


def parse_fixture_score(
    *,
    match_id: int,
    scores: Any,
    event_game_result: Any = None,
    allow_text_fallback: bool = False,
) -> ParsedMatchScore:
    """Punto d'ingresso unico: prova ``scores`` JSON, poi (solo se
    ``allow_text_fallback=True``, di default disattivato) ``event_game_result``.
    """
    parsed = parse_scores_json(scores, match_id=match_id)
    if parsed is not None and parsed.sets_played > 0:
        return parsed
    if allow_text_fallback:
        parsed_text = parse_event_game_result_text(event_game_result, match_id=match_id)
        if parsed_text is not None and parsed_text.sets_played > 0:
            return parsed_text
    return ParsedMatchScore(match_id=match_id, parse_source="none", sets=(), warnings=("no_score_data",))


def score_targets_from_parsed(parsed: ParsedMatchScore) -> dict[str, Any]:
    """Colonne target da agganciare (merge ``how="left"`` su ``match_id``) al
    dataset esistente — stesso pattern di ``odds_builder.attach_odds_to_dataset``.

    ``None`` quando il parsing non e' attendibile (``is_valid_for_training``
    False): MAI riempito con 0/valori di comodo, per non introdurre rumore
    silenzioso nei nuovi modelli.
    """
    valid = parsed.is_valid_for_training
    first_set_winner = parsed.first_set_winner if valid else None
    return {
        "match_id": parsed.match_id,
        "score_parse_source": parsed.parse_source,
        "score_is_valid_for_training": valid,
        "score_sets_played": parsed.sets_played if valid else None,
        "target_first_set_winner": (
            1 if first_set_winner == "player_1" else 0 if first_set_winner == "player_2" else None
        ),
        "target_sets_won_player_1": parsed.sets_won_player_1 if valid else None,
        "target_sets_won_player_2": parsed.sets_won_player_2 if valid else None,
        "target_correct_score_sets": parsed.correct_score_label if valid else None,
        "target_straight_sets": parsed.is_straight_sets if valid else None,
        "target_total_games_player_1": parsed.total_games_player_1 if valid else None,
        "target_total_games_player_2": parsed.total_games_player_2 if valid else None,
        "target_total_games": parsed.total_games if valid else None,
    }


def target_over_line(total_games: int | float | None, line: float) -> int | None:
    """Etichetta Over/Under per una linea arbitraria (la linea offerta dal
    bookmaker e' specifica per match, non fissa): 1 se ``total_games > line``
    (Over), 0 se Under. Usare una linea a taglio ``x.5`` per evitare push."""
    if total_games is None:
        return None
    return 1 if float(total_games) > line else 0


# ---------------------------------------------------------------------------
# Batch loading + report di validazione (da eseguire sui dati reali PRIMA di
# usare questi target per allenare qualunque modello).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FixtureScoreRecord:
    match_id: int
    scores: Any
    event_game_result: Any
    event_winner: str | None


def load_fixture_score_records(db: Session, *, singles_only: bool = True) -> list[FixtureScoreRecord]:
    """Fixture completate con ``event_winner`` risolto.

    ``singles_only=True`` (default) applica lo STESSO filtro gia' usato in
    produzione per il dataset match-winner
    (``dataset_builder.load_legacy_match_rows``): esclude doppio/teams, dove
    il 3 set e' spesso un match-tiebreak (es. "10-7") anziche' un set pieno —
    senza questo filtro la percentuale "valida per training" risulta
    artificialmente bassa perche' quei punteggi vengono (correttamente)
    marcati come anomalia dal validatore di set.
    """
    conditions = [Fixture.event_winner.in_(["First Player", "Second Player"])]
    if singles_only:
        conditions.extend(
            [
                Fixture.event_type_type.ilike("%singles%"),
                ~Fixture.event_type_type.ilike("%doubles%"),
                ~Fixture.event_type_type.ilike("%teams%"),
            ]
        )
    rows = db.execute(
        select(
            Fixture.event_key,
            Fixture.scores,
            Fixture.event_game_result,
            Fixture.event_winner,
        ).where(*conditions)
    ).all()
    return [
        FixtureScoreRecord(
            match_id=row.event_key,
            scores=row.scores,
            event_game_result=row.event_game_result,
            event_winner=row.event_winner,
        )
        for row in rows
    ]


def build_score_targets_dataframe(
    db: Session,
    *,
    allow_text_fallback: bool = False,
    singles_only: bool = True,
) -> pd.DataFrame:
    """Dataframe con ``match_id`` + colonne target, pronto per un merge
    (``how="left"`` su ``match_id``) sui dataset v3/v4 esistenti."""
    records = load_fixture_score_records(db, singles_only=singles_only)
    rows = [
        score_targets_from_parsed(
            parse_fixture_score(
                match_id=record.match_id,
                scores=record.scores,
                event_game_result=record.event_game_result,
                allow_text_fallback=allow_text_fallback,
            )
        )
        for record in records
    ]
    columns = [
        "match_id",
        "score_parse_source",
        "score_is_valid_for_training",
        "score_sets_played",
        *SCORE_TARGET_COLUMNS,
    ]
    return pd.DataFrame(rows, columns=columns)


def attach_score_targets_to_dataset(dataset: pd.DataFrame, score_targets: pd.DataFrame) -> pd.DataFrame:
    if "match_id" not in dataset.columns:
        return dataset.copy()
    return dataset.merge(score_targets, on="match_id", how="left", validate="one_to_one")


def _summarize_records(
    records: list[FixtureScoreRecord],
    *,
    allow_text_fallback: bool = False,
) -> dict[str, Any]:
    total = len(records)
    by_source: dict[str, int] = {}
    valid_for_training = 0
    suspected_retirement = 0
    agree = 0
    disagree = 0
    ambiguous = 0

    for record in records:
        parsed = parse_fixture_score(
            match_id=record.match_id,
            scores=record.scores,
            event_game_result=record.event_game_result,
            allow_text_fallback=allow_text_fallback,
        )
        by_source[parsed.parse_source] = by_source.get(parsed.parse_source, 0) + 1
        if parsed.is_valid_for_training:
            valid_for_training += 1
        if parsed.sets_played > 0 and parsed.is_suspected_retirement:
            suspected_retirement += 1

        if parsed.sets_played == 0 or parsed.sets_won_player_1 == parsed.sets_won_player_2:
            ambiguous += 1
            continue
        implied_winner = (
            "First Player" if parsed.sets_won_player_1 > parsed.sets_won_player_2 else "Second Player"
        )
        if implied_winner == record.event_winner:
            agree += 1
        else:
            disagree += 1

    checked = agree + disagree
    return {
        "total_completed_fixtures": total,
        "parse_source_breakdown": by_source,
        "valid_for_training": valid_for_training,
        "valid_for_training_pct": round(valid_for_training / total * 100, 2) if total else 0.0,
        "suspected_retirement_or_anomalous": suspected_retirement,
        "orientation_check": {
            "agree_with_event_winner": agree,
            "disagree_with_event_winner": disagree,
            "ambiguous_or_unparsed": ambiguous,
            "agreement_pct": round(agree / checked * 100, 2) if checked else None,
            "note": (
                "Un agreement_pct vicino al 100% conferma che score_first/score_second "
                "seguono la convenzione First/Second del provider. Vicino allo 0%: "
                "orientamento invertito (scambiare player_1/player_2 nel parser). "
                "Vicino al 50%: parsing inattendibile, verificare un campione di "
                "'scores' grezzi a mano."
            ),
        },
    }


def summarize_score_parsing(
    db: Session,
    *,
    allow_text_fallback: bool = False,
    singles_only: bool = True,
) -> dict[str, Any]:
    """Report diagnostico DA ESEGUIRE PRIMA di allenare qualunque modello sui
    nuovi target: copertura del parsing + tasso di accordo fra il vincitore
    implicito dai set e ``event_winner`` (verifica l'assunzione di
    orientamento First/Second, vedi docstring di modulo)."""
    records = load_fixture_score_records(db, singles_only=singles_only)
    return _summarize_records(records, allow_text_fallback=allow_text_fallback)


def format_score_parsing_summary(report: dict[str, Any]) -> str:
    check = report["orientation_check"]
    lines = [
        "Report parsing punteggi set-by-set (Fixture.scores / event_game_result)",
        f"Fixture completate totali: {report['total_completed_fixtures']}",
        f"Per fonte di parsing: {report['parse_source_breakdown']}",
        f"Valide per training: {report['valid_for_training']} ({report['valid_for_training_pct']}%)",
        f"Sospette ritiro/anomalia: {report['suspected_retirement_or_anomalous']}",
        "",
        "--- Verifica orientamento (score_first/second vs event_winner) ---",
        f"  Accordo: {check['agree_with_event_winner']}",
        f"  Disaccordo: {check['disagree_with_event_winner']}",
        f"  Ambigui/non parsati: {check['ambiguous_or_unparsed']}",
        f"  Tasso di accordo: {check['agreement_pct']}%",
        f"  {check['note']}",
    ]
    return "\n".join(lines)


def main() -> None:
    import argparse

    from backend.src.app.db.session import SessionLocal

    parser = argparse.ArgumentParser(
        description="Report diagnostico sul parsing dei punteggi set-by-set (Fase 0)."
    )
    parser.add_argument(
        "--allow-text-fallback",
        action="store_true",
        help="Include anche il fallback (sperimentale/non verificato) su event_game_result.",
    )
    parser.add_argument(
        "--include-non-singles",
        action="store_true",
        help="Non filtrare doppio/teams (default: solo singolare, coerente col training match-winner).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        report = summarize_score_parsing(
            db,
            allow_text_fallback=args.allow_text_fallback,
            singles_only=not args.include_non_singles,
        )
    print(format_score_parsing_summary(report))


if __name__ == "__main__":
    main()








