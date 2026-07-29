import json
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


def format_count(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
