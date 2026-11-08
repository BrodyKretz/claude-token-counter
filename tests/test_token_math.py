import json
import os
import time
from datetime import date, datetime

import pytest

from token_math import (
    backfill_daily,
    format_count,
    refresh_grand_total,
    sum_usage_for_today,
    sum_usage_since,
)


def write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def assistant_entry(input_tokens, output_tokens, cache_creation=0, cache_read=0, timestamp=None):
    entry = {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            }
        },
    }
    if timestamp is not None:
        entry["timestamp"] = timestamp
    return entry


def test_sum_usage_since_sums_all_fields(tmp_path):
    path = tmp_path / "session.jsonl"
    write_jsonl(path, [assistant_entry(10, 20, 30, 40)])

    tokens, new_offset = sum_usage_since(path, 0)

    assert tokens == 100
    assert new_offset == path.stat().st_size


def test_sum_usage_since_ignores_non_assistant_entries(tmp_path):
    path = tmp_path / "session.jsonl"
    write_jsonl(path, [{"type": "user", "message": {}}, assistant_entry(5, 5)])

    tokens, _ = sum_usage_since(path, 0)

    assert tokens == 10


def test_sum_usage_since_only_counts_new_bytes(tmp_path):
    path = tmp_path / "session.jsonl"
    write_jsonl(path, [assistant_entry(10, 10)])
    offset_after_first = path.stat().st_size

    with open(path, "a") as f:
        f.write(json.dumps(assistant_entry(1, 1)) + "\n")

    tokens, new_offset = sum_usage_since(path, offset_after_first)

    assert tokens == 2
    assert new_offset == path.stat().st_size


def test_sum_usage_since_skips_incomplete_trailing_line(tmp_path):
    path = tmp_path / "session.jsonl"
    write_jsonl(path, [assistant_entry(10, 10)])
    with open(path, "a") as f:
        f.write('{"type": "assistant", "message": {"usage":')  # no trailing newline

    tokens, new_offset = sum_usage_since(path, 0)

    assert tokens == 20
    assert new_offset == len(
        json.dumps(assistant_entry(10, 10)) + "\n"
    )


def test_refresh_grand_total_initial_scan_sums_everything(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "some-project"
    project.mkdir(parents=True)
    write_jsonl(project / "a.jsonl", [assistant_entry(10, 10)])
    write_jsonl(project / "b.jsonl", [assistant_entry(5, 5)])

    state = {"grand_total": 0, "file_offsets": {}}
    refresh_grand_total(state, projects_dir=projects_dir)

    assert state["grand_total"] == 30
    assert len(state["file_offsets"]) == 2


def test_refresh_grand_total_only_adds_new_tokens_on_second_call(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "some-project"
    project.mkdir(parents=True)
    session_file = project / "a.jsonl"
    write_jsonl(session_file, [assistant_entry(10, 10)])

    state = {"grand_total": 0, "file_offsets": {}}
    refresh_grand_total(state, projects_dir=projects_dir)
    assert state["grand_total"] == 20

    with open(session_file, "a") as f:
        f.write(json.dumps(assistant_entry(1, 1)) + "\n")

    refresh_grand_total(state, projects_dir=projects_dir)

    assert state["grand_total"] == 22


def test_refresh_grand_total_drops_deleted_files_without_losing_total(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "some-project"
    project.mkdir(parents=True)
    session_file = project / "a.jsonl"
    write_jsonl(session_file, [assistant_entry(10, 10)])

    state = {"grand_total": 0, "file_offsets": {}}
    refresh_grand_total(state, projects_dir=projects_dir)
    assert state["grand_total"] == 20

    session_file.unlink()
    refresh_grand_total(state, projects_dir=projects_dir)

    assert state["grand_total"] == 20
    assert state["file_offsets"] == {}


@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0"),
        (999, "999"),
        (1_000, "1.0K"),
        (12_345, "12.3K"),
        (1_000_000, "1.0M"),
        (2_500_000, "2.5M"),
        (1_000_000_000, "1.0B"),
        (2_451_790_780, "2.5B"),
    ],
)
def test_format_count(n, expected):
    assert format_count(n) == expected


def test_sum_usage_for_today_only_counts_matching_date(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "some-project"
    project.mkdir(parents=True)
    path = project / "session.jsonl"
    write_jsonl(
        path,
        [
            assistant_entry(10, 10, timestamp="2026-07-29T12:00:00.000Z"),
            assistant_entry(5, 5, timestamp="2026-07-28T12:00:00.000Z"),
        ],
    )
    now = time.time()
    os.utime(path, (now, now))

    total = sum_usage_for_today(projects_dir=projects_dir, today=date(2026, 7, 29))

    assert total == 20


def test_sum_usage_for_today_skips_files_not_modified_today(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "some-project"
    project.mkdir(parents=True)
    path = project / "session.jsonl"
    write_jsonl(path, [assistant_entry(10, 10, timestamp="2026-07-29T12:00:00.000Z")])
    two_days_before = datetime(2026, 7, 27, 12, 0).timestamp()
    os.utime(path, (two_days_before, two_days_before))

    total = sum_usage_for_today(projects_dir=projects_dir, today=date(2026, 7, 29))

    assert total == 0


def test_sum_usage_for_today_ignores_entries_missing_usage_or_timestamp(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "some-project"
    project.mkdir(parents=True)
    path = project / "session.jsonl"
    write_jsonl(
        path,
        [
            {"type": "assistant", "message": {}},
            assistant_entry(3, 3, timestamp="2026-07-29T12:00:00.000Z"),
        ],
    )
    now = time.time()
    os.utime(path, (now, now))

    total = sum_usage_for_today(projects_dir=projects_dir, today=date(2026, 7, 29))

    assert total == 6


def test_refresh_records_daily_buckets(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "p"
    project.mkdir(parents=True)
    write_jsonl(
        project / "s.jsonl",
        [assistant_entry(1, 2, 3, 4, timestamp="2026-07-29T12:00:00.000Z")],
    )
    state = {"grand_total": 0, "file_offsets": {}}

    refresh_grand_total(state, projects_dir=projects_dir)

    assert state["grand_total"] == 10
    assert len(state["daily"]) == 1


def test_backfill_reads_only_up_to_saved_offsets_and_keeps_grand_total(tmp_path):
    path = tmp_path / "s.jsonl"
    write_jsonl(
        path,
        [
            assistant_entry(5, 5, timestamp="2026-07-29T12:00:00.000Z"),
            assistant_entry(100, 100, timestamp="2026-07-29T13:00:00.000Z"),
        ],
    )
    first_line_end = len(path.read_bytes().splitlines(keepends=True)[0])
    state = {"grand_total": 999, "file_offsets": {str(path): first_line_end}}

    backfill_daily(state)

    day = next(iter(state["daily"].values()))
    assert sum(day["models"]["unknown"].values()) == 10
    assert state["grand_total"] == 999
    assert state["daily_backfilled"] is True


def test_backfill_runs_only_once(tmp_path):
    path = tmp_path / "s.jsonl"
    write_jsonl(path, [assistant_entry(5, 5, timestamp="2026-07-29T12:00:00.000Z")])
    state = {"grand_total": 0, "file_offsets": {str(path): path.stat().st_size}}

    backfill_daily(state)
    backfill_daily(state)

    day = next(iter(state["daily"].values()))
    assert sum(day["models"]["unknown"].values()) == 10


def test_backfill_skips_missing_files(tmp_path):
    state = {"grand_total": 0, "file_offsets": {str(tmp_path / "gone.jsonl"): 50}}

    backfill_daily(state)

    assert state["daily"] == {}
