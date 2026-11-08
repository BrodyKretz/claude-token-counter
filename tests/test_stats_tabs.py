from datetime import date

from stats_tabs import build_tabs, format_long_date, model_display_name, percent
from usage_stats import record_entry


def entry(ts, model="claude-opus-5-5", cwd="/x/proj", **usage):
    return {
        "type": "assistant",
        "timestamp": ts,
        "cwd": cwd,
        "message": {"model": model, "usage": usage},
    }


def test_model_display_name():
    assert model_display_name("claude-opus-5-5") == "Opus 5.5"
    assert model_display_name("claude-haiku-4-5-20251001") == "Haiku 4.5"
    assert model_display_name("claude-sonnet") == "Sonnet"
    assert model_display_name("<synthetic>") == "<synthetic>"


def test_percent():
    assert percent(0, 100) == "0%"
    assert percent(1, 1000) == "<1%"
    assert percent(50, 100) == "50%"
    assert percent(5, 0) == "0%"


def test_format_long_date():
    assert format_long_date("2026-11-03") == "November 3rd, 2026"
    assert format_long_date("2026-11-12") == "November 12th, 2026"


def test_build_tabs_names_and_row_shapes():
    daily = {}
    record_entry(daily, entry("2026-07-29T12:00:00.000Z", input_tokens=10, output_tokens=5))
    state = {"grand_total": 115, "daily": daily}
    sessions = [{"label": "~/proj", "tokens": 1500}]

    tabs = build_tabs(state, sessions, today=date(2026, 7, 29))

    assert [name for name, _ in tabs] == [
        "Tokens", "Models", "Projects", "History", "Cost", "Sessions",
    ]
    for _, rows in tabs:
        for row in rows:
            assert row[0] in {"heading", "row", "note", "gap"}
            assert len(row) == {"heading": 2, "row": 3, "note": 2, "gap": 1}[row[0]]
    tabs = dict(tabs)
    assert ("row", "Opus 5.5", "15") in tabs["Models"]
    assert ("row", "Older, no detail", "100  (87%)") in tabs["Tokens"]
    assert ("row", "/x/proj", "15") in tabs["Projects"]
    assert tabs["Sessions"] == [("row", "~/proj", "1.5K")]


def test_build_tabs_with_no_data():
    tabs = dict(build_tabs({"grand_total": 0}, [], today=date(2026, 7, 29)))
    assert tabs["Sessions"] == [("note", "No active sessions")]
    assert ("note", "No usage in the last 7 days") in tabs["Projects"]
