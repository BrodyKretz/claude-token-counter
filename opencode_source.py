"""opencode usage, read from opencode's own database on this Mac.

The database is opened read-only, and only the token counts, model, time and
cost of each message (`session_message`) plus each session's folder
(`session_v2.directory`) are read. Message text and the database's account
and credential tables are never queried.

Each scan is merged into the saved per-day buckets keeping the larger
numbers, so conversations deleted in opencode don't shrink history.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from usage_stats import add_usage, merge_max_daily, project_label

OPENCODE_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

QUERY = """
    select m.data, s.directory, m.session_id
    from session_message m left join session_v2 s on s.id = m.session_id
    where json_extract(m.data, '$.tokens') is not null
"""

# Per-session totals. They also include calls opencode makes that aren't
# saved as messages (e.g. generating the session title).
SESSION_QUERY = """
    select id, directory, model, time_created, cost, tokens_input, tokens_output,
           tokens_reasoning, tokens_cache_read, tokens_cache_write
    from session_v2
"""


def _parts(tokens):
    cache = tokens.get("cache") or {}
    return {
        "input": tokens.get("input", 0) or 0,
        "output": (tokens.get("output", 0) or 0) + (tokens.get("reasoning", 0) or 0),
        "cache_write_5m": cache.get("write", 0) or 0,
        "cache_write_1h": 0,
        "cache_read": cache.get("read", 0) or 0,
    }


def read_opencode(db_path):
    """Per-day buckets for every message opencode recorded tokens for.
    Raises sqlite3.Error if the database can't be read as expected."""
    db = sqlite3.connect(f"{Path(db_path).as_uri()}?mode=ro", uri=True)
    try:
        rows = db.execute(QUERY).fetchall()
        try:
            sessions = db.execute(SESSION_QUERY).fetchall()
        except sqlite3.OperationalError:
            sessions = []  # older opencode without per-session totals
    finally:
        db.close()

    daily = {}
    counted = {}  # session id -> (parts, cost) already counted from messages
    for data_json, directory, session_id in rows:
        data = json.loads(data_json)
        parts = _parts(data.get("tokens") or {})
        created = (data.get("time") or {}).get("created")
        if not created or not sum(parts.values()):
            continue
        model = (data.get("model") or {}).get("id") or "unknown"
        cost = data.get("cost")
        cost = float(cost) if isinstance(cost, (int, float)) else None
        add_usage(daily, datetime.fromtimestamp(created / 1000).date(), model,
                  project_label(directory), parts, cost=cost)
        seen_parts, seen_cost = counted.setdefault(session_id, ({}, [0.0]))
        for category, count in parts.items():
            seen_parts[category] = seen_parts.get(category, 0) + count
        seen_cost[0] += cost or 0.0

    for row in sessions:
        _add_session_leftover(daily, row, counted.get(row[0], ({}, [0.0])))
    return daily


def _add_session_leftover(daily, row, already):
    """Count what a session's own totals have beyond its messages."""
    _, directory, model_json, created, cost, t_in, t_out, t_reason, t_read, t_write = row
    seen_parts, seen_cost = already
    session_parts = _parts({"input": t_in, "output": t_out, "reasoning": t_reason,
                            "cache": {"read": t_read, "write": t_write}})
    leftover = {c: max(n - seen_parts.get(c, 0), 0) for c, n in session_parts.items()}
    if not created or not sum(leftover.values()):
        return
    try:
        model = (json.loads(model_json) or {}).get("id") or "unknown"
    except (TypeError, json.JSONDecodeError):
        model = "unknown"
    extra_cost = max((cost or 0.0) - seen_cost[0], 0.0)
    add_usage(daily, datetime.fromtimestamp(created / 1000).date(), model,
              project_label(directory), leftover, cost=extra_cost or None)


def scan_opencode(source_state, db_path=OPENCODE_DB):
    """Update `source_state` from opencode's database. Sets
    source_state["error"] to a message if it couldn't be read, else None."""
    source_state.setdefault("daily", {})
    source_state["error"] = None
    if not Path(db_path).exists():
        return source_state
    try:
        current = read_opencode(db_path)
    except (sqlite3.Error, json.JSONDecodeError) as e:
        source_state["error"] = f"opencode's database couldn't be read ({e})"
        return source_state
    source_state["daily"] = merge_max_daily(source_state["daily"], current)
    return source_state


def opencode_daily(source_state):
    return source_state.get("daily", {})


def opencode_total(source_state):
    return sum(
        sum(parts.values())
        for bucket in source_state.get("daily", {}).values()
        for parts in bucket["models"].values()
    )
