from datetime import date

from stats_tabs import (
    build_panel,
    format_interval,
    format_long_date,
    format_short_date,
    model_display_name,
    percent,
    settings_tab,
)
from usage_stats import record_entry

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
    )
    assert_well_formed(tab)
    items = items_of(tab)
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

    tab = settings_tab({}, paused=False, interval_choices=[15])
    about = next(c for c in tab["cards"] if c["title"] == "About")
    assert ("row", "Version", __version__) in about["items"]
    assert ("row", "Original app by", "BrodyKretz") in about["items"]
    assert ("row", "Redesign & new features by", "Raymond Tian") in about["items"]
