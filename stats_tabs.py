"""Content of the stats tabs shown in the menu, as plain data.

build_tabs() returns [(tab_name, rows)], where each row is one of:
    ("heading", text)
    ("row", label, value)     label left-aligned, value right-aligned
    ("note", text)            small grey text
    ("gap",)                  vertical space between sections
Kept free of AppKit so it can be unit-tested; stats_panel.py draws it.
"""

from datetime import date, timedelta

from pricing import estimate_cost, format_dollars
from token_math import format_count
from usage_stats import (
    category_totals,
    history,
    model_totals,
    models_all_time,
    models_in_range,
    top_projects,
)

CATEGORY_LABELS = [
    ("input", "Input"),
    ("output", "Output"),
    ("cache_write", "Cache write"),
    ("cache_read", "Cache read"),
]

MODEL_FAMILIES = ["fable", "mythos", "opus", "sonnet", "haiku"]


def _ordinal_suffix(day):
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def format_long_date(iso_date_str):
    """'2026-11-07' -> 'November 7th, 2026'."""
    parsed = date.fromisoformat(iso_date_str)
    return f"{parsed.strftime('%B')} {parsed.day}{_ordinal_suffix(parsed.day)}, {parsed.year}"


def model_display_name(model_id):
    """'claude-opus-5-5' -> 'Opus 5.5', 'claude-haiku-4-5-20251001' -> 'Haiku 4.5'."""
    parts = model_id.split("-")
    if len(parts) < 2 or parts[0] != "claude" or parts[1] not in MODEL_FAMILIES:
        return model_id
    version = [p for p in parts[2:] if p.isdigit() and len(p) <= 2]
    name = parts[1].capitalize()
    return f"{name} {'.'.join(version)}" if version else name


def merge_cache_writes(categories):
    merged = dict(categories)
    merged["cache_write"] = merged.pop("cache_write_5m", 0) + merged.pop(
        "cache_write_1h", 0
    )
    return merged


def percent(part, whole):
    if not whole or not part:
        return "0%"
    share = part / whole * 100
    return "<1%" if share < 1 else f"{share:.0f}%"


def _tokens_tab(today_models, lifetime_models, earlier):
    rows = []
    for heading, models, extra in (
        ("Today", today_models, 0),
        ("Lifetime", lifetime_models, earlier),
    ):
        if rows:
            rows.append(("gap",))
        rows.append(("heading", heading))
        categories = merge_cache_writes(category_totals(models))
        whole = sum(categories.values()) + extra
        for key, label in CATEGORY_LABELS:
            count = categories[key]
            rows.append(("row", label, f"{format_count(count)}  ({percent(count, whole)})"))
        if extra:
            rows.append(
                ("row", "Older, no detail", f"{format_count(extra)}  ({percent(extra, whole)})")
            )
    rows.append(("gap",))
    rows.append(("note", "Cache read = context re-sent each turn, billed cheaply"))
    return rows


def _models_tab(today_models, lifetime_models, earlier):
    rows = []
    for heading, models in (("Today", today_models), ("Lifetime", lifetime_models)):
        if rows:
            rows.append(("gap",))
        rows.append(("heading", heading))
        totals = model_totals(models)
        if not totals:
            rows.append(("note", "No usage yet"))
        for model, tokens in totals:
            rows.append(("row", model_display_name(model), format_count(tokens)))
    if earlier:
        rows.append(("gap",))
        rows.append(("note", f"Plus {format_count(earlier)} older tokens with no model detail"))
    return rows


def _projects_tab(daily, week_start, today):
    rows = [("heading", "Last 7 days")]
    projects = top_projects(daily, week_start, today)
    if not projects:
        rows.append(("note", "No usage in the last 7 days"))
    for project, tokens in projects:
        rows.append(("row", project, format_count(tokens)))
    return rows


def _history_tab(daily, today):
    stats = history(daily, today)
    rows = [
        ("row", "Yesterday", format_count(stats["yesterday"])),
        ("row", "Last 7 days", format_count(stats["last_7_days"])),
        ("row", "This month", format_count(stats["this_month"])),
    ]
    if stats["biggest_day"]:
        best_date, best_tokens = stats["biggest_day"]
        rows.append(("gap",))
        rows.append(("heading", "Biggest day"))
        rows.append(("row", format_long_date(best_date.isoformat()), format_count(best_tokens)))
    return rows


def _cost_tab(today_models, week_models, month_models, lifetime_models, earlier):
    rows = []
    unpriced_total = 0
    for label, models in (
        ("Today", today_models),
        ("Last 7 days", week_models),
        ("This month", month_models),
        ("All logged usage", lifetime_models),
    ):
        dollars, unpriced = estimate_cost(models)
        unpriced_total = max(unpriced_total, unpriced)
        rows.append(("row", label, format_dollars(dollars)))
    rows.append(("gap",))
    if unpriced_total:
        rows.append(("note", f"{format_count(unpriced_total)} tokens from unknown models not priced"))
    if earlier:
        rows.append(("note", f"{format_count(earlier)} older tokens not priced (no model detail)"))
    rows.append(("note", "Estimate at API list prices. Claude Pro is"))
    rows.append(("note", "flat-rate, so you aren't billed this."))
    return rows


def _sessions_tab(sessions):
    if not sessions:
        return [("note", "No active sessions")]
    return [("row", s["label"], format_count(s["tokens"])) for s in sessions]


def build_tabs(state, sessions, today=None):
    daily = state.get("daily", {})
    today = today or date.today()
    week_start = today - timedelta(days=6)
    today_models = models_in_range(daily, today, today)
    week_models = models_in_range(daily, week_start, today)
    month_models = models_in_range(daily, today.replace(day=1), today)
    lifetime_models = models_all_time(daily)
    lifetime_detailed = sum(t for _, t in model_totals(lifetime_models))
    earlier = max(state.get("grand_total", 0) - lifetime_detailed, 0)

    return [
        ("Tokens", _tokens_tab(today_models, lifetime_models, earlier)),
        ("Models", _models_tab(today_models, lifetime_models, earlier)),
        ("Projects", _projects_tab(daily, week_start, today)),
        ("History", _history_tab(daily, today)),
        ("Cost", _cost_tab(today_models, week_models, month_models, lifetime_models, earlier)),
        ("Sessions", _sessions_tab(sessions)),
    ]
