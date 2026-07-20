from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .client import BackendApiClient, BackendApiError
from .config import TelegramSettings, get_telegram_settings
from .dates import parse_date_or_offset, prediction_window, today_rome
from .images import render_betting_slip_png, render_bot_stats_png, render_fixtures_png
from .messages import (
    format_betting_slips,
    format_betting_slip_photo_caption,
    format_betting_slip_text,
    format_betting_slips_intro,
    format_bot_stats_intro,
    format_bot_stats_text,
    format_fixture_group_text,
    format_fixtures,
    format_fixtures_intro,
    format_fixtures_photo_caption,
    format_player_search,
    format_predictions_day,
    format_predictions_summary,
    split_message,
)
from .fixture_value import enrich_fixtures_with_value
from .public_labels import (
    accuracy_by_model_name,
    build_public_labels,
    build_stats_series,
)
from .slips_compare import select_distinct_fixture_models, select_distinct_model_payloads
from .tracking import track_callback_query, tracked


logger = logging.getLogger(__name__)


WELCOME_TEXT = """Ciao, sono il bot di tennis_oracle.

Comandi attivi:
/schedine - schedine di oggi
/partite - partite di oggi
/statistiche - andamento bot

Pronostici a scopo informativo/statistico, non garanzie di risultato."""


@tracked(action="/start", event_type="command")
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, WELCOME_TEXT)


@tracked(action="/help", event_type="command")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, WELCOME_TEXT)


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
        await _reply(update, str(exc))
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
        await _reply(update, exc.message)
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
        await _reply(update, exc.message)
        return

    await _reply(update, format_predictions_summary(items))


@tracked(action="/schedine", event_type="command")
async def schedine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_date = today_rome()
    settings = _settings(context)
    api = _api(context)
    fallback_models = [
        name.strip()
        for name in settings.telegram_model_names.split(",")
        if name.strip()
    ] or ["logistic_regression", "random_forest"]
    try:
        model_names = await api.model_names_for_version(
            model_version=settings.telegram_model_version,
            target_date=target_date,
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
        await _reply(update, exc.message)
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
    )


@tracked(action="/partite", event_type="command")
async def partite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_date = today_rome()
    settings = _settings(context)
    api = _api(context)
    fallback_models = [
        name.strip()
        for name in settings.telegram_model_names.split(",")
        if name.strip()
    ] or ["logistic_regression", "random_forest"]
    try:
        model_names = await api.model_names_for_version(
            model_version=settings.telegram_model_version,
            target_date=target_date,
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
        await _reply(update, exc.message)
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
    )


@tracked(action="/statistiche", event_type="command")
async def statistiche(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings = _settings(context)
    api = _api(context)
    fallback_models = [
        name.strip()
        for name in settings.telegram_model_names.split(",")
        if name.strip()
    ] or ["logistic_regression", "random_forest"]
    try:
        model_names = await api.model_names_for_version(
            model_version=settings.telegram_model_version,
            target_date=today_rome(),
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
        await _reply(update, exc.message)
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
        format_bot_stats_intro(from_date=from_date, to_date=to_date),
    )
    if not series:
        await _reply(update, "Nessuna statistica disponibile.")
        return
    try:
        image = render_bot_stats_png(
            series,
            from_date=str(from_date) if from_date else None,
            to_date=str(to_date) if to_date else None,
        )
        if update.message:
            await update.message.reply_photo(
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
        await _reply(update, exc.message)
        return

    await _reply(update, format_player_search(items, player))


async def _reply(update: Update, text: str) -> None:
    if not update.message:
        return
    for chunk in split_message(text):
        await update.message.reply_text(chunk)


async def _reply_betting_slips(
    update: Update,
    payloads: list[dict] | dict,
    *,
    min_edge_percent: float = 2.0,
    slip_date: str | None = None,
    public_labels: dict[str, str] | None = None,
) -> None:
    if not update.message:
        return

    if isinstance(payloads, dict):
        payloads = [payloads]

    non_empty = [payload for payload in payloads if payload.get("slips")]
    if not non_empty:
        empty_payload = payloads[0] if payloads else {"date": slip_date, "slips": []}
        await _reply(update, format_betting_slips(empty_payload, min_edge_percent=min_edge_percent))
        return

    resolved_date = slip_date or str(non_empty[0].get("date") or "oggi")
    show_series_labels = len(non_empty) > 1
    labels = public_labels or {}
    await _reply(
        update,
        format_betting_slips_intro(slip_date=resolved_date, min_edge_percent=min_edge_percent),
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
                await update.message.reply_photo(
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
) -> None:
    if not update.message:
        return

    if not model_items:
        await _reply(update, format_fixtures([], target_date))
        return

    # Backward-compatible: plain list of fixtures from a single model.
    if isinstance(model_items[0], dict):
        typed_items: list[tuple[str, list[dict]]] = [("", list(model_items))]  # type: ignore[arg-type]
    else:
        typed_items = [(str(name), list(items)) for name, items in model_items]  # type: ignore[misc]

    non_empty = [(name, items) for name, items in typed_items if items]
    if not non_empty:
        await _reply(update, format_fixtures([], target_date))
        return

    show_series_labels = len(non_empty) > 1
    labels = public_labels or {}
    await _reply(update, format_fixtures_intro(target_date=target_date))

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
                await update.message.reply_photo(
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


def _groups(items: list[dict], *, size: int) -> list[tuple[int, list[dict]]]:
    return [(index + 1, items[index : index + size]) for index in range(0, len(items), size)]


def _first_arg(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return context.args[0] if context.args else None


def _settings(context: ContextTypes.DEFAULT_TYPE) -> TelegramSettings:
    return context.application.bot_data["settings"]


def _api(context: ContextTypes.DEFAULT_TYPE) -> BackendApiClient:
    return context.application.bot_data["api_client"]


async def _post_init(application: Application) -> None:
    settings = application.bot_data["settings"]
    application.bot_data["api_client"] = BackendApiClient(settings.telegram_api_base_url)


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
    application.add_handler(CommandHandler("schedine", schedine))
    application.add_handler(CommandHandler("partite", partite))
    application.add_handler(CommandHandler("statistiche", statistiche))
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
