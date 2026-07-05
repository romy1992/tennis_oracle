from __future__ import annotations

import logging
from datetime import timedelta

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from .client import BackendApiClient, BackendApiError
from .config import TelegramSettings, get_telegram_settings
from .dates import parse_date_or_offset, prediction_window, today_rome
from .images import render_betting_slip_png, render_fixtures_png
from .messages import (
    format_betting_slips,
    format_betting_slip_photo_caption,
    format_betting_slip_text,
    format_betting_slips_intro,
    format_fixture_group_text,
    format_fixtures,
    format_fixtures_intro,
    format_fixtures_photo_caption,
    format_player_search,
    format_predictions_day,
    format_predictions_summary,
    split_message,
)


logger = logging.getLogger(__name__)


WELCOME_TEXT = """Ciao, sono il bot di tennis_oracle.

Comandi attivi:
/schedine - schedine di oggi
/partite - partite di oggi

Pronostici a scopo informativo/statistico, non garanzie di risultato."""


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, WELCOME_TEXT)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply(update, WELCOME_TEXT)


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


async def schedine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_date = today_rome()
    settings = _settings(context)
    try:
        payload = await _api(context).daily_betting_slips(
            slip_date=target_date,
            model_version=settings.telegram_model_version,
            model_name=settings.telegram_model_name,
            stake=settings.telegram_default_stake,
        )
    except BackendApiError as exc:
        await _reply(update, exc.message)
        return

    await _reply_betting_slips(update, payload)


async def partite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    target_date = today_rome()
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

    await _reply_fixtures(update, items, target_date)


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


async def _reply_betting_slips(update: Update, payload: dict) -> None:
    if not update.message:
        return

    slips = payload.get("slips") or []
    if not slips:
        await _reply(update, format_betting_slips(payload))
        return

    await _reply(update, format_betting_slips_intro(payload))
    slip_date = str(payload.get("date") or "")
    for slip in slips:
        try:
            image = render_betting_slip_png(slip, slip_date=slip_date)
            await update.message.reply_photo(
                photo=image,
                caption=format_betting_slip_photo_caption(slip),
            )
        except Exception:
            logger.exception("Impossibile generare immagine schedina Telegram.")
            await _reply(
                update,
                "Immagine non disponibile, invio il riepilogo testuale.\n\n"
                f"{format_betting_slip_text(slip)}",
            )


async def _reply_fixtures(update: Update, items: list[dict], target_date) -> None:
    if not update.message:
        return

    if not items:
        await _reply(update, format_fixtures(items, target_date))
        return

    await _reply(update, format_fixtures_intro(items, target_date))
    total = len(items)
    for start, group in _groups(items, size=20):
        end = start + len(group) - 1
        try:
            image = render_fixtures_png(group, target_date=str(target_date), start_index=start)
            await update.message.reply_photo(
                photo=image,
                caption=format_fixtures_photo_caption(target_date, start, end, total),
            )
        except Exception:
            logger.exception("Impossibile generare immagine partite Telegram.")
            await _reply(
                update,
                "Immagine non disponibile, invio il riepilogo testuale.\n\n"
                f"{format_fixture_group_text(group, start_index=start)}",
            )


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
