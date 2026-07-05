from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from .messages import (
    _format_date_time,
    _format_decimal,
    _format_percent,
    _match_title,
    predicted_winner_name,
    slip_pick_winner_name,
)


class BettingSlipImageError(RuntimeError):
    pass


def render_betting_slip_png(slip: dict[str, Any], *, slip_date: str | None = None) -> BytesIO:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise BettingSlipImageError("Pillow non installato.") from exc

    width = 1080
    margin = 48
    content_width = width - (margin * 2)
    background = "#f6f8fb"
    card = "#ffffff"
    text = "#16202a"
    muted = "#5d6b78"
    accent = "#1769aa"

    preview = Image.new("RGB", (width, 100), background)
    draw = ImageDraw.Draw(preview)
    fonts = {
        "title": _load_font(ImageFont, 44, bold=True),
        "section": _load_font(ImageFont, 32, bold=True),
        "body": _load_font(ImageFont, 30),
        "small": _load_font(ImageFont, 26),
    }

    rows: list[tuple[str, Any, str, int, int]] = []
    label = str(slip.get("label") or slip.get("slip_key") or "Schedina")
    rows.extend(_wrapped_rows(draw, label, fonts["title"], accent, content_width, 18, 0))
    if slip_date:
        rows.extend(_wrapped_rows(draw, f"Data: {slip_date}", fonts["small"], muted, content_width, 24, 0))

    metrics = [
        ("Quota combinata", _format_decimal(slip.get("combined_odds"))),
        ("Ritorno potenziale", _format_decimal(slip.get("potential_return"))),
        ("Profitto potenziale", _format_decimal(slip.get("potential_profit"))),
    ]
    for label, value in metrics:
        rows.extend(_wrapped_rows(draw, f"{label}: {value}", fonts["body"], text, content_width, 10, 0))

    rows.append(("Pick", fonts["section"], accent, 12, 0))
    for index, pick in enumerate(slip.get("picks") or [], start=1):
        match = _match_title(pick)
        winner = slip_pick_winner_name(pick) or "n.d."
        details = (
            f"Vincitore: {winner} | Quota {_format_decimal(pick.get('odds'))} | "
            f"Conf. {_format_percent(pick.get('confidence'))}"
        )
        rows.extend(_wrapped_rows(draw, f"{index}. {match}", fonts["body"], text, content_width, 8, 0))
        rows.extend(_wrapped_rows(draw, details, fonts["small"], muted, content_width - 24, 18, 24))

    height = margin * 2 + 40
    for value, font, _fill, spacing, _indent in rows:
        bbox = draw.textbbox((0, 0), value, font=font)
        height += bbox[3] - bbox[1] + spacing

    image = Image.new("RGB", (width, max(height, 640)), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, width - 24, image.height - 24),
        radius=28,
        fill=card,
        outline="#d9e2ec",
        width=2,
    )

    y = margin
    for value, font, fill, spacing, indent in rows:
        draw.text((margin + indent, y), value, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), value, font=font)
        y += bbox[3] - bbox[1] + spacing

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    output.name = f"{_safe_filename(str(slip.get('slip_key') or slip.get('label') or 'schedina'))}.png"
    return output


def render_fixtures_png(
    items: list[dict[str, Any]],
    *,
    target_date: str,
    start_index: int = 1,
) -> BytesIO:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise BettingSlipImageError("Pillow non installato.") from exc

    width = 1080
    margin = 48
    content_width = width - (margin * 2)
    background = "#f6f8fb"
    card = "#ffffff"
    text = "#16202a"
    muted = "#5d6b78"
    accent = "#1769aa"

    preview = Image.new("RGB", (width, 100), background)
    draw = ImageDraw.Draw(preview)
    fonts = {
        "title": _load_font(ImageFont, 44, bold=True),
        "body": _load_font(ImageFont, 30),
        "small": _load_font(ImageFont, 25),
    }

    end_index = start_index + len(items) - 1
    rows: list[tuple[str, Any, str, int, int]] = []
    rows.extend(_wrapped_rows(draw, f"Partite di oggi - {target_date}", fonts["title"], accent, content_width, 12, 0))
    rows.extend(_wrapped_rows(draw, f"{start_index}-{end_index}", fonts["small"], muted, content_width, 24, 0))

    for index, item in enumerate(items, start=start_index):
        tournament_parts = [item.get("tournament_name"), item.get("tournament_round"), item.get("surface")]
        tournament = " / ".join(str(part) for part in tournament_parts if part) or "Torneo n.d."
        prediction = item.get("prediction") or {}
        if prediction:
            winner = predicted_winner_name(item) or "n.d."
            prediction_text = (
                f"Vincitore: {winner} | Quota {_format_decimal(prediction.get('predicted_winner_odds'))} | "
                f"Vittoria {_format_percent(prediction.get('confidence'))}"
            )
        else:
            warning = item.get("prediction_warning") or "pronostico non disponibile"
            prediction_text = f"Pronostico: n.d. ({warning})"
        rows.extend(_wrapped_rows(draw, f"{index}. {_format_date_time(item)}", fonts["small"], muted, content_width, 4, 0))
        rows.extend(_wrapped_rows(draw, _match_title(item), fonts["body"], text, content_width, 4, 0))
        rows.extend(_wrapped_rows(draw, tournament, fonts["small"], muted, content_width, 4, 24))
        rows.extend(_wrapped_rows(draw, prediction_text, fonts["small"], accent, content_width, 18, 24))

    height = margin * 2 + 40
    for value, font, _fill, spacing, _indent in rows:
        bbox = draw.textbbox((0, 0), value, font=font)
        height += bbox[3] - bbox[1] + spacing

    image = Image.new("RGB", (width, max(height, 640)), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (24, 24, width - 24, image.height - 24),
        radius=28,
        fill=card,
        outline="#d9e2ec",
        width=2,
    )

    y = margin
    for value, font, fill, spacing, indent in rows:
        draw.text((margin + indent, y), value, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), value, font=font)
        y += bbox[3] - bbox[1] + spacing

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    output.name = f"partite_{target_date}_{start_index}_{end_index}.png"
    return output


def _wrapped_rows(
    draw: Any,
    value: str,
    font: Any,
    fill: str,
    max_width: int,
    spacing: int,
    indent: int,
) -> list[tuple[str, Any, str, int, int]]:
    words = value.split()
    if not words:
        return [(value, font, fill, spacing, indent)]

    rows: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            rows.append(current)
            current = word
    rows.append(current)
    return [(row, font, fill, spacing if index == len(rows) - 1 else 4, indent) for index, row in enumerate(rows)]


def _load_font(image_font: Any, size: int, *, bold: bool = False) -> Any:
    names = ["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]
    for name in names:
        try:
            return image_font.truetype(name, size)
        except OSError:
            continue
    for path in _font_candidates(bold):
        try:
            return image_font.truetype(str(path), size)
        except OSError:
            continue
    return image_font.load_default()


def _font_candidates(bold: bool) -> list[Path]:
    suffix = "Bold" if bold else ""
    return [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path(f"/usr/share/fonts/truetype/dejavu/DejaVuSans{('-' + suffix) if suffix else ''}.ttf"),
        Path(f"/Library/Fonts/Arial{' Bold' if bold else ''}.ttf"),
    ]


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_")
    return safe or "schedina"
