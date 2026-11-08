"""Codex usage, read from the session logs Codex writes on this Mac.

Codex keeps one JSONL "rollout" file per session under ~/.codex/sessions.
Only token counts, model, timestamp and the session's folder are read;
prompts and code in the same files are skipped.

Each file is re-read whole when it changes and its contribution replaces the
previous one, so files Codex rewrites or migrates can't be counted twice.
Files that disappear keep their last contribution, so lifetime totals
survive Codex pruning old sessions.
"""

import json
from pathlib import Path

from usage_stats import (
    SourceFormatError,
    _local_date_of,
    add_usage,
    merge_daily,
    project_label,
)

CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"

KNOWN_TYPES = {"session_meta", "turn_context", "event_msg", "response_item", "token_usage_record"}
USAGE_KEYS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")


def _parts(usage):
    """Codex usage -> the app's categories. Codex's input count already
    includes cached tokens, so they're split out here."""
    cached = usage.get("cached_input_tokens", 0) or 0
    return {
        "input": max((usage.get("input_tokens", 0) or 0) - cached, 0),
        "output": usage.get("output_tokens", 0) or 0,
        "cache_write_5m": usage.get("cache_write_input_tokens", 0) or 0,
        "cache_write_1h": 0,
        "cache_read": cached,
    }


def _complete_lines(path):
    """Parsed JSON objects for each newline-terminated line. A last line
    still being written (no newline yet) is left for the next scan."""
    with open(path, "rb") as f:
        data = f.read()
    for line in data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            yield entry


def read_codex_file(path):
    """This file's per-day buckets. Counts per-response usage records
    (de-duplicated by response id); files without any fall back to the growth
    of Codex's running total, ignoring repeats."""
    entries = list(_complete_lines(path))
    if entries and not any(e.get("type") in KNOWN_TYPES for e in entries):
        raise SourceFormatError(f"{Path(path).name} doesn't look like a Codex session log")

    has_records = any(e.get("type") == "token_usage_record" for e in entries)
    daily = {}
    model = "unknown"
    cwd = None
    seen_responses = set()
    previous_total = None

    for entry in entries:
        kind = entry.get("type")
        payload = entry.get("payload") or {}
        if kind in ("session_meta", "turn_context"):
            cwd = payload.get("cwd") or cwd
            model = payload.get("model") or model
            continue
        timestamp = entry.get("timestamp")
        if not timestamp:
            continue

        if has_records and kind == "token_usage_record":
            response_id = payload.get("response_id")
            if response_id in seen_responses:
                continue
            seen_responses.add(response_id)
            parts = _parts(payload.get("usage") or {})
        elif not has_records and kind == "event_msg" and payload.get("type") == "token_count":
            total = (payload.get("info") or {}).get("total_token_usage")
            if not total or total == previous_total:
                continue
            before = previous_total or {}
            growth = {k: max((total.get(k, 0) or 0) - (before.get(k, 0) or 0), 0) for k in USAGE_KEYS}
            previous_total = total
            parts = _parts(growth)
        else:
            continue

        if sum(parts.values()):
            add_usage(daily, _local_date_of(timestamp), model, project_label(cwd), parts)
    return daily


def scan_codex(source_state, sessions_dir=CODEX_SESSIONS_DIR):
    """Update `source_state` from Codex's session logs. Sets
    source_state["error"] to a message if a file couldn't be read, else None."""
    files = source_state.setdefault("files", {})
    errors = []
    for path in sorted(Path(sessions_dir).rglob("*.jsonl")):
        key = str(path)
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        saved = files.get(key)
        if saved and saved["size"] == stat.st_size and saved["mtime"] == stat.st_mtime:
            continue
        try:
            daily = read_codex_file(path)
        except (SourceFormatError, OSError) as e:
            errors.append(str(e))
            continue
        files[key] = {"size": stat.st_size, "mtime": stat.st_mtime, "daily": daily}
    source_state["error"] = errors[0] if errors else None
    return source_state


def codex_daily(source_state):
    return merge_daily([f["daily"] for f in source_state.get("files", {}).values()])


def codex_total(source_state):
    return sum(
        sum(parts.values())
        for f in source_state.get("files", {}).values()
        for bucket in f["daily"].values()
        for parts in bucket["models"].values()
    )
