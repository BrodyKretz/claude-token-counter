import json
import os
import sqlite3
from datetime import datetime

from opencode_source import opencode_daily, opencode_total, read_opencode, scan_opencode

NOON = int(datetime(2026, 7, 29, 12, 0).timestamp() * 1000)  # local noon, in ms


def make_db(path, messages, sessions=(("s1", "/x/proj"),)):
    db = sqlite3.connect(path)
    db.execute("create table session_v2 (id text primary key, directory text not null)")
    db.execute("create table session_message (id text primary key, session_id text, type text, seq int,"
               " time_created int, time_updated int, data text)")
    db.executemany("insert into session_v2 values (?, ?)", sessions)
    for i, data in enumerate(messages):
        db.execute("insert into session_message values (?, ?, 'message', ?, 0, 0, ?)",
                   (f"m{i}", data.pop("_session", "s1"), i, json.dumps(data)))
    db.commit()
    db.close()
    return path


def message(input=0, output=0, reasoning=0, read=0, write=0, cost=None, model="gemini-4-argon", when=NOON, **extra):
    data = {"time": {"created": when}, "model": {"id": model, "providerID": "google"},
            "tokens": {"input": input, "output": output, "reasoning": reasoning,
                       "cache": {"read": read, "write": write}}}
    if cost is not None:
        data["cost"] = cost
    data.update(extra)
    return data


def test_tokens_normalized_and_cost_recorded(tmp_path):
    db = make_db(tmp_path / "o.db", [message(input=2261, output=63, reasoning=7, read=6555, write=3, cost=0.5),
                                     {"time": {"created": NOON}, "text": "user message, no tokens"}])

    day = read_opencode(db)["2026-07-29"]

    assert day["models"]["gemini-4-argon"] == {
        "input": 2261, "output": 70, "cache_write_5m": 3, "cache_write_1h": 0, "cache_read": 6555,
    }
    assert day["recorded_cost"] == {"gemini-4-argon": 0.5}


def test_project_from_session_directory(tmp_path):
    db = make_db(tmp_path / "o.db", [message(input=5, _session="s2")],
                 sessions=(("s2", "/x/game"),))

    assert read_opencode(db)["2026-07-29"]["projects"] == {"/x/game": 5}


def test_scan_never_shrinks_after_deletion(tmp_path):
    path = tmp_path / "o.db"
    make_db(path, [message(input=10), message(input=5)])
    state = {}
    scan_opencode(state, path)
    assert opencode_total(state) == 15

    os.remove(path)
    make_db(path, [message(input=10)])  # one conversation deleted in opencode
    scan_opencode(state, path)

    assert opencode_total(state) == 15


def test_missing_table_sets_error_keeps_history(tmp_path):
    path = tmp_path / "o.db"
    make_db(path, [message(input=10)])
    state = {}
    scan_opencode(state, path)

    os.remove(path)
    sqlite3.connect(path).execute("create table other (x int)").connection.close()
    scan_opencode(state, path)

    assert state["error"]
    assert opencode_total(state) == 10
    assert opencode_daily(state)["2026-07-29"]["models"]["gemini-4-argon"]["input"] == 10


def test_missing_database_is_empty_not_error(tmp_path):
    state = {}
    scan_opencode(state, tmp_path / "none.db")
    assert opencode_total(state) == 0
    assert state["error"] is None


def test_opened_read_only(tmp_path):
    path = make_db(tmp_path / "o.db", [message(input=1)])
    before = (path.stat().st_mtime_ns, path.stat().st_size)

    scan_opencode({}, path)

    assert (path.stat().st_mtime_ns, path.stat().st_size) == before
    assert not (tmp_path / "o.db-journal").exists()


def add_session_totals(path, session_id, model, created_ms, cost, **cols):
    db = sqlite3.connect(path)
    for name in ("model", "time_created", "cost", "tokens_input", "tokens_output", "tokens_reasoning",
                 "tokens_cache_read", "tokens_cache_write"):
        try:
            db.execute(f"alter table session_v2 add column {name}")
        except sqlite3.OperationalError:
            pass
    db.execute(
        "update session_v2 set model=?, time_created=?, cost=?, tokens_input=?, tokens_output=?,"
        " tokens_reasoning=?, tokens_cache_read=?, tokens_cache_write=? where id=?",
        (json.dumps({"id": model}), created_ms, cost, cols.get("input", 0), cols.get("output", 0),
         cols.get("reasoning", 0), cols.get("read", 0), cols.get("write", 0), session_id),
    )
    db.commit()
    db.close()


def test_session_leftover_tokens_counted(tmp_path):
    path = make_db(tmp_path / "o.db", [message(input=100, output=10, cost=0.25)])
    # The session's own totals include 50 input + 5 output the messages don't
    # (e.g. title generation), and 0.05 more cost.
    add_session_totals(path, "s1", "gemini-4-argon", NOON, 0.30, input=150, output=15)

    day = read_opencode(path)["2026-07-29"]

    assert day["models"]["gemini-4-argon"]["input"] == 150
    assert day["models"]["gemini-4-argon"]["output"] == 15
    assert abs(day["recorded_cost"]["gemini-4-argon"] - 0.30) < 1e-9


def test_session_totals_lower_than_messages_add_nothing(tmp_path):
    path = make_db(tmp_path / "o.db", [message(input=100)])
    add_session_totals(path, "s1", "gemini-4-argon", NOON, 0.0, input=40)

    assert read_opencode(path)["2026-07-29"]["models"]["gemini-4-argon"]["input"] == 100
