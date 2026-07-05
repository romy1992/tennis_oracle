from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any


TELEGRAM_MESSAGE_LIMIT = 4096
DISCLAIMER = "Pronostici a scopo informativo/statistico, non sono garanzia di risultato."


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            if current:
                chunks.append(current.rstrip())
                current = ""
            for index in range(0, len(line), limit):
                chunks.append(line[index : index + limit].rstrip())
            continue
        if len(current) + len(line) > limit:
            chunks.append(current.rstrip())
            current = line
        else:
            current += line

    if current:
        chunks.append(current.rstrip())
    return [chunk for chunk in chunks if chunk]


def _format_date_time(item: dict[str, Any]) -> str:
    event_date = item.get("event_date") or "data n.d."
    event_time = item.get("event_time")
    if event_time:
        return f"{event_date} {str(event_time)[:5]}"
    return str(event_date)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n.d."
    return f"{value * 100:.0f}%"


def _format_decimal(value: float | None) -> str:
    if value is None:
        return "n.d."
    return f"{value:.2f}"


def predicted_winner_name(item: dict[str, Any]) -> str | None:
    prediction = item.get("prediction") or {}
    raw_winner = prediction.get("predicted_winner")
    player_1 = item.get("event_first_player") or item.get("player_1")
    player_2 = item.get("event_second_player") or item.get("player_2")

    if raw_winner == "First Player":
        return player_1
    if raw_winner == "Second Player":
        return player_2
    return raw_winner


def slip_pick_winner_name(pick: dict[str, Any]) -> str | None:
    if pick.get("predicted_winner_label"):
        return pick["predicted_winner_label"]
    return predicted_winner_name(
        {
            "event_first_player": pick.get("player_1"),
            "event_second_player": pick.get("player_2"),
            "prediction": {"predicted_winner": pick.get("predicted_winner")},
        }
    )


def _match_title(item: dict[str, Any]) -> str:
    player_1 = item.get("event_first_player") or item.get("player_1") or "Giocatore 1"
    player_2 = item.get("event_second_player") or item.get("player_2") or "Giocatore 2"
    return f"{player_1} vs {player_2}"


def format_prediction(item: dict[str, Any], *, compact: bool = False) -> str:
    prediction = item.get("prediction")
    tournament_parts = [
        item.get("tournament_name"),
        item.get("tournament_round"),
        item.get("surface"),
    ]
    tournament = " / ".join(str(part) for part in tournament_parts if part) or "Torneo n.d."

    if not prediction:
        warning = item.get("prediction_warning") or "pronostico mancante"
        return (
            f"{_format_date_time(item)} - {_match_title(item)}\n"
            f"{tournament}\n"
            f"Pronostico non disponibile ({warning})."
        )

    winner = predicted_winner_name(item) or "n.d."
    confidence = prediction.get("confidence")
    odds = prediction.get("predicted_winner_odds")
    if compact:
        return (
            f"{_format_date_time(item)} - {_match_title(item)}: "
            f"{winner} ({_format_percent(confidence)}, quota {_format_decimal(odds)})"
        )
    return (
        f"{_format_date_time(item)} - {_match_title(item)}\n"
        f"{tournament}\n"
        f"Pronostico: {winner} | Confidenza {_format_percent(confidence)} | "
        f"Quota media {_format_decimal(odds)}"
    )


def format_predictions_day(items: list[dict[str, Any]], target_date: date | str) -> str:
    if not items:
        return f"Nessun pronostico trovato per {target_date}.\n\n{DISCLAIMER}"

    lines = [f"Pronostici {target_date}", DISCLAIMER, ""]
    lines.extend(format_prediction(item) for item in items)
    return "\n\n".join(lines)


def format_predictions_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return f"Nessun pronostico trovato nei prossimi 10 giorni.\n\n{DISCLAIMER}"

    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_date[str(item.get("event_date") or "data n.d.")].append(item)

    lines = ["Pronostici prossimi 10 giorni", DISCLAIMER]
    for event_date in sorted(by_date):
        lines.append("")
        lines.append(f"{event_date} ({len(by_date[event_date])})")
        lines.extend(format_prediction(item, compact=True) for item in by_date[event_date])
    return "\n".join(lines)


def format_fixtures(items: list[dict[str, Any]], target_date: date | str) -> str:
    if not items:
        return f"Nessuna partita trovata per {target_date}."

    lines = [format_fixtures_intro(items, target_date), ""]
    lines.append(format_fixture_group_text(items))
    return "\n\n".join(lines)


def format_fixtures_intro(items: list[dict[str, Any]], target_date: date | str) -> str:
    return f"Partite di oggi ({target_date}): {len(items)}"


def format_fixture_group_text(items: list[dict[str, Any]], *, start_index: int = 1) -> str:
    lines = []
    for index, item in enumerate(items, start=start_index):
        tournament_parts = [item.get("tournament_name"), item.get("tournament_round"), item.get("surface")]
        tournament = " / ".join(str(part) for part in tournament_parts if part) or "Torneo n.d."
        lines.append(f"{index}. {_format_date_time(item)}\n{_match_title(item)}\n{tournament}\n{format_fixture_prediction(item)}")
    return "\n\n".join(lines)


def format_fixtures_photo_caption(target_date: date | str, start_index: int, end_index: int, total: int) -> str:
    return f"Partite oggi {target_date} | {start_index}-{end_index} di {total}"


def format_fixture_prediction(item: dict[str, Any]) -> str:
    prediction = item.get("prediction") or {}
    if not prediction:
        warning = item.get("prediction_warning") or "pronostico non disponibile"
        return f"Pronostico: n.d. ({warning})"

    winner = predicted_winner_name(item) or "n.d."
    odds = prediction.get("predicted_winner_odds")
    confidence = prediction.get("confidence")
    return f"Vincitore: {winner} | Quota {_format_decimal(odds)} | Vittoria {_format_percent(confidence)}"


def format_player_search(items: list[dict[str, Any]], player: str) -> str:
    if not items:
        return f"Nessuna partita trovata per '{player}' nei prossimi 10 giorni."

    lines = [f"Risultati ricerca: {player}", DISCLAIMER, ""]
    lines.extend(format_prediction(item) for item in items)
    return "\n\n".join(lines)


def format_betting_slips_intro(payload: dict[str, Any]) -> str:
    slip_date = payload.get("date") or "oggi"
    stake = payload.get("stake")
    lines = [f"Schedine di oggi ({slip_date})", f"Stake: {_format_decimal(stake)}", DISCLAIMER]
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append(f"Note: {'; '.join(warnings)}")
    return "\n".join(lines)


def format_betting_slip_text(slip: dict[str, Any]) -> str:
    lines = [
        f"Schedina: {slip.get('label') or slip.get('slip_key') or 'Schedina'}",
        f"Quota combinata: {_format_decimal(slip.get('combined_odds'))}",
        f"Ritorno potenziale: {_format_decimal(slip.get('potential_return'))}",
        f"Profitto potenziale: {_format_decimal(slip.get('potential_profit'))}",
    ]

    picks = slip.get("picks") or []
    if not picks:
        lines.append("Nessun pick disponibile.")
        return "\n".join(lines)

    lines.append("Pick:")
    for index, pick in enumerate(picks, start=1):
        winner = slip_pick_winner_name(pick) or "n.d."
        lines.append(
            f"{index}. {_match_title(pick)}\n"
            f"   Vincitore: {winner} | quota {_format_decimal(pick.get('odds'))} | "
            f"conf. {_format_percent(pick.get('confidence'))}"
        )
    return "\n".join(lines)


def format_betting_slip_photo_caption(slip: dict[str, Any]) -> str:
    label = slip.get("label") or slip.get("slip_key") or "Schedina"
    return (
        f"{label} | Quota {_format_decimal(slip.get('combined_odds'))} | "
        f"Profitto {_format_decimal(slip.get('potential_profit'))}"
    )


def format_betting_slips(payload: dict[str, Any]) -> str:
    slips = payload.get("slips") or []
    slip_date = payload.get("date") or "oggi"
    if not slips:
        warnings = payload.get("warnings") or []
        suffix = f"\n\nNote: {'; '.join(warnings)}" if warnings else ""
        return f"Nessuna schedina disponibile per {slip_date}.{suffix}\n\n{DISCLAIMER}"

    lines = [format_betting_slips_intro(payload)]
    for slip in slips:
        lines.append("")
        lines.append(format_betting_slip_text(slip))
    return "\n".join(lines)
