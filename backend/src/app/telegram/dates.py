from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


ROME_TZ = ZoneInfo("Europe/Rome")


def today_rome() -> date:
    return datetime.now(ROME_TZ).date()


def parse_date_or_offset(
    value: str | None,
    *,
    today: date | None = None,
    max_offset: int = 10,
) -> date:
    base_date = today or today_rome()
    if value is None or value.strip() == "":
        return base_date

    raw_value = value.strip()
    if raw_value.isdigit():
        offset = int(raw_value)
        if offset > max_offset:
            raise ValueError(f"Usa un offset tra 0 e {max_offset}.")
        return base_date + timedelta(days=offset)

    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValueError("Usa una data YYYY-MM-DD oppure un offset 0-10.") from exc


def prediction_window(*, today: date | None = None, days: int = 10) -> tuple[date, date]:
    start = today or today_rome()
    return start, start + timedelta(days=days)
