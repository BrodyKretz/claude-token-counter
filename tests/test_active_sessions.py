import json
from pathlib import Path

import active_sessions


def write_jsonl(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def assistant_entry(input_tokens, output_tokens):
    return {
        "type": "assistant",
        "message": {"usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}},
    }


def test_display_name_collapses_home_to_tilde():
    assert active_sessions.display_name("/Users/alice", home="/Users/alice") == "~"


def test_display_name_collapses_home_prefixed_path():
    assert (
        active_sessions.display_name("/Users/alice/work/thing", home="/Users/alice")
        == "~/work/thing"
    )


def test_display_name_leaves_unrelated_path_untouched():
    assert active_sessions.display_name("/opt/other", home="/Users/alice") == "/opt/other"


def test_project_dir_for_cwd_escapes_slashes(tmp_path):
    projects_dir = tmp_path / "projects"
    result = active_sessions.project_dir_for_cwd("/Users/alice/work/thing", projects_dir)
    assert result == projects_dir / "-Users-alice-work-thing"


def test_active_sessions_sums_tokens_per_matched_project_dir(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "-Users-alice-work-thing"
    project.mkdir(parents=True)
    write_jsonl(project / "session.jsonl", [assistant_entry(10, 20)])

    sessions = active_sessions.active_sessions(
        projects_dir=projects_dir, cwds=["/Users/alice/work/thing"]
    )

    assert sessions == [{"label": "/Users/alice/work/thing", "tokens": 30}]


def test_active_sessions_ignores_cwds_with_no_project_dir(tmp_path):
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()

    sessions = active_sessions.active_sessions(
        projects_dir=projects_dir, cwds=["/Users/alice/nonexistent"]
    )

    assert sessions == []


def test_active_sessions_picks_top_n_most_recent_files_for_shared_cwd(tmp_path):
    projects_dir = tmp_path / "projects"
    project = projects_dir / "-Users-alice"
    project.mkdir(parents=True)

    old_file = project / "old.jsonl"
    write_jsonl(old_file, [assistant_entry(1, 1)])

    mid_file = project / "mid.jsonl"
    write_jsonl(mid_file, [assistant_entry(2, 2)])

    new_file = project / "new.jsonl"
    write_jsonl(new_file, [assistant_entry(3, 3)])

    # ensure ordering isn't a coincidence of filesystem write order
    import os
    import time

    now = time.time()
    os.utime(old_file, (now - 30, now - 30))
    os.utime(mid_file, (now - 20, now - 20))
    os.utime(new_file, (now - 10, now - 10))

    sessions = active_sessions.active_sessions(
        projects_dir=projects_dir, cwds=["/Users/alice", "/Users/alice"]
    )

    tokens_found = sorted(s["tokens"] for s in sessions)
    assert tokens_found == [4, 6]  # new.jsonl (6) and mid.jsonl (4), old.jsonl dropped


def test_active_sessions_sorted_by_tokens_descending(tmp_path):
    projects_dir = tmp_path / "projects"
    small = projects_dir / "-Users-alice-small"
    small.mkdir(parents=True)
    write_jsonl(small / "s.jsonl", [assistant_entry(1, 1)])

    big = projects_dir / "-Users-alice-big"
    big.mkdir(parents=True)
    write_jsonl(big / "s.jsonl", [assistant_entry(100, 100)])

    sessions = active_sessions.active_sessions(
        projects_dir=projects_dir,
        cwds=["/Users/alice/small", "/Users/alice/big"],
    )

    assert [s["tokens"] for s in sessions] == [200, 2]
