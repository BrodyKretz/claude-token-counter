from datetime import date

from stats_tabs import (
    build_panel as _build_panel,
    leaderboard_enabled,
    tool_choices,
    welcome_tab,
    format_interval,
    format_long_date,
    format_short_date,
    model_display_name,
    percent,
    settings_tab,
)
from tools import tool_view
from usage_stats import add_usage, record_entry


def build_panel(state, sessions, friends, today=None, view=None, show_leaderboard=None):
    """Old call shape for these tests: Claude Code's view of `state`."""
    return _build_panel(
        view or tool_view(state, "claude_code"), state, sessions, friends,
        leaderboard_enabled(state) if show_leaderboard is None else show_leaderboard,
        today=today,
    )

ITEM_LENGTHS = {
    "tiles": 2, "chart": 3, "bar": 4, "row": 3, "note": 2, "buttons": 2,
    "segmented": 5, "popup": 5, "switch": 4,
}


def entry(ts, model="claude-opus-5-5", cwd="/x/proj", **usage):
    return {
        "type": "assistant",
        "timestamp": ts,
        "cwd": cwd,
        "message": {"model": model, "usage": usage},
    }


def assert_well_formed(tab):
    assert {"key", "title", "short", "icon", "cards"} <= tab.keys()
    for card in tab["cards"]:
        assert card["items"], tab["key"]
        for item in card["items"]:
            assert len(item) == ITEM_LENGTHS[item[0]], item
            if item[0] == "bar":
                assert 0.0 <= item[3] <= 1.0


def items_of(tab):
    return [item for card in tab["cards"] for item in card["items"]]


def test_formatters():
    assert model_display_name("claude-opus-5-5") == "Opus 5.5"
    assert model_display_name("claude-haiku-4-5-20251001") == "Haiku 4.5"
    assert model_display_name("<synthetic>") == "<synthetic>"
    assert percent(1, 1000) == "<1%"
    assert percent(50, 100) == "50%"
    assert percent(5, 0) == "0%"
    assert format_long_date("2026-11-03") == "November 3rd, 2026"
    assert format_short_date(date(2026, 11, 12)) == "Nov 12th"
    assert format_interval(15) == "15 seconds"
    assert format_interval(60) == "1 minute"


def test_build_panel_with_data():
    daily = {}
    record_entry(daily, entry("2026-07-29T12:00:00.000Z", input_tokens=10, output_tokens=5))
    state = {"grand_total": 115, "daily": daily, "leaderboard_view": "total",
             "leaderboard_enabled": True}
    sessions = [{"label": "~/proj", "tokens": 1500}]
    friends = [{"name": "Ann", "total_tokens": 200, "yesterday_tokens": 1},
               {"name": "Bo", "total_tokens": 100, "yesterday_tokens": 2}]

    tabs = build_panel(state, sessions, friends, today=date(2026, 7, 29))

    assert [t["key"] for t in tabs] == [
        "overview", "breakdown", "models", "projects", "cost", "sessions", "leaderboard",
    ]
    for tab in tabs:
        assert_well_formed(tab)
    tabs = {t["key"]: t for t in tabs}
    assert ("tiles", [("Today", "15", "sun.max"), ("Lifetime", "115", "infinity")]) in items_of(tabs["overview"])
    chart = next(i for i in items_of(tabs["overview"]) if i[0] == "chart")
    assert len(chart[1]) == 14 and chart[1][-1] == 15
    assert ("bar", "Older, no detail", "100 · 87%", 100 / 115) in items_of(tabs["breakdown"])
    assert ("bar", "Opus 5.5", "15 · 100%", 1.0) in items_of(tabs["models"])
    assert ("bar", "/x/proj", "15 · 100%", 1.0) in items_of(tabs["projects"])
    assert tabs["sessions"]["cards"][0]["title"] == "Open now (1)"
    assert ("bar", "1. Ann", "200", 1.0) in items_of(tabs["leaderboard"])
    assert ("bar", "2. Bo", "100", 0.5) in items_of(tabs["leaderboard"])


def test_build_panel_with_no_data():
    tabs = {t["key"]: t for t in build_panel({"grand_total": 0, "leaderboard_enabled": True}, [], [],
                                             today=date(2026, 7, 29))}
    for tab in tabs.values():
        assert_well_formed(tab)
    assert ("note", "No Claude Code sessions running") in items_of(tabs["sessions"])
    assert ("note", "No friends added yet") in items_of(tabs["leaderboard"])
    buttons = [i for i in items_of(tabs["leaderboard"]) if i[0] == "buttons"]
    assert buttons[0][1][0][2] == "leaderboard_setup"


def test_leaderboard_buttons_after_setup():
    tabs = {t["key"]: t for t in build_panel({"grand_total": 0, "my_gist_id": "abc"}, [], [],
                                             today=date(2026, 7, 29))}
    actions = [b[2] for i in items_of(tabs["leaderboard"]) if i[0] == "buttons" for b in i[1]]
    assert actions == ["leaderboard_share", "leaderboard_push", "leaderboard_add", "leaderboard_pull"]


def test_settings_tab_reflects_state():
    tab = settings_tab(
        {"title_mode": "icon", "scan_interval_seconds": 60, "start_at_login": False},
        paused=True,
        interval_choices=[5, 15, 30, 60, 300],
        detected=["claude_code"],
    )
    assert_well_formed(tab)
    items = items_of({**tab, "cards": [c for c in tab["cards"] if c["title"] not in ("AI tools", "AI providers")]})
    assert ("segmented", "Shows", ["Lifetime", "Today", "Icon only"], 2, "title_mode") in items
    assert items[1] == ("popup", "Text size", ["10 pt", "11 pt", "12 pt", "13 pt", "14 pt"], 2,
                        "menu_bar_font_size")  # 12 pt by default
    assert items[2][3] == 3  # 60 seconds selected
    assert ("switch", "Pause scanning", True, "pause") in items
    assert ("switch", "Start at login", False, "login") in items


def test_leaderboard_tab_hidden_unless_enabled():
    def keys(state):
        return [t["key"] for t in build_panel(state, [], [], today=date(2026, 7, 29))]

    assert "leaderboard" not in keys({"grand_total": 0})
    assert "leaderboard" in keys({"grand_total": 0, "leaderboard_enabled": True})
    # Existing leaderboard users keep the tab by default.
    assert "leaderboard" in keys({"grand_total": 0, "my_gist_id": "abc"})
    assert "leaderboard" not in keys({"grand_total": 0, "my_gist_id": "abc", "leaderboard_enabled": False})


def test_settings_about_card_shows_version_and_credits():
    from version import __version__

    tab = settings_tab({}, paused=False, interval_choices=[15], detected=["claude_code"])
    about = next(c for c in tab["cards"] if c["title"] == "About")
    assert ("row", "Version", __version__) in about["items"]
    assert ("row", "Original app by", "BrodyKretz") in about["items"]
    assert ("row", "Redesign & new features by", "Raymond Tian") in about["items"]


PARTS = {"input": 0, "output": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0}


def view_of(daily, name="Codex", key="codex", total=None, error=None):
    if total is None:
        total = sum(sum(p.values()) for b in daily.values() for p in b["models"].values())
    return {"key": key, "name": name, "daily": daily, "grand_total": total, "error": error}


def test_overview_shows_new_input_plus_output():
    daily = {}
    add_usage(daily, date(2026, 7, 29), "gpt-x", "~/p", {**PARTS, "input": 30, "output": 5, "cache_read": 900})

    tabs = {t["key"]: t for t in build_panel({}, [], [], today=date(2026, 7, 29), view=view_of(daily))}

    assert ("row", "New input + output", "35") in items_of(tabs["overview"])


def test_error_note_shown():
    tabs = {t["key"]: t for t in build_panel({}, [], [], today=date(2026, 7, 29),
                                             view=view_of({}, error="bad file"))}

    assert tabs["overview"]["cards"][0]["items"][0] == ("note", "Codex data couldn't be read: bad file")


def test_cost_uses_recorded_cost():
    daily = {}
    add_usage(daily, date(2026, 7, 29), "gemini-4-argon", "~/p", {**PARTS, "input": 10}, cost=1.25)

    tabs = {t["key"]: t for t in build_panel({}, [], [], today=date(2026, 7, 29),
                                             view=view_of(daily, "opencode", "opencode"))}

    assert ("Today", "$1.25", "sun.max") in tabs["cost"]["cards"][0]["items"][0][1]


def test_sessions_empty_message_names_tool():
    tabs = {t["key"]: t for t in build_panel({}, [], [], today=date(2026, 7, 29), view=view_of({}))}

    assert ("note", "No Codex sessions running") in items_of(tabs["sessions"])


def test_sessions_without_token_counts_show_running():
    tabs = {t["key"]: t for t in build_panel({}, [{"label": "~/p", "tokens": None}], [],
                                             today=date(2026, 7, 29), view=view_of({}))}

    assert ("row", "~/p", "running") in items_of(tabs["sessions"])


def test_leaderboard_only_when_requested():
    state = {"grand_total": 0, "leaderboard_enabled": True}
    keys = [t["key"] for t in build_panel(state, [], [], today=date(2026, 7, 29), show_leaderboard=False)]
    assert "leaderboard" not in keys


def test_settings_lists_detected_tools_only():
    state = {"enabled_tools": ["claude_code"], "combine_tools": False}

    tab = settings_tab(state, paused=False, interval_choices=[15], detected=["claude_code", "opencode"])

    tools_card = next(c for c in tab["cards"] if c["title"] == "AI tools")
    tools = [i for i in tools_card["items"] if i[-1].startswith("tool:") or i[-1] == "combine_tools"]
    assert tools == [
        ("switch", "Claude Code", True, "tool:claude_code"),
        ("switch", "opencode", False, "tool:opencode"),
        ("switch", "Combine all tools", False, "combine_tools"),
    ]


def test_welcome_lists_detected_tools():
    tab = welcome_tab(["claude_code", "codex"], chosen=["codex"])

    assert tab["key"] == "welcome"
    items = items_of(tab)
    assert ("switch", "Claude Code", False, "welcome_tool:claude_code") in items
    assert ("switch", "Codex", True, "welcome_tool:codex") in items
    assert ("buttons", [("Continue", "arrow.right.circle", "welcome_done")]) in items


def test_welcome_with_no_tools_detected():
    items = items_of(welcome_tab([], chosen=[]))

    assert ("note", "No supported AI tools found on this Mac yet.") in items
    assert ("buttons", [("Continue", "arrow.right.circle", "welcome_done")]) in items


def test_tool_choices_are_enabled_tools_detected_or_with_history():
    state = {"enabled_tools": ["claude_code", "codex", "opencode"],
             "sources": {"opencode": {"daily": {"2026-07-29": {"models": {}, "projects": {}}}}}}

    assert tool_choices(state, detected=["claude_code"]) == [
        ("claude_code", "Claude Code"), ("opencode", "opencode"),
    ]


def test_settings_keeps_enabled_tool_whose_data_disappeared():
    state = {"enabled_tools": ["claude_code", "codex"], "combine_tools": False}

    tab = settings_tab(state, paused=False, interval_choices=[15], detected=["claude_code"])

    tools_card = next(c for c in tab["cards"] if c["title"] == "AI tools")
    assert ("switch", "Codex", True, "tool:codex") in tools_card["items"]


def test_combined_cost_prices_each_tool_separately():
    from tools import combined_view

    claude_daily, opencode_daily = {}, {}
    add_usage(claude_daily, date(2026, 7, 29), "claude-opus-5-5", "~/p", {**PARTS, "input": 1_000_000})
    add_usage(opencode_daily, date(2026, 7, 29), "claude-opus-5-5", "~/p", {**PARTS, "input": 10}, cost=0.5)
    state = {"grand_total": 1_000_000, "daily": claude_daily,
             "sources": {"opencode": {"daily": opencode_daily}}}

    view = combined_view(state, ["claude_code", "opencode"])
    tabs = {t["key"]: t for t in build_panel(state, [], [], today=date(2026, 7, 29), view=view)}

    # Claude Code: 1M input at $4/M; opencode: its recorded $0.50.
    assert ("Today", "$4.50", "sun.max") in tabs["cost"]["cards"][0]["items"][0][1]


# --- providers ------------------------------------------------------------

def _provider_view(key="openai", name="OpenAI"):
    daily = {}
    add_usage(daily, date(2026, 11, 8), "gpt-5", "~/a", {"input": 5})
    return {"key": key, "name": name, "daily": daily, "grand_total": 5, "error": None,
            "views": []}


def _card(tabs, tab_key, title):
    tab = next(t for t in tabs if t["key"] == tab_key)
    return next(c for c in tab["cards"] if c["title"] == title)


def test_tool_choices_add_enabled_providers_after_tools():
    state = {"enabled_tools": ["claude_code"], "enabled_providers": ["kimi", "openai"]}

    assert tool_choices(state, detected=["claude_code"]) == [
        ("claude_code", "Claude Code"), ("openai", "OpenAI"), ("kimi", "Kimi"),
    ]


def test_provider_view_has_no_live_sessions_tab():
    tabs = build_panel({}, [], [], today=date(2026, 11, 8), view=_provider_view())

    assert "sessions" not in [t["key"] for t in tabs]


def test_provider_account_card_without_key_says_how_to_add_one():
    tabs = build_panel({}, [], [], today=date(2026, 11, 8), view=_provider_view())

    items = _card(tabs, "overview", "OpenAI account")["items"]
    assert items[0][0] == "note"
    assert "API key in Settings" in " ".join(i[1] for i in items)


def test_provider_account_card_with_fetched_numbers():
    account_daily = {}
    add_usage(account_daily, date(2026, 11, 8), "gpt-5", "Account", {"input": 1000})
    add_usage(account_daily, date(2026, 11, 1), "gpt-5", "Account", {"input": 2000})
    add_usage(account_daily, date(2026, 10, 15), "gpt-5", "Account", {"input": 4000})
    state = {"provider_keys": ["openai"], "accounts": {"openai": {
        "daily": account_daily, "cost": {"2026-11-08": 1.5, "2026-10-15": 2.0},
        "rows": [["Balance", "$3.00"]], "notes": ["Hello"], "error": "boom",
        "fetched_at": "2026-11-08T09:05:00", "attempted_at": "2026-11-08T09:20:00",
    }}}

    tabs = build_panel(state, [], [], today=date(2026, 11, 8), view=_provider_view())

    items = _card(tabs, "overview", "OpenAI account")["items"]
    assert ("row", "Today", "1.0K") in items
    assert ("row", "Last 7 days", "1.0K") in items
    assert ("row", "Last 30 days", "7.0K") in items
    assert ("row", "Billed, last 30 days", "$3.50") in items
    assert ("row", "Balance", "$3.00") in items
    notes = [i[1] for i in items if i[0] == "note"]
    assert "Hello" in notes
    assert any("boom" in n for n in notes)
    assert "Updated 9:05 AM" in notes


def test_provider_account_card_before_first_fetch():
    state = {"provider_keys": ["kimi"], "accounts": {}}

    tabs = build_panel(state, [], [], today=date(2026, 11, 8), view=_provider_view("kimi", "Kimi"))

    assert ("note", "Fetching account numbers…") in _card(tabs, "overview", "Kimi account")["items"]


def test_tool_views_have_no_account_card():
    tabs = build_panel({}, [], [], today=date(2026, 11, 8))

    titles = [c["title"] for c in tabs[0]["cards"]]
    assert not any(t and t.endswith("account") for t in titles)


def test_settings_providers_card():
    state = {"enabled_tools": [], "enabled_providers": ["openai", "kimi"],
             "provider_keys": ["kimi"]}

    tab = settings_tab(state, paused=False, interval_choices=[15], detected=[])

    assert "AI providers" not in [c["title"] for c in tab["cards"]]
    items = next(c for c in tab["cards"] if c["title"] == "AI tools")["items"]
    assert ("switch", "OpenAI", True, "provider:openai") in items
    assert ("switch", "DeepSeek", False, "provider:deepseek") in items
    assert ("buttons", [("Add API Key", "key", "provider_key:openai")]) in items
    assert ("buttons", [("Replace Key", "key", "provider_key:kimi"),
                        ("Remove Key", "trash", "provider_key_remove:kimi")]) in items
    assert ("row", "Kimi key", "In Keychain") in items
    # DeepSeek is off: no key controls for it.
    assert not any("deepseek" in str(i[-1]) for i in items if i[0] == "buttons")


def test_long_notes_are_split_into_lines():
    from stats_tabs import note_lines
    text = "the API key was rejected (HTTP 401) and some more words to make it long"

    lines = note_lines(text)

    assert len(lines) > 1
    assert all(item[0] == "note" and len(item[1]) <= 46 for item in lines)
    assert " ".join(item[1] for item in lines) == text


def test_view_choices_when_combined_offers_all_tools_and_providers():
    from stats_tabs import view_choices
    state = {"enabled_tools": ["claude_code"], "combine_tools": True}

    assert view_choices(state, ["claude_code"]) == []
    state["enabled_providers"] = ["deepseek"]
    assert view_choices(state, ["claude_code"]) == [("all", "All tools"), ("deepseek", "DeepSeek")]


def test_view_choices_per_tool_matches_tool_choices():
    from stats_tabs import view_choices
    state = {"enabled_tools": ["claude_code"], "enabled_providers": ["kimi"]}

    assert view_choices(state, ["claude_code"]) == tool_choices(state, ["claude_code"])


def test_tools_and_providers_share_one_card_with_combine_last():
    state = {"enabled_tools": ["claude_code"], "enabled_providers": ["kimi"], "combine_tools": False}

    tab = settings_tab(state, paused=False, interval_choices=[15], detected=["claude_code", "codex"])

    items = next(c for c in tab["cards"] if c["title"] == "AI tools")["items"]
    switches = [i[1] for i in items if i[0] == "switch"]
    assert switches == ["Claude Code", "Codex", "OpenAI", "DeepSeek", "Kimi", "Combine all tools"]
