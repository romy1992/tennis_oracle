from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from backend.src.app.telegram.dates import ROME_TZ


TELEGRAM_MESSAGE_LIMIT = 4096
DISCLAIMER = (
    "Avvertenza: contenuti a scopo informativo/statistico. "
    "Non sono consigli di scommessa né garanzia di risultato."
)
# Premessa estesa mostrata quando l'utente deve accettare le condizioni d'uso
# (prima e durante /accetta_condizioni): a differenza di DISCLAIMER (breve, in coda
# ai messaggi operativi), qui specifichiamo esplicitamente la fase beta e il rischio,
# cosi' l'utente non "accetta al buio" senza aver letto nulla.
BETA_TERMS_TEXT = (
    "Condizioni d'uso (fase beta) — tennis_oracle\n\n"
    "- Il servizio è in fase BETA: il modello di pronostico è in fase di validazione e il suo "
    "storico di risultati reali è ancora limitato.\n"
    "- I contenuti (pronostici, quote, schedine, statistiche) sono a scopo informativo/"
    "statistico. Non sono consigli di scommessa né di investimento e non garantiscono alcun "
    "risultato o profitto.\n"
    "- Le scommesse comportano il rischio di perdere il denaro puntato: gioca solo ciò che puoi "
    "permetterti di perdere, nel rispetto delle leggi del tuo paese e dei limiti di gioco "
    "responsabile.\n"
    "- tennis_oracle non è un bookmaker né un consulente di scommesse abilitato: resti l'unico "
    "responsabile delle tue decisioni."
)
USER_ERROR_FALLBACK = "Si è verificato un problema temporaneo. Riprova tra poco."
LOADING_PARTITE = "Caricamento partite in corso…"
LOADING_SCHEDINE = "Caricamento schedine in corso…"
LOADING_STATISTICHE = "Caricamento statistiche in corso…"

def build_welcome_text(
    *,
    include_fixtures: bool = True,
    include_slips: bool = True,
    include_statistics: bool = True,
    include_subscription_commands: bool = True,
    include_notifications: bool = True,
    include_feedback: bool = True,
    include_terms: bool = True,
) -> str:
    lines = [
        "Ciao! Sono il bot di tennis_oracle.",
        "",
        "Usa i pulsanti qui sotto oppure i comandi:",
    ]

    if include_fixtures:
        lines.append("/partite - partite di oggi")
    if include_slips:
        lines.append("/schedine - schedine di oggi")
    if include_statistics:
        lines.append("/statistiche - andamento")

    if include_subscription_commands:
        lines.extend(
            [
                "/piano - stato abbonamento",
                "/abbonati - attiva il piano premium",
                "/gestisci_abbonamento - rinnovo e fatturazione",
            ]
        )

    if include_notifications:
        lines.append("/notifiche - preferenze push")
    if include_feedback:
        lines.append("/feedback - invia un feedback")

    lines.extend(["", "/help - guida rapida"])
    if include_terms:
        lines.append("/accetta_condizioni - condizioni d'uso (se richieste)")
    # Sempre presente, indipendentemente dal flag TELEGRAM_TERMS_REQUIRED: quel flag
    # governa solo il flusso di accettazione formale (/accetta_condizioni), non deve
    # condizionare la visibilita' di questa premessa minima (fase beta, nessuna
    # garanzia, rischio di perdita) che l'utente deve vedere comunque al primo /start.
    lines.extend(["", BETA_TERMS_TEXT])
    return "\n".join(lines)


def build_help_text(
    *,
    include_fixtures: bool = True,
    include_slips: bool = True,
    include_statistics: bool = True,
    include_subscription_commands: bool = True,
    include_notifications: bool = True,
    include_feedback: bool = True,
) -> str:
    lines = [
        "Guida rapida",
        "",
    ]

    if include_fixtures:
        lines.append("/partite - partite e pronostici di oggi (con indicazione di valore)")
    if include_slips:
        lines.append("/schedine - schedine proposte di oggi")
    if include_statistics:
        lines.append("/statistiche - andamento storico (partite e schedine)")

    if include_subscription_commands:
        lines.extend(
            [
                "/piano - mostra piano, prova, rinnovo o scadenza",
                "/abbonati - genera link checkout per piano premium",
                "/gestisci_abbonamento - apre il portale cliente per rinnovo/fatturazione",
            ]
        )

    if include_notifications:
        lines.append("/notifiche - attiva, disattiva e preferenze push")
    if include_feedback:
        lines.extend(
            [
                "/feedback - invia un feedback (categoria, valutazione, messaggio)",
                "/annulla - annulla il feedback in corso",
            ]
        )

    lines.extend(
        [
            "",
            "Puoi anche usare i pulsanti del menu iniziale (/start).",
            "",
            "Se non ci sono partite o schedine, riprova più tardi dopo l'aggiornamento giornaliero.",
        ]
    )
    return "\n".join(lines)


WELCOME_TEXT = build_welcome_text()
HELP_TEXT = build_help_text()

ACCOUNT_STATUS_LABELS = {
    "active": "Attivo",
    "invited": "In lista di attesa",
    "suspended": "Sospeso",
    "blocked": "Bloccato",
}

SUBSCRIPTION_STATUS_LABELS = {
    "trialing": "In prova",
    "active": "Attivo",
    "suspended": "Sospeso",
    "canceled": "Cancellato",
    "expired": "Scaduto",
}

FEEDBACK_CATEGORY_LABELS = {
    "bug": "Bug / errore",
    "content": "Contenuti / partite / schedine",
    "ux": "Usabilità bot",
    "feature": "Suggerimento",
    "access": "Accesso / whitelist",
    "other": "Altro",
}

FEEDBACK_START_TEXT = (
    "Invia un feedback\n"
    "\n"
    "1) Scegli una categoria.\n"
    "2) Assegna una valutazione da 1 a 5.\n"
    "3) Scrivi un messaggio.\n"
    "\n"
    "Puoi annullare in qualsiasi momento con /annulla."
)

FEEDBACK_CANCELLED_TEXT = "Feedback annullato. Nessun dato salvato."
FEEDBACK_ASK_RATING_TEXT = "Valutazione: scegli un voto da 1 (basso) a 5 (alto)."
FEEDBACK_ASK_MESSAGE_TEXT = (
    "Scrivi ora il messaggio del feedback (max 2000 caratteri).\n"
    "Per annullare: /annulla"
)
FEEDBACK_SAVED_TEXT = "Grazie! Feedback inviato correttamente."
FEEDBACK_SAVE_FAILED_TEXT = (
    "Non sono riuscito a salvare il feedback. Riprova tra poco con /feedback."
)
FEEDBACK_EMPTY_MESSAGE_TEXT = (
    "Il messaggio non può essere vuoto. Scrivi un testo oppure /annulla."
)
FEEDBACK_MESSAGE_TOO_LONG_TEXT = (
    "Messaggio troppo lungo (max 2000 caratteri). Accorcialo oppure /annulla."
)


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


def _format_event_time(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value)
    return text[:5] if len(text) >= 5 else text


def _format_signed_percent(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}%"


def _format_signed_roi(value: float | None) -> str:
    if value is None:
        return "-"
    percent = value * 100
    sign = "+" if percent > 0 else ""
    return f"{sign}{percent:.1f}%"


def slip_status_label(status: str | None) -> str:
    if status == "won":
        return "Presa"
    if status == "lost":
        return "Persa"
    if status == "void":
        return "Annullata"
    return "In corso"


def pick_status_label(status: str | None) -> str:
    if status == "won":
        return "Presa"
    if status == "lost":
        return "Persa"
    if status == "void":
        return "Annullata"
    return "In corso"


STATUS_LEGEND = (
    "● Verde = Presa\n● Rosso = Persa\n● Grigio = In corso\n● Barrato/grigio scuro = Annullata"
)
VALUE_LEGEND = "PLAY = valore | BORDERLINE = vicino void | NO BET = sotto valore"


def account_status_label(status: str | None) -> str:
    if not status:
        return "n.d."
    return ACCOUNT_STATUS_LABELS.get(status, status)


def subscription_status_label(status: str | None) -> str:
    if not status:
        return "n.d."
    return SUBSCRIPTION_STATUS_LABELS.get(status, status)


def format_datetime_rome(value: datetime | None) -> str | None:
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(ROME_TZ)
    return local.strftime("%d/%m/%Y %H:%M")


def format_subscription_overview(
    *,
    plan_name: str | None,
    subscription_status: str | None,
    trial_ends_at: datetime | None,
    expires_at: datetime | None,
    auto_renew: bool,
    cancel_at_period_end: bool,
    payment_failed: bool,
    include_subscription_commands: bool = True,
    feedback_url: str | None = None,
) -> str:
    plan_label = (plan_name or "Free").strip() or "Free"
    status = (subscription_status or "").strip().lower()
    lines = [
        f"Piano attuale: {plan_label}",
        f"Stato abbonamento: {subscription_status_label(subscription_status)}",
    ]

    trial_line = format_datetime_rome(trial_ends_at)
    expiry_line = format_datetime_rome(expires_at)
    if status == "trialing" and trial_line:
        lines.append(f"Periodo di prova fino al: {trial_line} (ora italiana)")

    if cancel_at_period_end and expiry_line:
        lines.append(f"Cancellazione programmata al: {expiry_line} (ora italiana)")
    elif auto_renew and expiry_line and status in {"active", "trialing"}:
        lines.append(f"Prossimo rinnovo stimato: {expiry_line} (ora italiana)")
    elif expiry_line:
        lines.append(f"Scadenza: {expiry_line} (ora italiana)")

    if payment_failed:
        if include_subscription_commands:
            lines.append(
                "Pagamento non riuscito rilevato. Usa /gestisci_abbonamento per aggiornare la fatturazione."
            )
        else:
            lines.append("Pagamento non riuscito rilevato. Contatta il supporto.")

    if status in {"expired", "canceled"}:
        if include_subscription_commands:
            lines.append("Per riattivare il premium usa /abbonati.")
        else:
            lines.append("Per riattivare il premium contatta il supporto.")

    return append_message_footer(
        "\n".join(lines),
        feedback_url=feedback_url,
        include_disclaimer=False,
    )


def format_last_updated(value: Any) -> str | None:
    """Human-readable last-update line for public bot replies (Rome time)."""
    if value is None or value == "":
        return None
    dt: datetime | None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return f"Ultimo aggiornamento: {text}"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(ROME_TZ)
    return f"Ultimo aggiornamento: {local.strftime('%d/%m/%Y %H:%M')} (ora italiana)"


def format_feedback_line(feedback_url: str | None) -> str | None:
    if not isinstance(feedback_url, str):
        return None
    url = feedback_url.strip()
    if not url:
        return None
    return f"Feedback / segnalazioni: {url}"


def format_user_error(message: str | None = None) -> str:
    """Uniform public error copy (no stack traces / internal detail dumps)."""
    body = (message or "").strip() or USER_ERROR_FALLBACK
    # Avoid leaking raw HTTP/JSON payloads that may contain technical tokens.
    lowered = body.lower()
    if any(token in lowered for token in ("traceback", "sqlalchemy", "psycopg", "jwt")):
        body = USER_ERROR_FALLBACK
    return f"{body}\n\n{DISCLAIMER}"


def append_message_footer(
    text: str,
    *,
    last_updated: Any = None,
    feedback_url: str | None = None,
    include_disclaimer: bool = True,
) -> str:
    """Append last-update, disclaimer and optional feedback in a stable order."""
    parts = [text.rstrip()]
    last_line = format_last_updated(last_updated)
    if last_line:
        parts.append(last_line)
    if include_disclaimer and DISCLAIMER not in text:
        parts.append(DISCLAIMER)
    feedback = format_feedback_line(feedback_url)
    if feedback:
        parts.append(feedback)
    return "\n\n".join(parts)


def format_help_text(
    *,
    feedback_url: str | None = None,
    include_fixtures: bool = True,
    include_slips: bool = True,
    include_statistics: bool = True,
    include_subscription_commands: bool = True,
    include_notifications: bool = True,
    include_feedback: bool = True,
) -> str:
    return append_message_footer(
        build_help_text(
            include_fixtures=include_fixtures,
            include_slips=include_slips,
            include_statistics=include_statistics,
            include_subscription_commands=include_subscription_commands,
            include_notifications=include_notifications,
            include_feedback=include_feedback,
        ),
        feedback_url=feedback_url,
    )


def format_welcome_text(
    *,
    feedback_url: str | None = None,
    include_fixtures: bool = True,
    include_slips: bool = True,
    include_statistics: bool = True,
    include_subscription_commands: bool = True,
    include_notifications: bool = True,
    include_feedback: bool = True,
    include_terms: bool = True,
) -> str:
    return append_message_footer(
        build_welcome_text(
            include_fixtures=include_fixtures,
            include_slips=include_slips,
            include_statistics=include_statistics,
            include_subscription_commands=include_subscription_commands,
            include_notifications=include_notifications,
            include_feedback=include_feedback,
            include_terms=include_terms,
        ),
        feedback_url=feedback_url,
        # BETA_TERMS_TEXT (sempre incluso in build_welcome_text) copre gia' un
        # disclaimer piu' dettagliato: il breve DISCLAIMER qui sarebbe ridondante.
        include_disclaimer=False,
    )


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


def format_fixtures_empty(
    target_date: date | str,
    *,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    body = (
        f"Nessuna partita disponibile per {target_date}.\n\n"
        "Non ci sono incontri con pronostico per oggi, oppure l'aggiornamento "
        "non è ancora completo. Riprova più tardi."
    )
    return append_message_footer(
        body,
        last_updated=last_updated,
        feedback_url=feedback_url,
    )


def format_fixtures(items: list[dict[str, Any]], target_date: date | str) -> str:
    if not items:
        return format_fixtures_empty(target_date)

    lines = [format_fixtures_intro(items, target_date), ""]
    lines.append(format_fixture_group_text(items))
    return "\n\n".join(lines)


def format_fixtures_intro(
    items: list[dict[str, Any]] | None = None,
    target_date: date | str | None = None,
    *,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    del items  # count kept out of intro; legend-only like /schedine
    resolved = target_date or "oggi"
    body = (
        f"Partite di oggi ({resolved})\n\n"
        f"{STATUS_LEGEND}\n{VALUE_LEGEND}"
    )
    return append_message_footer(
        body,
        last_updated=last_updated,
        feedback_url=feedback_url,
    )


def format_fixture_group_text(
    items: list[dict[str, Any]],
    *,
    start_index: int = 1,
    series_label: str | None = None,
) -> str:
    lines = []
    if series_label:
        lines.append(series_label)
    for index, item in enumerate(items, start=start_index):
        tournament = item.get("tournament_name") or "-"
        surface = item.get("surface") or "-"
        lines.append(
            f"{index}. {_format_event_time(item.get('event_time'))} | {tournament} | {surface}\n"
            f"{_match_title(item)}\n"
            f"{format_fixture_prediction(item)}"
        )
    return "\n\n".join(lines)


def format_fixtures_photo_caption(
    target_date: date | str,
    start_index: int,
    end_index: int,
    total: int,
    *,
    series_label: str | None = None,
) -> str:
    lines = [f"Partite oggi {target_date} | {start_index}-{end_index} di {total}"]
    if series_label:
        lines.append(series_label)
    return "\n".join(lines)


def format_fixture_prediction(item: dict[str, Any]) -> str:
    prediction = item.get("prediction") or {}
    if not prediction:
        warning = item.get("prediction_warning") or "pronostico non disponibile"
        return f"Pronostico: n.d. ({warning})"

    winner = predicted_winner_name(item) or "n.d."
    confidence = prediction.get("confidence")
    void_odds = item.get("void_odds")
    value = item.get("value_decision") or "-"
    return (
        f"Predetto: {winner} | Conf. {_format_percent(confidence)} | "
        f"Void {_format_decimal(void_odds)} | Valore {value}"
    )


def format_player_search(items: list[dict[str, Any]], player: str) -> str:
    if not items:
        return f"Nessuna partita trovata per '{player}' nei prossimi 10 giorni."

    lines = [f"Risultati ricerca: {player}", DISCLAIMER, ""]
    lines.extend(format_prediction(item) for item in items)
    return "\n\n".join(lines)


def format_betting_slips_empty(
    slip_date: date | str,
    *,
    warnings: list[str] | None = None,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    suffix = f"\n\nNote: {'; '.join(warnings)}" if warnings else ""
    body = (
        f"Nessuna schedina disponibile per {slip_date}.{suffix}\n\n"
        "Può dipendere da margini insufficienti o da dati non ancora aggiornati. "
        "Riprova più tardi."
    )
    return append_message_footer(
        body,
        last_updated=last_updated,
        feedback_url=feedback_url,
    )


def format_betting_slips_intro(
    payload: dict[str, Any] | None = None,
    *,
    slip_date: str | None = None,
    min_edge_percent: float = 2.0,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    del min_edge_percent  # kept for call-site compatibility; not shown in intro
    resolved_date = slip_date or (payload or {}).get("date") or "oggi"
    body = f"Schedine di oggi ({resolved_date})\n\n{STATUS_LEGEND}\n{VALUE_LEGEND}"
    return append_message_footer(
        body,
        last_updated=last_updated,
        feedback_url=feedback_url,
    )


def format_betting_slip_text(slip: dict[str, Any], *, series_label: str | None = None) -> str:
    status = slip_status_label(slip.get("slip_status"))
    picks_won = slip.get("picks_won")
    picks_total = slip.get("picks_total") or len(slip.get("picks") or [])
    lines = [
        f"Schedina: {slip.get('label') or slip.get('slip_key') or 'Schedina'}",
    ]
    if series_label:
        lines.append(series_label)
    lines.append(f"Stato: {status} | {picks_won}/{picks_total} pick corrette")
    picks_void = slip.get("picks_void") or 0
    if picks_void:
        lines.append(f"Pick annullate: {picks_void} (escluse dalla quota effettiva)")
    description = slip.get("description")
    if description:
        lines.append(str(description))
    effective = slip.get("effective_combined_odds")
    combined = slip.get("combined_odds")
    if picks_void and effective is not None and effective != combined:
        odds_line = (
            f"Quota originale: {_format_decimal(combined)} | "
            f"Quota effettiva: {_format_decimal(effective)}"
        )
    else:
        odds_line = f"Quota combinata: {_format_decimal(combined)}"
    lines.extend(
        [
            odds_line,
            f"Ritorno potenziale: {_format_decimal(slip.get('potential_return'))}",
            f"Profitto potenziale: {_format_decimal(slip.get('potential_profit'))}",
        ]
    )

    picks = slip.get("picks") or []
    if not picks:
        lines.append("Nessun pick disponibile.")
        return "\n".join(lines)

    lines.append(
        "Pick (Ora | Torneo | Match | Pick | Media quote bookmakers | Void | Edge | ROI | Valore | Conf.):"
    )
    for index, pick in enumerate(picks, start=1):
        winner = slip_pick_winner_name(pick) or "n.d."
        tournament = pick.get("tournament_name") or "-"
        value = pick.get("value_decision") or "-"
        lifecycle_note = ""
        if pick.get("pick_status") == "void":
            lifecycle_note = f" · {pick.get('void_reason') or pick.get('match_lifecycle_label') or 'Annullata'}"
        elif pick.get("match_lifecycle_label") and pick.get("match_lifecycle_status") not in {
            None,
            "upcoming",
            "completed",
            # legacy aliases still accepted if an old payload is cached
            "scheduled",
            "finished",
        }:
            lifecycle_note = f" · {pick.get('match_lifecycle_label')}"
        lines.append(
            f"{index}. [{pick_status_label(pick.get('pick_status'))}] "
            f"{_format_event_time(pick.get('event_time'))} | {tournament} | {_match_title(pick)}{lifecycle_note}\n"
            f"   Pick: {winner} | Q {_format_decimal(pick.get('odds'))} | "
            f"Void {_format_decimal(pick.get('void_odds'))} | "
            f"Edge {_format_signed_percent(pick.get('edge_percent'))} | "
            f"ROI {_format_signed_roi(pick.get('expected_roi'))} | "
            f"{value} | Conf. {_format_percent(pick.get('confidence'))}"
        )
    return "\n".join(lines)


def format_betting_slip_photo_caption(
    slip: dict[str, Any],
    *,
    series_label: str | None = None,
) -> str:
    label = slip.get("label") or slip.get("slip_key") or "Schedina"
    status = slip_status_label(slip.get("slip_status"))
    picks_won = slip.get("picks_won")
    picks_total = slip.get("picks_total") or len(slip.get("picks") or [])
    lines = [f"{label} | {status} | {picks_won}/{picks_total} pick"]
    if series_label:
        lines.append(series_label)
    lines.append(
        f"Quota {_format_decimal(slip.get('combined_odds'))} | "
        f"Profitto {_format_decimal(slip.get('potential_profit'))}"
    )
    return "\n".join(lines)


def format_betting_slips(
    payload: dict[str, Any],
    *,
    min_edge_percent: float = 2.0,
    series_label: str | None = None,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    slips = payload.get("slips") or []
    slip_date = payload.get("date") or "oggi"
    if not slips:
        return format_betting_slips_empty(
            slip_date,
            warnings=list(payload.get("warnings") or []),
            last_updated=last_updated,
            feedback_url=feedback_url,
        )

    lines = [
        format_betting_slips_intro(
            payload,
            min_edge_percent=min_edge_percent,
            last_updated=last_updated,
            feedback_url=feedback_url,
        )
    ]
    for slip in slips:
        lines.append("")
        lines.append(format_betting_slip_text(slip, series_label=series_label))
    return "\n".join(lines)


def format_bot_stats_intro(
    *,
    from_date: Any = None,
    to_date: Any = None,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    if from_date and to_date:
        range_text = f"{from_date} → {to_date}"
    else:
        range_text = "storico completo"
    body = (
        f"Statistiche bot ({range_text})\n"
        "Confronto delle predizioni (etichette pubbliche, senza nomi tecnici)."
    )
    return append_message_footer(
        body,
        last_updated=last_updated,
        feedback_url=feedback_url,
    )


def format_bot_stats_empty(
    *,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> str:
    return append_message_footer(
        "Nessuna statistica disponibile al momento.\n"
        "Riprova dopo l'aggiornamento giornaliero.",
        last_updated=last_updated,
        feedback_url=feedback_url,
    )


def format_bot_stats_text(series: list[dict[str, Any]]) -> str:
    if not series:
        return format_bot_stats_empty()

    lines = ["Andamento predizioni"]
    for entry in series:
        prediction = entry.get("prediction") or {}
        slip = entry.get("slip") or {}
        lines.extend(
            [
                "",
                str(entry.get("label") or "Predizione"),
                (
                    f"Partite: accuratezza {_format_stats_pct(prediction.get('accuracy_pct'))} | "
                    f"risolte {prediction.get('predictions_resolved', 0)} | "
                    f"corrette {prediction.get('predictions_correct', 0)} | "
                    f"perse {prediction.get('predictions_lost', 0)} | "
                    f"in corso {prediction.get('pending', 0)}"
                ),
                (
                    f"Profitto partite: {_format_stats_decimal(prediction.get('theoretical_profit_units'))} | "
                    f"ROI {_format_stats_pct(prediction.get('theoretical_roi_pct'))}"
                ),
                (
                    f"Schedine: win rate {_format_stats_pct(slip.get('slip_win_rate_pct'))} | "
                    f"prese {slip.get('slips_won', 0)} | "
                    f"perse {slip.get('slips_lost', 0)} | "
                    f"in corso {slip.get('slips_pending', 0)}"
                ),
                (
                    f"Hit pick {_format_stats_pct(slip.get('pick_hit_rate_pct'))} | "
                    f"Profitto schedine {_format_stats_decimal(slip.get('theoretical_profit_units'))} | "
                    f"ROI {_format_stats_pct(slip.get('theoretical_roi_pct'))}"
                ),
            ]
        )
    return "\n".join(lines)


def _format_stats_pct(value: float | None) -> str:
    if value is None:
        return "n.d."
    return f"{float(value):.1f}%"


def _format_stats_decimal(value: float | None) -> str:
    if value is None:
        return "n.d."
    return f"{float(value):+.2f}"


def format_notification_predictions(
    items: list[dict[str, Any]],
    target_date: date | str,
    *,
    max_items: int = 12,
) -> str:
    """Compact push text for today's fixtures/predictions (no images)."""
    if not items:
        return format_fixtures_empty(target_date)

    lines = [
        f"Pronostici del giorno ({target_date})",
        f"{len(items)} partite disponibili.",
        "",
        DISCLAIMER,
        "",
    ]
    for item in items[:max_items]:
        prediction = item.get("prediction") if isinstance(item.get("prediction"), dict) else {}
        winner = (
            item.get("predicted_winner")
            or (prediction or {}).get("predicted_winner")
            or "n.d."
        )
        title = _match_title(item)
        time_label = _format_event_time(item.get("event_time"))
        lines.append(f"• {time_label} {title} → {winner}")
    if len(items) > max_items:
        lines.append(f"… e altre {len(items) - max_items} partite.")
    lines.append("")
    lines.append("Dettagli: /partite oppure /schedine")
    return "\n".join(lines)


def format_notification_results(
    target_date: date | str,
    day_stats: dict[str, Any] | None,
) -> str:
    """Push digest for settled predictions on a given day."""
    if not day_stats:
        body = (
            f"Riepilogo risultati {target_date}\n\n"
            "Nessun dato disponibile per questa giornata."
        )
        return append_message_footer(body)

    total = int(day_stats.get("predictions_total") or 0)
    resolved = int(day_stats.get("predictions_resolved") or 0)
    correct = int(day_stats.get("predictions_correct") or 0)
    lost = int(day_stats.get("predictions_lost") or 0)
    pending = int(day_stats.get("pending") or 0)
    accuracy = day_stats.get("accuracy_pct")
    roi = day_stats.get("theoretical_roi_pct")
    profit = day_stats.get("theoretical_profit_units")

    if total == 0 and resolved == 0:
        body = (
            f"Riepilogo risultati {target_date}\n\n"
            "Nessun pronostico da valutare per questa giornata."
        )
        return append_message_footer(body)

    lines = [
        f"Riepilogo risultati {target_date}",
        "",
        f"Pronostici: {total} | Chiusi: {resolved} | Ok: {correct} | Ko: {lost} | In corso: {pending}",
        f"Accuratezza: {_format_stats_pct(float(accuracy) if accuracy is not None else None)}",
        (
            f"Profitto teorico: {_format_stats_decimal(float(profit) if profit is not None else None)} | "
            f"ROI: {_format_stats_pct(float(roi) if roi is not None else None)}"
        ),
        "",
        "Andamento completo: /statistiche",
    ]
    return append_message_footer("\n".join(lines))


def format_notification_preferences(user: Any) -> str:
    """Show current push preferences for /notifiche."""
    master = "ON" if getattr(user, "notifications_enabled", True) else "OFF"
    preds = "ON" if getattr(user, "notify_predictions", True) else "OFF"
    results = "ON" if getattr(user, "notify_results", True) else "OFF"
    empty = "ON" if getattr(user, "notify_empty_day", False) else "OFF"
    return "\n".join(
        [
            "Preferenze notifiche",
            "",
            f"Master: {master}",
            f"Pronostici del giorno: {preds}",
            f"Riepilogo risultati: {results}",
            f"Giorno senza partite: {empty}",
            "",
            "Comandi:",
            "/notifiche on | off — attiva/disattiva tutte",
            "/notifiche pronostici on|off",
            "/notifiche risultati on|off",
            "/notifiche vuoto on|off",
        ]
    )


def feedback_category_label(category: str | None) -> str:
    if not category:
        return "n.d."
    return FEEDBACK_CATEGORY_LABELS.get(category, category)


def format_feedback_saved(
    *,
    category: str,
    rating: int,
    feedback_id: int | None = None,
) -> str:
    lines = [
        FEEDBACK_SAVED_TEXT,
        "",
        f"Categoria: {feedback_category_label(category)}",
        f"Valutazione: {rating}/5",
    ]
    if feedback_id is not None:
        lines.append(f"Riferimento: #{feedback_id}")
    return "\n".join(lines)
