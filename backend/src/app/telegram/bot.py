from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from backend.src.app.services.telegram_feedback import (
    TelegramFeedbackError,
    create_telegram_feedback_safe,
)
from backend.src.app.services.telegram_users import (
    TelegramUserError,
    accept_telegram_terms_safe,
    access_denial_message,
    check_telegram_access_safe,
    get_telegram_user_safe,
    register_or_touch_on_start_safe,
    update_notification_preferences_safe,
)
from backend.src.app.schemas.telegram_users import TelegramNotificationPreferencesUpdate

from .access import require_beta_access
from .client import BackendApiClient, BackendApiError
from .config import TelegramSettings, get_telegram_settings
from .dates import parse_date_or_offset, prediction_window, today_rome
from .images import render_betting_slip_png, render_bot_stats_png, render_fixtures_png
from .messages import (
    FEEDBACK_ASK_MESSAGE_TEXT,
    FEEDBACK_ASK_RATING_TEXT,
    FEEDBACK_CANCELLED_TEXT,
    FEEDBACK_CATEGORY_LABELS,
    FEEDBACK_EMPTY_MESSAGE_TEXT,
    FEEDBACK_MESSAGE_TOO_LONG_TEXT,
    FEEDBACK_SAVE_FAILED_TEXT,
    FEEDBACK_START_TEXT,
    LOADING_PARTITE,
    LOADING_SCHEDINE,
    LOADING_STATISTICHE,
    WELCOME_TEXT,
    account_status_label,
    append_message_footer,
    format_betting_slip_photo_caption,
    format_betting_slip_text,
    format_betting_slips,
    format_betting_slips_intro,
    format_bot_stats_empty,
    format_bot_stats_intro,
    format_bot_stats_text,
    format_feedback_saved,
    format_fixture_group_text,
    format_fixtures_empty,
    format_fixtures_intro,
    format_fixtures_photo_caption,
    format_help_text,
    format_notification_preferences,
    format_player_search,
    format_predictions_day,
    format_predictions_summary,
    format_user_error,
    split_message,
)
from .fixture_value import enrich_fixtures_with_value
from .public_labels import (
    accuracy_by_model_name,
    build_public_labels,
    build_stats_series,
)
from .slips_compare import select_distinct_fixture_models, select_distinct_model_payloads
from .rate_limit import rate_limited
from .tracking import track_callback_query, tracked


logger = logging.getLogger(__name__)

MENU_PARTITE = "menu:partite"
MENU_SCHEDINE = "menu:schedine"
MENU_STATISTICHE = "menu:statistiche"
MENU_HELP = "menu:help"

# ConversationHandler states for /feedback (in-memory only; nothing persisted until submit).
FEEDBACK_CATEGORY, FEEDBACK_RATING, FEEDBACK_MESSAGE = range(3)
FEEDBACK_CB_PREFIX_CAT = "fb:cat:"
FEEDBACK_CB_PREFIX_RATE = "fb:rate:"
FEEDBACK_CB_CANCEL = "fb:cancel"
FEEDBACK_USER_DATA_KEY = "feedback_draft"
FEEDBACK_MESSAGE_MAX = 2000


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Partite", callback_data=MENU_PARTITE),
                InlineKeyboardButton("Schedine", callback_data=MENU_SCHEDINE),
            ],
            [
                InlineKeyboardButton("Statistiche", callback_data=MENU_STATISTICHE),
                InlineKeyboardButton("Aiuto", callback_data=MENU_HELP),
            ],
        ]
    )


async def _answer_callback(update: Update) -> None:
    query = update.callback_query
    if query is None:
        return
    try:
        await query.answer()
    except Exception:
        logger.debug("Telegram callback answer failed", exc_info=True)


def _with_callback_answer(handler: Callable[..., Awaitable[Any]]):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        await _answer_callback(update)
        return await handler(update, context)

    wrapper.__name__ = getattr(handler, "__name__", "callback_wrapper")
    wrapper.__wrapped__ = handler  # type: ignore[attr-defined]
    return wrapper


@rate_limited()
@tracked(action="/start", event_type="command")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    settings = _settings(context)
    if user is None:
        await _reply(update, format_user_error("Utente Telegram non disponibile."))
        return

    invite_origin = _invite_origin_from_start(context)
    chat = update.effective_chat
    registered = register_or_touch_on_start_safe(
        telegram_user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        invite_origin=invite_origin,
        chat_id=chat.id if chat is not None else None,
    )

    lines = [WELCOME_TEXT, ""]
    if registered is None:
        lines.append(
            "Registrazione temporaneamente non disponibile. Riprova tra poco."
        )
        await _reply(
            update,
            append_message_footer(
                "\n".join(lines),
                feedback_url=settings.telegram_feedback_url,
            ),
            reply_markup=main_menu_keyboard(),
        )
        return

    lines.append(f"Stato account: {account_status_label(registered.status)}.")
    if registered.invite_origin:
        lines.append(f"Origine invito: {registered.invite_origin}.")

    if settings.telegram_terms_required and not registered.terms_accepted:
        lines.append("")
        lines.append(
            "Per usare i comandi beta devi accettare le condizioni: /accetta_condizioni"
        )
    elif settings.telegram_whitelist_enabled and registered.status != "active":
        if registered.status == "invited":
            lines.append("")
            lines.append(
                "Sei in lista di attesa. Un amministratore deve attivare il tuo accesso beta."
            )
        elif registered.status in {"suspended", "blocked"}:
            lines.append("")
            lines.append(access_denial_message(
                check_telegram_access_safe(
                    telegram_user_id=user.id,
                    touch_last_access=False,
                )
            ))

    await _reply(
        update,
        append_message_footer(
            "\n".join(lines),
            feedback_url=settings.telegram_feedback_url,
        ),
        reply_markup=main_menu_keyboard(),
    )


@rate_limited()
@tracked(action="/help", event_type="command")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    await _reply(
        update,
        format_help_text(feedback_url=settings.telegram_feedback_url),
        reply_markup=main_menu_keyboard(),
    )


@rate_limited()
@tracked(action="/accetta_condizioni", event_type="command")
async def accetta_condizioni(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None:
        await _reply(update, format_user_error("Utente Telegram non disponibile."))
        return
    settings = _settings(context)
    if not settings.telegram_terms_required:
        await _reply(update, "Al momento non è richiesta l'accettazione delle condizioni.")
        return
    try:
        accepted = accept_telegram_terms_safe(telegram_user_id=user.id)
    except TelegramUserError as exc:
        await _reply(update, format_user_error(exc.message))
        return
    if accepted is None:
        await _reply(update, format_user_error("Impossibile registrare l'accettazione. Riprova tra poco."))
        return
    await _reply(
        update,
        f"Condizioni accettate (versione {accepted.terms_version}). "
        f"Stato account: {account_status_label(accepted.status)}.",
        reply_markup=main_menu_keyboard(),
    )


def _parse_bool_flag(raw: str) -> bool | None:
    cleaned = raw.strip().lower()
    if cleaned in {"on", "si", "sì", "yes", "true", "1", "attiva"}:
        return True
    if cleaned in {"off", "no", "false", "0", "disattiva"}:
        return False
    return None


@rate_limited()
@tracked(action="/notifiche", event_type="command")
async def notifiche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show or update push notification preferences."""
    user = update.effective_user
    if user is None:
        await _reply(update, format_user_error("Utente Telegram non disponibile."))
        return

    args = [a.strip().lower() for a in (context.args or []) if a.strip()]
    if not args:
        current = get_telegram_user_safe(telegram_user_id=user.id)
        if current is None:
            await _reply(update, "Non sei ancora registrato. Usa /start per iniziare.")
            return
        await _reply(update, format_notification_preferences(current))
        return

    payload = TelegramNotificationPreferencesUpdate()
    if len(args) == 1:
        flag = _parse_bool_flag(args[0])
        if flag is None:
            await _reply(
                update,
                "Uso: /notifiche | /notifiche on|off | "
                "/notifiche pronostici|risultati|vuoto on|off",
            )
            return
        payload.notifications_enabled = flag
    elif len(args) >= 2:
        kind = args[0]
        flag = _parse_bool_flag(args[1])
        if flag is None:
            await _reply(update, "Valore non valido. Usa on oppure off.")
            return
        if kind in {"pronostici", "predictions", "partite"}:
            payload.notify_predictions = flag
        elif kind in {"risultati", "results"}:
            payload.notify_results = flag
        elif kind in {"vuoto", "empty", "empty_day"}:
            payload.notify_empty_day = flag
        else:
            await _reply(
                update,
                "Tipo sconosciuto. Usa: pronostici, risultati oppure vuoto.",
            )
            return
    else:
        await _reply(update, "Uso: /notifiche on|off oppure /notifiche <tipo> on|off")
        return

    try:
        updated = update_notification_preferences_safe(
            telegram_user_id=user.id,
            payload=payload,
        )
    except TelegramUserError as exc:
        await _reply(update, format_user_error(exc.message))
        return
    if updated is None:
        await _reply(update, format_user_error("Impossibile aggiornare le preferenze."))
        return
    await _reply(update, format_notification_preferences(updated))


def feedback_category_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    items = list(FEEDBACK_CATEGORY_LABELS.items())
    for index in range(0, len(items), 2):
        chunk = items[index : index + 2]
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{FEEDBACK_CB_PREFIX_CAT}{key}",
                )
                for key, label in chunk
            ]
        )
    rows.append(
        [InlineKeyboardButton("Annulla", callback_data=FEEDBACK_CB_CANCEL)]
    )
    return InlineKeyboardMarkup(rows)


def feedback_rating_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    str(value),
                    callback_data=f"{FEEDBACK_CB_PREFIX_RATE}{value}",
                )
                for value in range(1, 6)
            ],
            [InlineKeyboardButton("Annulla", callback_data=FEEDBACK_CB_CANCEL)],
        ]
    )


def _clear_feedback_draft(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop(FEEDBACK_USER_DATA_KEY, None)


@rate_limited()
@tracked(action="/feedback", event_type="command")
async def feedback_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Start /feedback conversation: category → rating → message."""
    user = update.effective_user
    if user is None:
        await _reply(update, format_user_error("Utente Telegram non disponibile."))
        return ConversationHandler.END

    context.user_data[FEEDBACK_USER_DATA_KEY] = {
        "telegram_user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }
    await _reply(
        update,
        FEEDBACK_START_TEXT,
        reply_markup=feedback_category_keyboard(),
    )
    return FEEDBACK_CATEGORY


async def feedback_choose_category(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or not query.data:
        return FEEDBACK_CATEGORY
    await _answer_callback(update)
    raw = query.data.removeprefix(FEEDBACK_CB_PREFIX_CAT)
    if raw not in FEEDBACK_CATEGORY_LABELS:
        await _reply(update, "Categoria non valida. Scegli un pulsante oppure /annulla.")
        return FEEDBACK_CATEGORY

    draft = context.user_data.setdefault(FEEDBACK_USER_DATA_KEY, {})
    draft["category"] = raw
    await _reply(
        update,
        f"Categoria: {FEEDBACK_CATEGORY_LABELS[raw]}\n\n{FEEDBACK_ASK_RATING_TEXT}",
        reply_markup=feedback_rating_keyboard(),
    )
    return FEEDBACK_RATING


async def feedback_choose_rating(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None or not query.data:
        return FEEDBACK_RATING
    await _answer_callback(update)
    raw = query.data.removeprefix(FEEDBACK_CB_PREFIX_RATE)
    try:
        rating = int(raw)
    except ValueError:
        rating = 0
    if rating < 1 or rating > 5:
        await _reply(update, "Valutazione non valida. Scegli un voto da 1 a 5 oppure /annulla.")
        return FEEDBACK_RATING

    draft = context.user_data.setdefault(FEEDBACK_USER_DATA_KEY, {})
    draft["rating"] = rating
    await _reply(update, FEEDBACK_ASK_MESSAGE_TEXT)
    return FEEDBACK_MESSAGE


async def feedback_receive_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Final step: persist only the completed feedback (no intermediate drafts)."""
    message = update.effective_message
    text = (message.text if message and message.text else "") or ""
    cleaned = text.strip()
    if not cleaned:
        await _reply(update, FEEDBACK_EMPTY_MESSAGE_TEXT)
        return FEEDBACK_MESSAGE
    if len(cleaned) > FEEDBACK_MESSAGE_MAX:
        await _reply(update, FEEDBACK_MESSAGE_TOO_LONG_TEXT)
        return FEEDBACK_MESSAGE

    draft = context.user_data.get(FEEDBACK_USER_DATA_KEY) or {}
    category = draft.get("category")
    rating = draft.get("rating")
    telegram_user_id = draft.get("telegram_user_id")
    if not category or not rating or not telegram_user_id:
        _clear_feedback_draft(context)
        await _reply(
            update,
            format_user_error("Sessione feedback scaduta. Riparti con /feedback."),
        )
        return ConversationHandler.END

    try:
        saved = create_telegram_feedback_safe(
            telegram_user_id=int(telegram_user_id),
            username=draft.get("username"),
            first_name=draft.get("first_name"),
            last_name=draft.get("last_name"),
            category=str(category),
            rating=int(rating),
            message=cleaned,
        )
    except TelegramFeedbackError as exc:
        await _reply(update, format_user_error(exc.message))
        return FEEDBACK_MESSAGE

    _clear_feedback_draft(context)
    if saved is None:
        await _reply(update, FEEDBACK_SAVE_FAILED_TEXT)
        return ConversationHandler.END

    await _reply(
        update,
        format_feedback_saved(
            category=saved.category,
            rating=saved.rating,
            feedback_id=saved.id,
        ),
        reply_markup=main_menu_keyboard(),
    )
    return ConversationHandler.END


async def feedback_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    _clear_feedback_draft(context)
    if update.callback_query is not None:
        await _answer_callback(update)
    await _reply(update, FEEDBACK_CANCELLED_TEXT, reply_markup=main_menu_keyboard())
    return ConversationHandler.END


def build_feedback_conversation() -> ConversationHandler:
    """Multi-step /feedback without persisting intermediate conversation turns."""
    return ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_start)],
        states={
            FEEDBACK_CATEGORY: [
                CallbackQueryHandler(
                    feedback_choose_category,
                    pattern=rf"^{FEEDBACK_CB_PREFIX_CAT}",
                ),
                CallbackQueryHandler(
                    feedback_cancel,
                    pattern=rf"^{FEEDBACK_CB_CANCEL}$",
                ),
            ],
            FEEDBACK_RATING: [
                CallbackQueryHandler(
                    feedback_choose_rating,
                    pattern=rf"^{FEEDBACK_CB_PREFIX_RATE}",
                ),
                CallbackQueryHandler(
                    feedback_cancel,
                    pattern=rf"^{FEEDBACK_CB_CANCEL}$",
                ),
            ],
            FEEDBACK_MESSAGE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    feedback_receive_message,
                ),
            ],
        },
        fallbacks=[
            CommandHandler("annulla", feedback_cancel),
            CommandHandler("cancel", feedback_cancel),
            CallbackQueryHandler(
                feedback_cancel,
                pattern=rf"^{FEEDBACK_CB_CANCEL}$",
            ),
        ],
        allow_reentry=True,
        name="telegram_feedback",
        persistent=False,
    )


@tracked(event_type="message")
async def log_unhandled_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = message.text if message and message.text else None
    command = text.split()[0] if text and text.startswith("/") else None
    logger.debug(
        "Telegram unhandled update has_message=%s has_text=%s command=%s",
        message is not None,
        text is not None,
        command,
    )


async def pronostici(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lines = [
        "Pronostici disponibili:",
        "",
        "/giorno 0 - oggi",
        "/giorno 1 - domani",
    ]
    lines.extend(f"/giorno {offset}" for offset in range(2, 11))
    lines.append("")
    lines.append("/10giorni - riepilogo compatto")
    await _reply(update, "\n".join(lines))


async def giorno(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        target_date = parse_date_or_offset(_first_arg(context), today=today_rome())
    except ValueError as exc:
        await _reply(update, format_user_error(str(exc)))
        return

    settings = _settings(context)
    try:
        items = await _api(context).predictions(
            model_version=settings.telegram_model_version,
            model_name=settings.telegram_model_name,
            from_date=target_date,
            to_date=target_date,
            status="upcoming",
            limit=200,
        )
    except BackendApiError as exc:
        await _reply(update, format_user_error(exc.message))
        return

    await _reply(update, format_predictions_day(items, target_date))


async def ten_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    start_date, end_date = prediction_window(today=today_rome(), days=10)
    try:
        items = await _api(context).predictions(
            model_version=settings.telegram_model_version,
            model_name=settings.telegram_model_name,
            from_date=start_date,
            to_date=end_date,
            status="upcoming",
            limit=200,
        )
    except BackendApiError as exc:
        await _reply(update, format_user_error(exc.message))
        return

    await _reply(update, format_predictions_summary(items))


@rate_limited(expensive=True)
@tracked(action="/schedine", event_type="command")
@require_beta_access()
async def schedine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_with_loading(update, LOADING_SCHEDINE, _schedine_body, context)


@rate_limited(expensive=True)
@tracked(action="/partite", event_type="command")
@require_beta_access()
async def partite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_with_loading(update, LOADING_PARTITE, _partite_body, context)


@rate_limited(expensive=True)
@tracked(action="/statistiche", event_type="command")
@require_beta_access()
async def statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _run_with_loading(update, LOADING_STATISTICHE, _statistiche_body, context)


async def _schedine_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_date = today_rome()
    settings = _settings(context)
    api = _api(context)
    fallback_models = _fallback_models(settings)
    try:
        versions_payload = await api.models_versions_results(target_date=target_date)
        last_updated = versions_payload.get("last_updated_at")
        model_names = _model_names_from_versions(
            versions_payload,
            model_version=settings.telegram_model_version,
            fallback=fallback_models,
        )
        payloads: list[dict] = []
        for model_name in model_names:
            payload = await api.daily_betting_slips(
                slip_date=target_date,
                model_version=settings.telegram_model_version,
                model_name=model_name,
                stake=settings.telegram_default_stake,
                slip_count=settings.telegram_slip_count,
                min_edge_percent=settings.telegram_min_edge_percent,
            )
            payloads.append(payload)
    except BackendApiError as exc:
        await _reply(update, format_user_error(exc.message))
        return

    selected = select_distinct_model_payloads(
        payloads,
        preferred_model_name=settings.telegram_model_name,
    )
    public_labels = await _public_labels_for_models(
        api,
        model_version=settings.telegram_model_version,
        model_names=[str(payload.get("model_name") or "") for payload in selected],
    )
    await _reply_betting_slips(
        update,
        selected,
        min_edge_percent=settings.telegram_min_edge_percent,
        slip_date=str(target_date),
        public_labels=public_labels,
        last_updated=last_updated,
        feedback_url=settings.telegram_feedback_url,
    )


async def _partite_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_date = today_rome()
    settings = _settings(context)
    api = _api(context)
    fallback_models = _fallback_models(settings)
    try:
        versions_payload = await api.models_versions_results(target_date=target_date)
        last_updated = versions_payload.get("last_updated_at")
        model_names = _model_names_from_versions(
            versions_payload,
            model_version=settings.telegram_model_version,
            fallback=fallback_models,
        )
        model_items: list[tuple[str, list[dict]]] = []
        for model_name in model_names:
            items = await api.predictions(
                model_version=settings.telegram_model_version,
                model_name=model_name,
                from_date=target_date,
                to_date=target_date,
                status="upcoming",
                limit=200,
            )
            smva_items: list[dict] = []
            try:
                smva = await api.single_match_value(
                    from_date=target_date,
                    to_date=target_date,
                    model_version=settings.telegram_model_version,
                    model_name=model_name,
                    min_edge_percent=settings.telegram_min_edge_percent,
                    status="upcoming",
                    limit=200,
                )
                smva_items = list(smva.get("items") or [])
            except BackendApiError:
                logger.exception("SMVA non disponibile per Telegram /partite; uso fallback locale.")
            enriched = enrich_fixtures_with_value(
                items,
                min_edge_percent=settings.telegram_min_edge_percent,
                smva_items=smva_items,
            )
            model_items.append((model_name, enriched))
    except BackendApiError as exc:
        await _reply(update, format_user_error(exc.message))
        return

    selected = select_distinct_fixture_models(
        model_items,
        preferred_model_name=settings.telegram_model_name,
    )
    public_labels = await _public_labels_for_models(
        api,
        model_version=settings.telegram_model_version,
        model_names=[name for name, _items in selected],
    )
    await _reply_fixtures(
        update,
        selected,
        target_date,
        min_edge_percent=settings.telegram_min_edge_percent,
        public_labels=public_labels,
        last_updated=last_updated,
        feedback_url=settings.telegram_feedback_url,
    )


async def _statistiche_body(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    api = _api(context)
    fallback_models = _fallback_models(settings)
    try:
        versions_payload = await api.models_versions_results(target_date=today_rome())
        last_updated = versions_payload.get("last_updated_at")
        model_names = _model_names_from_versions(
            versions_payload,
            model_version=settings.telegram_model_version,
            fallback=fallback_models,
        )
        prediction_summary = await api.prediction_summary(
            model_version=settings.telegram_model_version,
        )
        slip_stats = await api.betting_slip_stats_by_model(
            stake=settings.telegram_default_stake,
            all_time=True,
        )
    except BackendApiError as exc:
        await _reply(update, format_user_error(exc.message))
        return

    series = build_stats_series(
        model_names=model_names,
        model_version=settings.telegram_model_version,
        prediction_summary=prediction_summary,
        slip_stats=slip_stats,
    )
    from_date = slip_stats.get("from_date")
    to_date = slip_stats.get("to_date")
    await _reply(
        update,
        format_bot_stats_intro(
            from_date=from_date,
            to_date=to_date,
            last_updated=last_updated,
            feedback_url=settings.telegram_feedback_url,
        ),
    )
    if not series:
        await _reply(
            update,
            format_bot_stats_empty(
                last_updated=last_updated,
                feedback_url=settings.telegram_feedback_url,
            ),
        )
        return
    message = _effective_message(update)
    try:
        image = render_bot_stats_png(
            series,
            from_date=str(from_date) if from_date else None,
            to_date=str(to_date) if to_date else None,
        )
        if message:
            await message.reply_photo(
                photo=image,
                caption="Andamento bot · partite e schedine",
            )
    except Exception:
        logger.exception("Impossibile generare immagine statistiche Telegram.")
        await _reply(update, format_bot_stats_text(series))


async def cerca(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    player = " ".join(context.args).strip()
    if not player:
        await _reply(update, "Uso: /cerca <nome giocatore>")
        return

    settings = _settings(context)
    start_date = today_rome()
    end_date = start_date + timedelta(days=10)
    try:
        items = await _api(context).predictions(
            model_version=settings.telegram_model_version,
            model_name=settings.telegram_model_name,
            from_date=start_date,
            to_date=end_date,
            status="upcoming",
            limit=200,
            player=player,
        )
    except BackendApiError as exc:
        await _reply(update, format_user_error(exc.message))
        return

    await _reply(update, format_player_search(items, player))


def _effective_message(update: Update) -> Message | None:
    return update.effective_message


async def _reply(
    update: Update,
    text: str,
    *,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    message = _effective_message(update)
    if message is None:
        return
    chunks = split_message(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        await message.reply_text(chunk, reply_markup=markup)


async def _run_with_loading(
    update: Update,
    loading_text: str,
    body: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]],
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    message = _effective_message(update)
    loading_msg: Message | None = None
    if message is not None:
        try:
            loading_msg = await message.reply_text(loading_text)
        except Exception:
            logger.exception("Impossibile inviare messaggio di caricamento Telegram.")
    try:
        await body(update, context)
    finally:
        if loading_msg is not None:
            try:
                await loading_msg.delete()
            except Exception:
                logger.debug("Impossibile eliminare messaggio di caricamento Telegram.", exc_info=True)


async def _reply_betting_slips(
    update: Update,
    payloads: list[dict] | dict,
    *,
    min_edge_percent: float = 2.0,
    slip_date: str | None = None,
    public_labels: dict[str, str] | None = None,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> None:
    message = _effective_message(update)
    if message is None:
        return

    if isinstance(payloads, dict):
        payloads = [payloads]

    non_empty = [payload for payload in payloads if payload.get("slips")]
    if not non_empty:
        empty_payload = payloads[0] if payloads else {"date": slip_date, "slips": []}
        await _reply(
            update,
            format_betting_slips(
                empty_payload,
                min_edge_percent=min_edge_percent,
                last_updated=last_updated,
                feedback_url=feedback_url,
            ),
        )
        return

    resolved_date = slip_date or str(non_empty[0].get("date") or "oggi")
    show_series_labels = len(non_empty) > 1
    labels = public_labels or {}
    await _reply(
        update,
        format_betting_slips_intro(
            slip_date=resolved_date,
            min_edge_percent=min_edge_percent,
            last_updated=last_updated,
            feedback_url=feedback_url,
        ),
    )

    for payload in non_empty:
        model_name = str(payload.get("model_name") or "")
        series_label = labels.get(model_name) if show_series_labels else None
        stake = payload.get("stake")
        for slip in payload.get("slips") or []:
            try:
                image = render_betting_slip_png(
                    slip,
                    slip_date=resolved_date,
                    stake=stake,
                    min_edge_percent=min_edge_percent,
                    series_label=series_label,
                )
                await message.reply_photo(
                    photo=image,
                    caption=format_betting_slip_photo_caption(slip, series_label=series_label),
                )
            except Exception:
                logger.exception("Impossibile generare immagine schedina Telegram.")
                await _reply(
                    update,
                    "Immagine non disponibile, invio il riepilogo testuale.\n\n"
                    f"{format_betting_slip_text(slip, series_label=series_label)}",
                )


async def _reply_fixtures(
    update: Update,
    model_items: list[tuple[str, list[dict]]] | list[dict],
    target_date,
    *,
    min_edge_percent: float = 2.0,
    public_labels: dict[str, str] | None = None,
    last_updated: Any = None,
    feedback_url: str | None = None,
) -> None:
    message = _effective_message(update)
    if message is None:
        return

    if not model_items:
        await _reply(
            update,
            format_fixtures_empty(
                target_date,
                last_updated=last_updated,
                feedback_url=feedback_url,
            ),
        )
        return

    # Backward-compatible: plain list of fixtures from a single model.
    if isinstance(model_items[0], dict):
        typed_items: list[tuple[str, list[dict]]] = [("", list(model_items))]  # type: ignore[arg-type]
    else:
        typed_items = [(str(name), list(items)) for name, items in model_items]  # type: ignore[misc]

    non_empty = [(name, items) for name, items in typed_items if items]
    if not non_empty:
        await _reply(
            update,
            format_fixtures_empty(
                target_date,
                last_updated=last_updated,
                feedback_url=feedback_url,
            ),
        )
        return

    show_series_labels = len(non_empty) > 1
    labels = public_labels or {}
    await _reply(
        update,
        format_fixtures_intro(
            target_date=target_date,
            last_updated=last_updated,
            feedback_url=feedback_url,
        ),
    )

    for model_name, items in non_empty:
        series_label = labels.get(model_name) if show_series_labels else None
        total = len(items)
        for start, group in _groups(items, size=15):
            end = start + len(group) - 1
            try:
                image = render_fixtures_png(
                    group,
                    target_date=str(target_date),
                    start_index=start,
                    series_label=series_label,
                    min_edge_percent=min_edge_percent,
                )
                await message.reply_photo(
                    photo=image,
                    caption=format_fixtures_photo_caption(
                        target_date,
                        start,
                        end,
                        total,
                        series_label=series_label,
                    ),
                )
            except Exception:
                logger.exception("Impossibile generare immagine partite Telegram.")
                await _reply(
                    update,
                    "Immagine non disponibile, invio il riepilogo testuale.\n\n"
                    f"{format_fixture_group_text(group, start_index=start, series_label=series_label)}",
                )


async def _public_labels_for_models(
    api: BackendApiClient,
    *,
    model_version: str,
    model_names: list[str],
) -> dict[str, str]:
    names = [name for name in model_names if name]
    if not names:
        return {}
    try:
        summary = await api.prediction_summary(model_version=model_version)
        accuracy_map = accuracy_by_model_name(summary)
    except BackendApiError:
        accuracy_map = {}
    return build_public_labels(names, accuracy_by_model=accuracy_map)


def _fallback_models(settings: TelegramSettings) -> list[str]:
    return [
        name.strip()
        for name in settings.telegram_model_names.split(",")
        if name.strip()
    ] or ["logistic_regression", "random_forest"]


def _model_names_from_versions(
    payload: dict[str, Any],
    *,
    model_version: str,
    fallback: list[str],
) -> list[str]:
    for entry in payload.get("versions") or []:
        if entry.get("version") != model_version:
            continue
        names = [
            str(model.get("model"))
            for model in (entry.get("models") or [])
            if model.get("model")
        ]
        return names or list(fallback)
    return list(fallback)


def _groups(items: list[dict], *, size: int) -> list[tuple[int, list[dict]]]:
    return [(index + 1, items[index : index + size]) for index in range(0, len(items), size)]


def _first_arg(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.args[0] if context.args else None


def _invite_origin_from_start(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Deep-link payload from ``/start <payload>`` (invite origin)."""
    if not context.args:
        return None
    payload = " ".join(context.args).strip()
    return payload or None


def _settings(context: ContextTypes.DEFAULT_TYPE) -> TelegramSettings:
    return context.application.bot_data["settings"]


def _api(context: ContextTypes.DEFAULT_TYPE) -> BackendApiClient:
    return context.application.bot_data["api_client"]


async def _post_init(application: Application) -> None:
    settings = application.bot_data["settings"]
    application.bot_data["api_client"] = BackendApiClient(
        settings.telegram_api_base_url,
        service_api_key=settings.telegram_service_api_key,
    )


async def _post_shutdown(application: Application) -> None:
    client = application.bot_data.get("api_client")
    if client:
        await client.close()


def build_application(settings: TelegramSettings | None = None) -> Application:
    settings = settings or get_telegram_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN non configurato in backend/.env.")

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("accetta_condizioni", accetta_condizioni))
    application.add_handler(CommandHandler("notifiche", notifiche))
    # ConversationHandler must be registered before the catch-all message handler.
    application.add_handler(build_feedback_conversation())
    application.add_handler(CommandHandler("schedine", schedine))
    application.add_handler(CommandHandler("partite", partite))
    application.add_handler(CommandHandler("statistiche", statistiche))
    # Inline menu buttons reuse the same guarded handlers as slash commands.
    application.add_handler(
        CallbackQueryHandler(_with_callback_answer(partite), pattern=rf"^{MENU_PARTITE}$")
    )
    application.add_handler(
        CallbackQueryHandler(_with_callback_answer(schedine), pattern=rf"^{MENU_SCHEDINE}$")
    )
    application.add_handler(
        CallbackQueryHandler(
            _with_callback_answer(statistiche), pattern=rf"^{MENU_STATISTICHE}$"
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            _with_callback_answer(help_command), pattern=rf"^{MENU_HELP}$"
        )
    )
    application.add_handler(CallbackQueryHandler(track_callback_query))
    application.add_handler(MessageHandler(filters.ALL, log_unhandled_update))
    # Comandi temporaneamente disabilitati. Lasciare il codice degli handler
    # pronto per riattivazione futura.
    # application.add_handler(CommandHandler("pronostici", pronostici))
    # application.add_handler(CommandHandler("giorno", giorno))
    # application.add_handler(CommandHandler("10giorni", ten_days))
    # application.add_handler(CommandHandler("cerca", cerca))
    return application


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    application = build_application()
    logger.info("Telegram bot avviato in polling.")
    application.run_polling()


if __name__ == "__main__":
    main()
