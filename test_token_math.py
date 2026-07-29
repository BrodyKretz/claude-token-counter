import json

import pytest

from token_math import format_count, refresh_grand_total, sum_usage_since


def write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def assistant_entry(input_tokens, output_tokens, cache_creation=0, cache_read=0):
    return {
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
