from datetime import date

from usage_stats import (
    biggest_day,
    category_totals,
    history,
    model_totals,
    models_all_time,
    project_label,
    record_entry,
    split_usage,
    top_projects,
    total_in_range,
)


def entry(model="claude-opus-5-5", ts="2026-07-29T12:00:00.000Z", cwd="/Users/me/proj", **usage):
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    base.update(usage)
    return {
        "type": "assistant",
        "timestamp": ts,
        "cwd": cwd,
        "message": {"model": model, "usage": base},
    }


def test_split_usage_separates_1h_cache_writes():
    parts = split_usage(
        {
            "input_tokens": 1,
            "output_tokens": 2,
            "cache_creation_input_tokens": 30,
            "cache_read_input_tokens": 4,
            "cache_creation": {"ephemeral_1h_input_tokens": 20, "ephemeral_5m_input_tokens": 10},
        }
    )
    assert parts == {
        "input": 1,
        "output": 2,
        "cache_write_5m": 10,
        "cache_write_1h": 20,
        "cache_read": 4,
    }


def test_split_usage_without_detail_counts_writes_as_5m():
    parts = split_usage({"cache_creation_input_tokens": 7})
    assert parts["cache_write_5m"] == 7
    assert parts["cache_write_1h"] == 0


def test_project_label_folds_worktrees_and_shortens_home():
    home = "/Users/me"
    assert project_label("/Users/me/app/.claude/worktrees/agent-abc", home=home) == "~/app"
    assert project_label("/Users/me", home=home) == "~"
    assert project_label("/opt/x", home=home) == "/opt/x"
    assert project_label(None, home=home) == "Unknown"


def test_record_entry_skips_zero_usage_and_missing_timestamp():
    daily = {}
    record_entry(daily, entry(model="<synthetic>"))
    no_ts = entry(input_tokens=5)
    del no_ts["timestamp"]
    record_entry(daily, no_ts)
    assert daily == {}


def test_aggregations_across_days_models_and_projects():
    daily = {}
    record_entry(daily, entry(ts="2026-07-29T12:00:00.000Z", input_tokens=10, cwd="/a"))
    record_entry(daily, entry(model="claude-sonnet-5-5", ts="2026-07-29T13:00:00.000Z", output_tokens=5, cwd="/b"))
    record_entry(daily, entry(ts="2026-07-20T12:00:00.000Z", cache_read_input_tokens=100, cwd="/a"))

    models = models_all_time(daily)
    assert model_totals(models) == [("claude-opus-5-5", 110), ("claude-sonnet-5-5", 5)]
    assert category_totals(models)["cache_read"] == 100
    july29 = date(2026, 7, 29)
    assert total_in_range(daily, july29, july29) == 15
    assert top_projects(daily, date(2026, 7, 1), july29) == [("/a", 110), ("/b", 5)]
    assert biggest_day(daily) == (date(2026, 7, 20), 100)


def test_history_windows():
    daily = {}
    record_entry(daily, entry(ts="2026-07-28T12:00:00.000Z", input_tokens=1))
    record_entry(daily, entry(ts="2026-07-23T12:00:00.000Z", input_tokens=10))
    record_entry(daily, entry(ts="2026-07-02T12:00:00.000Z", input_tokens=100))
    record_entry(daily, entry(ts="2026-06-15T12:00:00.000Z", input_tokens=1000))

    stats = history(daily, today=date(2026, 7, 29))

    assert stats["yesterday"] == 1
    assert stats["last_7_days"] == 11
    assert stats["this_month"] == 111
    assert stats["biggest_day"] == (date(2026, 6, 15), 1000)


def test_biggest_day_none_when_empty():
    assert biggest_day({}) is None


def test_top_projects_folds_subfolders_into_parent_project():
    daily = {}
    record_entry(daily, entry(input_tokens=10, cwd="/x/game"))
    record_entry(daily, entry(input_tokens=5, cwd="/x/game/tools"))
    record_entry(daily, entry(input_tokens=1, cwd="/x/gamer"))
    july29 = date(2026, 7, 29)
    assert top_projects(daily, july29, july29) == [("/x/game", 15), ("/x/gamer", 1)]
