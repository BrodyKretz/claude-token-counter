"""What the panel shows, as plain data. panel_view.py draws it.

build_panel() returns a list of tabs. Each tab is a dict:
    {"key": str, "title": str, "short": tab-bar caption, "icon": SF Symbol name,
     "cards": [card, ...]}
and each card is {"title": str or None, "items": [item, ...]} where an item is
one of:
    ("tiles", [(label, value, icon), ...])     big numbers side by side
    ("chart", [tokens, ...], caption)           line chart, oldest first
    ("bar", label, value, fraction)             label/value over a 0-1 bar
    ("row", label, value)
    ("note", text)                              small grey line
    ("buttons", [(title, icon, action), ...])
    ("segmented", label, [option, ...], selected_index, action)
    ("popup", label, [option, ...], selected_index, action)
    ("switch", label, is_on, action)
Actions are strings the app handles in TokenCounterApp.handle_action.

Kept free of AppKit so it can be unit-tested.
"""

from datetime import date, timedelta

from pricing import estimate_cost, format_dollars
from token_math import format_count
from version import FORK_AUTHOR, ORIGINAL_AUTHOR, __version__
from usage_stats import (
    category_totals,
    daily_series,
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

TITLE_MODES = [("lifetime", "Lifetime"), ("today", "Today"), ("icon", "Icon only")]
LEADERBOARD_VIEWS = [("total", "Total"), ("day", "Yesterday")]
CHART_DAYS = 14
MENU_BAR_FONT_SIZES = [10, 11, 12, 13, 14]
DEFAULT_MENU_BAR_FONT_SIZE = 12


def _ordinal_suffix(day):
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def format_long_date(iso_date_str):
    """'2026-11-07' -> 'November 7th, 2026'."""
    parsed = date.fromisoformat(iso_date_str)
    return f"{parsed.strftime('%B')} {parsed.day}{_ordinal_suffix(parsed.day)}, {parsed.year}"


def format_short_date(day):
    """date(2026, 11, 7) -> 'Nov 7th'."""
    return f"{day.strftime('%b')} {day.day}{_ordinal_suffix(day.day)}"


def format_interval(seconds):
    if seconds < 60:
        return f"{seconds} second" + ("" if seconds == 1 else "s")
    minutes = seconds // 60
    return f"{minutes} minute" + ("" if minutes == 1 else "s")


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


def _fraction(part, whole):
    return part / whole if whole else 0.0


def _share_bar(label, count, whole):
    return ("bar", label, f"{format_count(count)} · {percent(count, whole)}", _fraction(count, whole))


class _Data:
    """Everything the tabs need, computed once per render."""

    def __init__(self, state, today):
        self.state = state
        self.daily = state.get("daily", {})
        self.today = today
        self.week_start = today - timedelta(days=6)
        self.today_models = models_in_range(self.daily, today, today)
        self.week_models = models_in_range(self.daily, self.week_start, today)
        self.month_models = models_in_range(self.daily, today.replace(day=1), today)
        self.lifetime_models = models_all_time(self.daily)
        detailed = sum(t for _, t in model_totals(self.lifetime_models))
        self.grand_total = state.get("grand_total", 0)
        self.earlier = max(self.grand_total - detailed, 0)
        self.today_total = sum(t for _, t in model_totals(self.today_models))


def _overview_tab(d):
    stats = history(d.daily, d.today)
    series = daily_series(d.daily, d.today, CHART_DAYS)
    peak = max((t for _, t in series), default=0)
    history_items = [
        ("row", "Yesterday", format_count(stats["yesterday"])),
        ("row", "Last 7 days", format_count(stats["last_7_days"])),
        ("row", "This month", format_count(stats["this_month"])),
    ]
    if stats["biggest_day"]:
        best_date, best_tokens = stats["biggest_day"]
        history_items.append(
            ("row", f"Biggest day · {format_short_date(best_date)}", format_count(best_tokens))
        )
    return {
        "key": "overview",
        "title": "Overview",
        "short": "Home",
        "icon": "square.grid.2x2",
        "cards": [
            {
                "title": None,
                "items": [
                    (
                        "tiles",
                        [
                            ("Today", format_count(d.today_total), "sun.max"),
                            ("Lifetime", format_count(d.grand_total), "infinity"),
                        ],
                    )
                ],
            },
            {
                "title": f"Last {CHART_DAYS} days",
                "items": [("chart", [t for _, t in series], f"Peak {format_count(peak)}")],
            },
            {"title": "History", "items": history_items},
        ],
    }


def _breakdown_card(title, models, extra):
    categories = merge_cache_writes(category_totals(models))
    whole = sum(categories.values()) + extra
    items = [_share_bar(label, categories[key], whole) for key, label in CATEGORY_LABELS]
    if extra:
        items.append(_share_bar("Older, no detail", extra, whole))
    return {"title": title, "items": items}


def _breakdown_tab(d):
    lifetime = _breakdown_card("Lifetime", d.lifetime_models, d.earlier)
    lifetime["items"].append(("note", "Cache read = context re-sent each turn, billed cheaply"))
    return {
        "key": "breakdown",
        "title": "Token Types",
        "short": "Types",
        "icon": "chart.pie",
        "cards": [_breakdown_card("Today", d.today_models, 0), lifetime],
    }


def _models_card(title, models):
    totals = model_totals(models)
    whole = sum(t for _, t in totals)
    if not totals:
        return {"title": title, "items": [("note", "No usage yet")]}
    return {
        "title": title,
        "items": [_share_bar(model_display_name(m), t, whole) for m, t in totals],
    }


def _models_tab(d):
    lifetime = _models_card("Lifetime", d.lifetime_models)
    if d.earlier:
        lifetime["items"].append(
            ("note", f"Plus {format_count(d.earlier)} older tokens with no model detail")
        )
    return {
        "key": "models",
        "title": "Models",
        "short": "Models",
        "icon": "brain",
        "cards": [_models_card("Today", d.today_models), lifetime],
    }


def _projects_tab(d):
    projects = top_projects(d.daily, d.week_start, d.today)
    week_total = sum(t for _, t in model_totals(d.week_models))
    if projects:
        items = [_share_bar(name, tokens, week_total) for name, tokens in projects]
    else:
        items = [("note", "No usage in the last 7 days")]
    return {
        "key": "projects",
        "title": "Projects",
        "short": "Projects",
        "icon": "folder",
        "cards": [{"title": "Top projects · last 7 days", "items": items}],
    }


def _cost_tab(d):
    costs = {
        key: estimate_cost(models)
        for key, models in (
            ("today", d.today_models),
            ("week", d.week_models),
            ("month", d.month_models),
            ("all", d.lifetime_models),
        )
    }
    notes = []
    unpriced = max(u for _, u in costs.values())
    if unpriced:
        notes.append(("note", f"{format_count(unpriced)} tokens from unknown models not priced"))
    if d.earlier:
        notes.append(("note", f"{format_count(d.earlier)} older tokens not priced (no model detail)"))
    notes.append(("note", "Estimate at API list prices. Claude Pro is flat-rate,"))
    notes.append(("note", "so you aren't billed this."))
    return {
        "key": "cost",
        "title": "Estimated API Cost",
        "short": "Cost",
        "icon": "dollarsign.circle",
        "cards": [
            {
                "title": None,
                "items": [
                    (
                        "tiles",
                        [
                            ("Today", format_dollars(costs["today"][0]), "sun.max"),
                            ("This month", format_dollars(costs["month"][0]), "calendar"),
                        ],
                    )
                ],
            },
            {
                "title": None,
                "items": [
                    ("row", "Last 7 days", format_dollars(costs["week"][0])),
                    ("row", "All logged usage", format_dollars(costs["all"][0])),
                ]
                + notes,
            },
        ],
    }


def _sessions_tab(sessions):
    if sessions:
        items = [("row", s["label"], format_count(s["tokens"])) for s in sessions]
    else:
        items = [("note", "No Claude Code sessions running")]
    return {
        "key": "sessions",
        "title": "Active Sessions",
        "short": "Live",
        "icon": "terminal",
        "cards": [{"title": f"Open now ({len(sessions)})", "items": items}],
    }


def _leaderboard_tab(state, friends):
    view = state.get("leaderboard_view", "total")
    view_keys = [key for key, _ in LEADERBOARD_VIEWS]
    metric = "total_tokens" if view == "total" else "yesterday_tokens"
    ranking = [
        ("segmented", None, [label for _, label in LEADERBOARD_VIEWS],
         view_keys.index(view) if view in view_keys else 0, "leaderboard_view"),
    ]
    if friends:
        top = max(f.get(metric, 0) for f in friends) or 1
        for rank, friend in enumerate(friends, start=1):
            tokens = friend.get(metric, 0)
            ranking.append(
                ("bar", f"{rank}. {friend.get('name', 'Friend')}", format_count(tokens), tokens / top)
            )
    else:
        ranking.append(("note", "No friends added yet"))

    if state.get("my_gist_id"):
        first_row = [
            ("Share Code", "square.and.arrow.up", "leaderboard_share"),
            ("Push Now", "arrow.up.circle", "leaderboard_push"),
        ]
    else:
        first_row = [("Set Up Leaderboard", "person.crop.circle.badge.plus", "leaderboard_setup")]
    actions = [
        ("buttons", first_row),
        (
            "buttons",
            [
                ("Add Friend", "person.badge.plus", "leaderboard_add"),
                ("Pull Now", "arrow.down.circle", "leaderboard_pull"),
            ],
        ),
        ("note", "Scores are self-reported and can be faked. Just for fun."),
    ]
    return {
        "key": "leaderboard",
        "title": "Leaderboard (Beta)",
        "short": "Friends",
        "icon": "trophy",
        "cards": [{"title": "Ranking", "items": ranking}, {"title": None, "items": actions}],
    }


def settings_tab(state, paused, interval_choices):
    modes = [key for key, _ in TITLE_MODES]
    mode = state.get("title_mode", "lifetime")
    interval = state.get("scan_interval_seconds", interval_choices[0])
    font_size = state.get("menu_bar_font_size", DEFAULT_MENU_BAR_FONT_SIZE)
    return {
        "key": "settings",
        "title": "Settings",
        "short": "Settings",
        "icon": "slider.horizontal.3",
        "cards": [
            {
                "title": "Menu bar",
                "items": [
                    ("segmented", "Shows", [label for _, label in TITLE_MODES],
                     modes.index(mode) if mode in modes else 0, "title_mode"),
                    ("popup", "Text size", [f"{size} pt" for size in MENU_BAR_FONT_SIZES],
                     MENU_BAR_FONT_SIZES.index(font_size)
                     if font_size in MENU_BAR_FONT_SIZES
                     else MENU_BAR_FONT_SIZES.index(DEFAULT_MENU_BAR_FONT_SIZE),
                     "menu_bar_font_size"),
                ],
            },
            {
                "title": "Scanning",
                "items": [
                    ("popup", "Scan every", [format_interval(s) for s in interval_choices],
                     interval_choices.index(interval) if interval in interval_choices else 0,
                     "scan_interval"),
                    ("switch", "Pause scanning", paused, "pause"),
                ],
            },
            {
                "title": "General",
                "items": [
                    ("switch", "Start at login", state.get("start_at_login", True), "login"),
                    ("switch", "Show Leaderboard (Beta)", leaderboard_enabled(state),
                     "leaderboard_enabled"),
                ],
            },
            {
                "title": "About",
                "items": [
                    ("row", "Version", __version__),
                    ("row", "Original app by", ORIGINAL_AUTHOR),
                    ("row", "Redesign & new features by", FORK_AUTHOR),
                    ("buttons", [("View on GitHub", "arrow.up.right.square", "open_repo")]),
                ],
            },
        ],
    }


def leaderboard_enabled(state):
    """Whether the Leaderboard tab (and its daily sync) is on. Defaults to on
    only for people who already set the leaderboard up."""
    return state.get("leaderboard_enabled", bool(state.get("my_gist_id")))


def build_panel(state, sessions, friends, today=None):
    """The tabs shown in the tab bar, in order."""
    d = _Data(state, today or date.today())
    tabs = [
        _overview_tab(d),
        _breakdown_tab(d),
        _models_tab(d),
        _projects_tab(d),
        _cost_tab(d),
        _sessions_tab(sessions),
    ]
    if leaderboard_enabled(state):
        tabs.append(_leaderboard_tab(state, friends))
    return tabs
