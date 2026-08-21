from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from .messages import (
    MARKETS_LEGEND,
    _format_decimal,
    _format_event_time,
    _format_percent,
    _match_title,
    market_label,
    market_text_color,
    predicted_winner_name,
    slip_kind_of,
    slip_pick_winner_name,
    slip_status_label,
    surface_label,
)


class BettingSlipImageError(RuntimeError):
    pass


_STATUS_COLORS = {
    "won": "#1f9d55",
    "lost": "#e02424",
    "pending": "#94a3b3",
    "void": "#64748b",
}

# Colonne leggibili su Telegram: predizione + % + quota, con mercato esplicito
# (Match / 1° set / O/U). Void/Edge/ROI/Valore restano fuori dall'immagine.
_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("", 36),
    ("Ora", 70),
    ("Torneo", 200),
    ("Match", 280),
    ("Mercato", 100),
    ("Predizione", 190),
    ("Percentuale\ndi riuscita", 120),
    ("Quota", 90),
    ("Live / esito", 180),
]

_LADDER_TABLE_COLUMNS: list[tuple[str, int]] = [
    ("", 36),
    ("Step", 50),
    ("Ora", 70),
    ("Torneo", 180),
    ("Match", 250),
    ("Mercato", 100),
    ("Predizione", 170),
    ("Puntata", 110),
    ("Quota", 90),
    ("Live / esito", 180),
]


def render_betting_slip_png(
    slip: dict[str, Any],
    *,
    slip_date: str | None = None,
    stake: float | None = None,
    min_edge_percent: float = 2.0,
    series_label: str | None = None,
    snapshot_label: str | None = None,
) -> BytesIO:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise BettingSlipImageError("Pillow non installato.") from exc

    del min_edge_percent  # kept for call-site compatibility; not shown on image
    width = 1460
    margin = 36
    row_height = 50
    header_height = 48
    background = "#f6f8fb"
    card = "#ffffff"
    text = "#16202a"
    muted = "#5d6b78"
    accent = "#1769aa"
    grid = "#d9e2ec"
    header_bg = "#eef3f8"

    fonts = {
        "title": _load_font(ImageFont, 36, bold=True),
        "section": _load_font(ImageFont, 24, bold=True),
        "body": _load_font(ImageFont, 22),
        "small": _load_font(ImageFont, 18),
        "tiny": _load_font(ImageFont, 16),
    }

    label = str(slip.get("label") or slip.get("slip_key") or "Schedina")
    description = str(slip.get("description") or "").strip()
    status = slip_status_label(slip.get("slip_status"))
    status_key = str(slip.get("slip_status") or "pending")
    picks = list(slip.get("picks") or [])
    picks_won = slip.get("picks_won")
    picks_total = slip.get("picks_total") or len(picks)
    is_ladder = slip_kind_of(slip) == "ladder"

    if is_ladder:
        metrics = [
            ("Moltiplicatore", _format_decimal(slip.get("combined_odds"))),
            ("Puntata iniz.", _format_decimal(stake if stake is not None else None)),
            ("Ritorno se presa", _format_decimal(slip.get("potential_return"))),
            ("Profitto", _format_decimal(slip.get("potential_profit"))),
        ]
        badge_text = f"{status} · {picks_won}/{picks_total} step"
    else:
        metrics = [
            ("Quota combinata", _format_decimal(slip.get("combined_odds"))),
            ("Puntata", _format_decimal(stake if stake is not None else None)),
            ("Vincita pot.", _format_decimal(slip.get("potential_return"))),
            ("Profitto", _format_decimal(slip.get("potential_profit"))),
        ]
        badge_text = f"{status} · {picks_won}/{picks_total} pick"

    table_columns = _LADDER_TABLE_COLUMNS if is_ladder else _TABLE_COLUMNS
    table_width = sum(col_width for _, col_width in table_columns)
    content_width = width - (margin * 2)
    table_left = margin + max(0, (content_width - table_width) // 2)

    title_block = 86 + (28 if description else 0) + (22 if slip_date or series_label else 0)
    metrics_block = 58
    table_block = header_height + max(len(picks), 1) * row_height + 16
    legend_block = 70
    height = margin * 2 + title_block + metrics_block + table_block + legend_block + 24

    image = Image.new("RGB", (width, max(height, 720)), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (16, 16, width - 16, image.height - 16),
        radius=24,
        fill=card,
        outline=grid,
        width=2,
    )

    y = margin
    draw.text((margin, y), label, font=fonts["title"], fill=accent)
    badge_bbox = draw.textbbox((0, 0), badge_text, font=fonts["small"])
    badge_w = badge_bbox[2] - badge_bbox[0] + 24
    badge_h = badge_bbox[3] - badge_bbox[1] + 12
    badge_x = width - margin - badge_w
    badge_fill = _STATUS_COLORS.get(status_key, _STATUS_COLORS["pending"])
    draw.rounded_rectangle(
        (badge_x, y + 4, badge_x + badge_w, y + 4 + badge_h),
        radius=12,
        fill=badge_fill,
    )
    draw.text((badge_x + 12, y + 8), badge_text, font=fonts["small"], fill="#ffffff")
    y += 44

    if description:
        draw.text((margin, y), _truncate(description, 110), font=fonts["small"], fill=muted)
        y += 28
    meta_parts = []
    if slip_date:
        meta_parts.append(f"Data: {slip_date}")
    if series_label:
        meta_parts.append(series_label)
    if snapshot_label:
        meta_parts.append(snapshot_label)
    if is_ladder:
        meta_parts.append("Scalata · reinvestimento progressivo")
    meta_parts.append(MARKETS_LEGEND)
    if meta_parts:
        draw.text((margin, y), " · ".join(meta_parts), font=fonts["tiny"], fill=muted)
        y += 24
    y += 10

    metric_box_w = (content_width - 24) // 4
    for index, (metric_label, metric_value) in enumerate(metrics):
        x = margin + index * (metric_box_w + 8)
        draw.rounded_rectangle(
            (x, y, x + metric_box_w, y + 48),
            radius=10,
            fill=header_bg,
            outline=grid,
        )
        draw.text((x + 12, y + 6), metric_label, font=fonts["tiny"], fill=muted)
        draw.text((x + 12, y + 22), metric_value, font=fonts["section"], fill=text)
    y += 64

    # Table header
    x = table_left
    draw.rectangle((table_left, y, table_left + table_width, y + header_height), fill=header_bg)
    for col_label, col_width in table_columns:
        if col_label:
            _draw_column_header(
                draw, x, y, col_label, fonts["tiny"], muted, header_height
            )
        draw.line((x, y, x, y + header_height), fill=grid, width=1)
        x += col_width
    draw.line((table_left + table_width, y, table_left + table_width, y + header_height), fill=grid, width=1)
    draw.line((table_left, y, table_left + table_width, y), fill=grid, width=1)
    y += header_height

    if not picks:
        draw.rectangle((table_left, y, table_left + table_width, y + row_height), outline=grid)
        empty_msg = "Nessun step disponibile." if is_ladder else "Nessun pick disponibile."
        draw.text((table_left + 12, y + 12), empty_msg, font=fonts["body"], fill=muted)
        y += row_height
    else:
        for pick in picks:
            draw.rectangle((table_left, y, table_left + table_width, y + row_height), outline=grid)
            cells = _ladder_pick_cells(pick) if is_ladder else _pick_cells(pick)
            x = table_left
            for (cell_text, cell_fill), (_, col_width) in zip(cells, table_columns):
                if cell_text == "__DOT__":
                    color = _STATUS_COLORS.get(str(pick.get("pick_status") or "pending"), _STATUS_COLORS["pending"])
                    cx = x + col_width // 2
                    cy = y + row_height // 2
                    draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=color)
                else:
                    draw.text((x + 6, y + 12), cell_text, font=fonts["tiny"], fill=cell_fill)
                draw.line((x, y, x, y + row_height), fill=grid, width=1)
                x += col_width
            draw.line(
                (table_left + table_width, y, table_left + table_width, y + row_height),
                fill=grid,
                width=1,
            )
            y += row_height

    y += 18
    draw.text((margin, y), "Legenda esiti", font=fonts["small"], fill=accent)
    y += 26
    legend_items = [
        (_STATUS_COLORS["won"], "Presa"),
        (_STATUS_COLORS["lost"], "Persa"),
        (_STATUS_COLORS["pending"], "In corso"),
        (_STATUS_COLORS["void"], "Annullata"),
    ]
    lx = margin
    for color, name in legend_items:
        draw.ellipse((lx, y + 2, lx + 14, y + 16), fill=color)
        draw.text((lx + 20, y), name, font=fonts["small"], fill=text)
        lx += 120
    y += 28
    draw.text((margin, y), MARKETS_LEGEND, font=fonts["tiny"], fill=muted)

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
    series_label: str | None = None,
    min_edge_percent: float = 2.0,
    snapshot_label: str | None = None,
) -> BytesIO:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise BettingSlipImageError("Pillow non installato.") from exc

    del min_edge_percent  # kept for call-site compatibility; not shown on image
    columns: list[tuple[str, int]] = [
        ("", 36),
        ("Ora", 70),
        ("Torneo", 170),
        ("Superficie", 100),
        ("Match", 260),
        ("Mercato", 100),
        ("Predizione", 170),
        ("Percentuale\ndi riuscita", 120),
        ("Quota", 80),
        ("Live / esito", 180),
    ]
    width = 1440
    margin = 36
    row_height = 44
    header_height = 48
    background = "#f6f8fb"
    card = "#ffffff"
    text = "#16202a"
    muted = "#5d6b78"
    accent = "#1769aa"
    grid = "#d9e2ec"
    header_bg = "#eef3f8"

    fonts = {
        "title": _load_font(ImageFont, 34, bold=True),
        "section": _load_font(ImageFont, 22, bold=True),
        "small": _load_font(ImageFont, 18),
        "tiny": _load_font(ImageFont, 16),
    }

    table_width = sum(col_width for _, col_width in columns)
    content_width = width - (margin * 2)
    table_left = margin + max(0, (content_width - table_width) // 2)
    end_index = start_index + len(items) - 1

    title_block = 70 + (22 if series_label else 0)
    table_block = header_height + max(len(items), 1) * row_height + 16
    legend_block = 70
    height = margin * 2 + title_block + table_block + legend_block + 24

    image = Image.new("RGB", (width, max(height, 640)), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (16, 16, width - 16, image.height - 16),
        radius=24,
        fill=card,
        outline=grid,
        width=2,
    )

    y = margin
    draw.text((margin, y), f"Partite di oggi - {target_date}", font=fonts["title"], fill=accent)
    y += 40
    meta = f"{start_index}-{end_index}"
    if series_label:
        meta = f"{meta} · {series_label}"
    if snapshot_label:
        meta = f"{meta} · {snapshot_label}"
    meta = f"{meta} · {MARKETS_LEGEND}"
    draw.text((margin, y), meta, font=fonts["tiny"], fill=muted)
    y += 28

    x = table_left
    draw.rectangle((table_left, y, table_left + table_width, y + header_height), fill=header_bg)
    for col_label, col_width in columns:
        if col_label:
            _draw_column_header(
                draw, x, y, col_label, fonts["tiny"], muted, header_height
            )
        draw.line((x, y, x, y + header_height), fill=grid, width=1)
        x += col_width
    draw.line((table_left + table_width, y, table_left + table_width, y + header_height), fill=grid, width=1)
    draw.line((table_left, y, table_left + table_width, y), fill=grid, width=1)
    y += header_height

    if not items:
        draw.rectangle((table_left, y, table_left + table_width, y + row_height), outline=grid)
        draw.text((table_left + 12, y + 12), "Nessuna partita.", font=fonts["small"], fill=muted)
        y += row_height
    else:
        for item in items:
            draw.rectangle((table_left, y, table_left + table_width, y + row_height), outline=grid)
            cells = _fixture_cells(item)
            x = table_left
            for (cell_text, cell_fill), (_, col_width) in zip(cells, columns):
                if cell_text == "__DOT__":
                    color = _STATUS_COLORS.get(str(item.get("pick_status") or "pending"), _STATUS_COLORS["pending"])
                    cx = x + col_width // 2
                    cy = y + row_height // 2
                    draw.ellipse((cx - 7, cy - 7, cx + 7, cy + 7), fill=color)
                else:
                    draw.text((x + 6, y + 12), cell_text, font=fonts["tiny"], fill=cell_fill)
                draw.line((x, y, x, y + row_height), fill=grid, width=1)
                x += col_width
            draw.line(
                (table_left + table_width, y, table_left + table_width, y + row_height),
                fill=grid,
                width=1,
            )
            y += row_height

    y += 18
    draw.text((margin, y), "Legenda esiti", font=fonts["small"], fill=accent)
    y += 26
    legend_items = [
        (_STATUS_COLORS["won"], "Presa"),
        (_STATUS_COLORS["lost"], "Persa"),
        (_STATUS_COLORS["pending"], "In corso"),
        (_STATUS_COLORS["void"], "Annullata"),
    ]
    lx = margin
    for color, name in legend_items:
        draw.ellipse((lx, y + 2, lx + 14, y + 16), fill=color)
        draw.text((lx + 20, y), name, font=fonts["small"], fill=text)
        lx += 120
    y += 28
    draw.text((margin, y), MARKETS_LEGEND, font=fonts["tiny"], fill=muted)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    output.name = f"partite_{target_date}_{start_index}_{end_index}.png"
    return output


def render_bot_stats_png(
    series: list[dict[str, Any]],
    *,
    from_date: str | None = None,
    to_date: str | None = None,
) -> BytesIO:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise BettingSlipImageError("Pillow non installato.") from exc

    width = 1400
    margin = 36
    background = "#f6f8fb"
    card = "#ffffff"
    text = "#16202a"
    muted = "#5d6b78"
    accent = "#1769aa"
    grid = "#d9e2ec"
    header_bg = "#eef3f8"

    fonts = {
        "title": _load_font(ImageFont, 34, bold=True),
        "section": _load_font(ImageFont, 22, bold=True),
        "body": _load_font(ImageFont, 20),
        "small": _load_font(ImageFont, 17),
        "tiny": _load_font(ImageFont, 15),
    }

    columns = max(len(series), 1)
    gap = 16
    usable = width - (margin * 2) - (gap * (columns - 1))
    card_w = usable // columns
    card_h = 420
    header_h = 90
    height = margin * 2 + header_h + card_h + 40

    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (16, 16, width - 16, image.height - 16),
        radius=24,
        fill=card,
        outline=grid,
        width=2,
    )

    y = margin
    draw.text((margin, y), "Statistiche bot", font=fonts["title"], fill=accent)
    y += 40
    range_text = (
        f"{from_date} → {to_date}" if from_date and to_date else "Storico completo"
    )
    draw.text((margin, y), range_text, font=fonts["tiny"], fill=muted)
    y += 36

    for index, entry in enumerate(series):
        x = margin + index * (card_w + gap)
        prediction = entry.get("prediction") or {}
        slip = entry.get("slip") or {}
        label = str(entry.get("label") or f"Serie {index + 1}")

        draw.rounded_rectangle(
            (x, y, x + card_w, y + card_h),
            radius=16,
            fill=header_bg,
            outline=grid,
        )
        cy = y + 16
        draw.text((x + 14, cy), _truncate(label, 34), font=fonts["section"], fill=accent)
        cy += 36

        draw.text((x + 14, cy), "Partite singole", font=fonts["small"], fill=muted)
        cy += 26
        draw.text(
            (x + 14, cy),
            f"Accuratezza {_fmt_pct(prediction.get('accuracy_pct'))}",
            font=fonts["body"],
            fill=text,
        )
        cy += 28
        draw.text(
            (x + 14, cy),
            (
                f"Risolte {prediction.get('predictions_resolved', 0)} · "
                f"Corrette {prediction.get('predictions_correct', 0)} · "
                f"Perse {prediction.get('predictions_lost', 0)}"
            ),
            font=fonts["tiny"],
            fill=muted,
        )
        cy += 22
        draw.text(
            (x + 14, cy),
            f"In corso {prediction.get('pending', 0)}",
            font=fonts["tiny"],
            fill=muted,
        )
        cy += 22
        draw.text(
            (x + 14, cy),
            (
                f"Profitto {_fmt_signed(prediction.get('theoretical_profit_units'))} · "
                f"ROI {_fmt_pct(prediction.get('theoretical_roi_pct'))}"
            ),
            font=fonts["tiny"],
            fill=text,
        )
        cy += 34

        draw.text((x + 14, cy), "Schedine", font=fonts["small"], fill=muted)
        cy += 26
        draw.text(
            (x + 14, cy),
            f"Win rate {_fmt_pct(slip.get('slip_win_rate_pct'))}",
            font=fonts["body"],
            fill=text,
        )
        cy += 28
        draw.text(
            (x + 14, cy),
            (
                f"Prese {slip.get('slips_won', 0)} · "
                f"Perse {slip.get('slips_lost', 0)} · "
                f"In corso {slip.get('slips_pending', 0)}"
            ),
            font=fonts["tiny"],
            fill=muted,
        )
        cy += 22
        draw.text(
            (x + 14, cy),
            f"Hit pick {_fmt_pct(slip.get('pick_hit_rate_pct'))}",
            font=fonts["tiny"],
            fill=muted,
        )
        cy += 26
        draw.text(
            (x + 14, cy),
            (
                f"Profitto {_fmt_signed(slip.get('theoretical_profit_units'))} · "
                f"ROI {_fmt_pct(slip.get('theoretical_roi_pct'))}"
            ),
            font=fonts["section"],
            fill=text,
        )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    output.name = "statistiche_bot.png"
    return output


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "n.d."
    return f"{float(value):.1f}%"


def _fmt_signed(value: Any) -> str:
    if value is None:
        return "n.d."
    return f"{float(value):+.2f}"


def _fixture_status_label(item: dict[str, Any]) -> str:
    lifecycle_label = item.get("match_lifecycle_label")
    status = item.get("pick_status")
    if status == "won":
        return "Presa"
    if status == "lost":
        return "Persa"
    if status == "void":
        return str(lifecycle_label or "Annullata")
    if lifecycle_label and item.get("match_lifecycle_status") not in {
        None,
        "upcoming",
        "completed",
        "scheduled",
        "finished",
    }:
        return str(lifecycle_label)
    event_status = str(item.get("event_status") or "").lower()
    if item.get("is_completed") or event_status in {"finished", "completed"}:
        return str(lifecycle_label or "Esito mancante")
    prediction = item.get("prediction")
    if not prediction:
        return "Da generare"
    return str(lifecycle_label or "Da giocare")


def _score_snapshot_label(item: dict[str, Any]) -> tuple[str, str]:
    """Compact live/final snapshot suitable for a single image table cell."""
    muted = "#5d6b78"
    live_color = "#b91c1c"
    won_color = _STATUS_COLORS["won"]
    lost_color = _STATUS_COLORS["lost"]
    score = item.get("live_score") if isinstance(item.get("live_score"), dict) else {}
    sets = " ".join(
        f"{entry.get('score_first', '-')}-{entry.get('score_second', '-')}"
        for entry in (score.get("sets") or [])
        if isinstance(entry, dict)
    )
    game = str(score.get("current_game") or "").strip()
    final_result = str(score.get("final_result") or "").strip()
    if final_result in {"-", "0 - 0", "0-0"}:
        final_result = ""

    lifecycle = str(item.get("match_lifecycle_status") or "").lower()
    event_live = str(item.get("event_live") or "").lower()
    is_live = lifecycle in {"started", "live"} or event_live in {
        "1",
        "true",
        "yes",
        "live",
        "inprogress",
    }
    if is_live:
        details = " · ".join(part for part in (sets, f"G {game}" if game else "") if part)
        return (_truncate(f"LIVE · {details}" if details else "LIVE", 28), live_color)

    pick_status = str(item.get("pick_status") or "pending")
    prediction = item.get("prediction") if isinstance(item.get("prediction"), dict) else {}
    prediction_correct = prediction.get("is_correct")
    is_completed = bool(item.get("is_completed")) or lifecycle in {"completed", "finished"}
    if pick_status in {"won", "lost", "void"} or is_completed:
        if pick_status == "won":
            base, color = "PRESA", won_color
        elif pick_status == "lost":
            base, color = "PERSA", lost_color
        elif pick_status == "void":
            base, color = "ANNULLATA", _STATUS_COLORS["void"]
        elif prediction_correct is True:
            base, color = "PRESA", won_color
        elif prediction_correct is False:
            base, color = "PERSA", lost_color
        else:
            base, color = "FINALE", won_color
        details = " · ".join(part for part in (final_result, sets) if part)
        return (_truncate(f"{base} · {details}" if details else base, 28), color)

    return (_truncate(_fixture_status_label(item), 28), muted)


def _draw_column_header(
    draw: Any,
    x: int,
    y: int,
    label: str,
    font: Any,
    fill: str,
    header_height: int,
) -> None:
    lines = [line for line in str(label).split("\n") if line]
    if not lines:
        return
    line_h = 14
    total = line_h * len(lines)
    start = y + max(2, (header_height - total) // 2)
    for index, line in enumerate(lines):
        draw.text((x + 4, start + index * line_h), line, font=font, fill=fill)


def _fixture_cells(item: dict[str, Any]) -> list[tuple[str, str]]:
    text = "#16202a"
    muted = "#5d6b78"
    prediction = item.get("prediction") or {}
    winner = predicted_winner_name(item) if prediction else "-"
    odds = item.get("market_odds")
    if odds is None:
        odds = prediction.get("predicted_winner_odds")
    market_key = item.get("market") or prediction.get("market")
    market = market_label(market_key)
    pred_color = market_text_color(market_key) if prediction else muted
    snapshot_text, snapshot_color = _score_snapshot_label(item)
    return [
        ("__DOT__", text),
        (_format_event_time(item.get("event_time")), muted),
        (_truncate(str(item.get("tournament_name") or "-"), 20), text),
        (_truncate(surface_label(item.get("surface")), 10), muted),
        (_truncate(_match_title(item), 28), text),
        (_truncate(market, 12), pred_color),
        (_truncate(str(winner or "-"), 18), pred_color),
        (_format_percent(prediction.get("confidence")) if prediction else "-", muted),
        (_format_decimal(odds), text),
        (snapshot_text, snapshot_color),
    ]


def _pick_cells(pick: dict[str, Any]) -> list[tuple[str, str]]:
    text = "#16202a"
    muted = "#5d6b78"
    winner = slip_pick_winner_name(pick) or "-"
    market_key = pick.get("market")
    pred_color = market_text_color(market_key)
    snapshot_text, snapshot_color = _score_snapshot_label(pick)
    return [
        ("__DOT__", text),
        (_format_event_time(pick.get("event_time")), muted),
        (_truncate(str(pick.get("tournament_name") or "-"), 22), text),
        (_truncate(_match_title(pick), 30), text),
        (_truncate(market_label(market_key), 12), pred_color),
        (_truncate(winner, 18), pred_color),
        (_format_percent(pick.get("confidence")), muted),
        (_format_decimal(pick.get("odds")), text),
        (snapshot_text, snapshot_color),
    ]


def _ladder_pick_cells(pick: dict[str, Any]) -> list[tuple[str, str]]:
    text = "#16202a"
    muted = "#5d6b78"
    winner = slip_pick_winner_name(pick) or "-"
    market_key = pick.get("market")
    pred_color = market_text_color(market_key)
    step = pick.get("ladder_step_index")
    snapshot_text, snapshot_color = _score_snapshot_label(pick)
    return [
        ("__DOT__", text),
        (str(step) if step is not None else "-", muted),
        (_format_event_time(pick.get("event_time")), muted),
        (_truncate(str(pick.get("tournament_name") or "-"), 20), text),
        (_truncate(_match_title(pick), 26), text),
        (_truncate(market_label(market_key), 12), pred_color),
        (_truncate(winner, 16), pred_color),
        (_format_decimal(pick.get("ladder_step_stake")), muted),
        (_format_decimal(pick.get("odds")), text),
        (snapshot_text, snapshot_color),
    ]


def _truncate(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 1].rstrip() + "…"


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
