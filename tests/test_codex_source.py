import json
import os

import pytest

from codex_source import codex_daily, codex_total, read_codex_file, scan_codex

TS = "2026-07-29T12:00:00.000Z"


def meta(cwd="/x/proj"):
    return {"timestamp": TS, "type": "session_meta", "payload": {"id": "s1", "cwd": cwd}}


def turn(model="gpt-5.6-luna", cwd="/x/proj"):
    return {"timestamp": TS, "type": "turn_context", "payload": {"cwd": cwd, "model": model}}


def usage(input_tokens=0, cached=0, cache_write=0, output=0):
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "cache_write_input_tokens": cache_write,
        "output_tokens": output,
        "total_tokens": input_tokens + output,
    }


def record(response_id, **kw):
    return {"timestamp": TS, "type": "token_usage_record",
            "payload": {"response_id": response_id, "usage": usage(**kw)}}


def running_total(**kw):
    return {"timestamp": TS, "type": "event_msg",
            "payload": {"type": "token_count", "info": {"total_token_usage": usage(**kw)}}}


def write(path, entries, partial_tail=None):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
        if partial_tail is not None:
            f.write(partial_tail)
    return path


def day_models(daily):
    return daily["2026-07-29"]["models"]


def test_records_are_normalized(tmp_path):
    path = write(tmp_path / "r.jsonl", [meta(), turn(), record("r1", input_tokens=12651, cached=8960, output=191)])

    parts = day_models(read_codex_file(path))["gpt-5.6-luna"]

    assert parts["input"] == 3691
    assert parts["cache_read"] == 8960
    assert parts["output"] == 191
    assert parts["cache_write_5m"] == 0


def test_project_comes_from_session_cwd(tmp_path):
    path = write(tmp_path / "r.jsonl", [meta(cwd="/x/game"), turn(cwd="/x/game"), record("r1", input_tokens=5)])

    assert read_codex_file(path)["2026-07-29"]["projects"] == {"/x/game": 5}


def test_duplicate_response_ids_count_once(tmp_path):
    path = write(tmp_path / "r.jsonl", [meta(), turn(), record("r1", input_tokens=10), record("r1", input_tokens=10)])

    assert day_models(read_codex_file(path))["gpt-5.6-luna"]["input"] == 10


def test_running_total_fallback_skips_repeats(tmp_path):
    path = write(tmp_path / "r.jsonl", [
        meta(), turn(),
        running_total(input_tokens=100),
        running_total(input_tokens=100),
        {"timestamp": TS, "type": "event_msg", "payload": {"type": "token_count", "info": None}},
        running_total(input_tokens=250),
    ])

    assert sum(day_models(read_codex_file(path))["gpt-5.6-luna"].values()) == 250


def test_records_win_over_running_totals(tmp_path):
    path = write(tmp_path / "r.jsonl", [meta(), turn(), record("r1", input_tokens=40), running_total(input_tokens=40)])

    assert sum(day_models(read_codex_file(path))["gpt-5.6-luna"].values()) == 40


def test_partial_last_line_ignored(tmp_path):
    path = write(tmp_path / "r.jsonl", [meta(), turn(), record("r1", input_tokens=10)],
                 partial_tail=json.dumps(record("r2", input_tokens=99))[:40])

    assert day_models(read_codex_file(path))["gpt-5.6-luna"]["input"] == 10


def test_new_session_without_usage_is_not_an_error(tmp_path):
    path = write(tmp_path / "r.jsonl", [meta(), turn()])

    assert read_codex_file(path) == {}


def _sessions(tmp_path):
    root = tmp_path / "sessions" / "2026" / "07" / "29"
    root.mkdir(parents=True)
    return tmp_path / "sessions", root


def test_rescan_replaces_file_contribution(tmp_path):
    sessions, root = _sessions(tmp_path)
    path = write(root / "rollout-a.jsonl", [meta(), turn(), record("r1", input_tokens=10)])
    state = {}
    scan_codex(state, sessions)
    assert codex_total(state) == 10

    write(path, [meta(), turn(), record("r1", input_tokens=10), record("r2", input_tokens=5)])
    os.utime(path, (1, 1))  # force a different mtime
    scan_codex(state, sessions)

    assert codex_total(state) == 15


def test_deleted_file_keeps_history(tmp_path):
    sessions, root = _sessions(tmp_path)
    path = write(root / "rollout-a.jsonl", [meta(), turn(), record("r1", input_tokens=10)])
    state = {}
    scan_codex(state, sessions)

    path.unlink()
    scan_codex(state, sessions)

    assert codex_total(state) == 10
    assert codex_daily(state)["2026-07-29"]["models"]["gpt-5.6-luna"]["input"] == 10


def test_unrecognized_file_sets_error_and_keeps_others(tmp_path):
    sessions, root = _sessions(tmp_path)
    write(root / "rollout-a.jsonl", [meta(), turn(), record("r1", input_tokens=10)])
    write(root / "rollout-b.jsonl", [{"something": "else"}])
    state = {}

    scan_codex(state, sessions)

    assert codex_total(state) == 10
    assert state["error"]


def test_missing_sessions_dir_is_empty_not_error(tmp_path):
    state = {}
    scan_codex(state, tmp_path / "nope")
    assert codex_total(state) == 0
    assert state["error"] is None
