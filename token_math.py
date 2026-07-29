import json
from datetime import date, datetime
from pathlib import Path

CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def load_state(state_file):
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"grand_total": 0, "file_offsets": {}, "first_seen_at": None}


def save_state(state, state_file):
    state_file.write_text(json.dumps(state))


def sum_usage_since(path, offset):
    """Sum token usage from an assistant-log jsonl file starting at a byte offset.

    Only consumes complete (newline-terminated) lines so a session file being
    actively written to never has a half-written JSON line parsed.
    Returns (tokens_found, new_offset).
    """
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()

    tokens = 0
    consumed = 0
    for line in data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        consumed += len(line)
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        usage = entry.get("message", {}).get("usage")
        if not usage:
            continue
        tokens += (
            usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
    return tokens, offset + consumed


def refresh_grand_total(state, projects_dir=CLAUDE_PROJECTS_DIR):
    """Mutates and returns state with grand_total updated by any newly-seen tokens.

    Files no longer on disk (pruned after 30 days) are dropped from tracking
    without touching grand_total, since their tokens were already counted
    while they existed.
    """
    offsets = state["file_offsets"]
    current_files = {str(p) for p in projects_dir.rglob("*.jsonl")}

    for tracked_path in list(offsets):
        if tracked_path not in current_files:
            del offsets[tracked_path]

    for path_str in current_files:
        offset = offsets.get(path_str, 0)
        tokens, new_offset = sum_usage_since(path_str, offset)
        state["grand_total"] += tokens
        offsets[path_str] = new_offset

    return state


def _local_date_of(timestamp_str):
    """Convert a log entry's UTC timestamp (e.g. "2026-07-23T04:42:51.880Z")
    into the local calendar date it falls on.
    """
    utc_dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
    return utc_dt.astimezone().date()


def _sum_usage_for_date_in_file(path, target_date):
    total = 0
    with open(path, "rb") as f:
        for line in f:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != "assistant":
                continue
            timestamp = entry.get("timestamp")
            usage = entry.get("message", {}).get("usage")
            if not timestamp or not usage:
                continue
            if _local_date_of(timestamp) != target_date:
                continue
            total += (
                usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
    return total


def sum_usage_for_today(projects_dir=CLAUDE_PROJECTS_DIR, today=None):
    """Sum tokens from assistant entries whose own timestamp falls on `today`.

    Filters by each entry's actual timestamp rather than by when it was
    scanned, so a first-ever run doesn't misreport the entire historical
    backlog as "today". Only files modified today or later are opened in
    full, since a file untouched today can't contain any of today's entries.
    """
    today = today or date.today()
    total = 0
    for path in projects_dir.rglob("*.jsonl"):
        if datetime.fromtimestamp(path.stat().st_mtime).date() < today:
            continue
        total += _sum_usage_for_date_in_file(path, today)
    return total


def format_count(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
