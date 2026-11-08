"""The AI coding tools the app can track, and the "views" the panel shows.

A view is {"key", "name", "daily", "grand_total", "error"}: one tool's
per-day buckets and lifetime total, or every enabled tool merged ("all").

Claude Code's data stays in the state keys it has always used (grand_total,
file_offsets, daily); other tools live under state["sources"][tool].
"""

from codex_source import CODEX_SESSIONS_DIR, codex_daily, codex_total, scan_codex
from opencode_source import OPENCODE_DB, opencode_daily, opencode_total, scan_opencode
from token_math import CLAUDE_PROJECTS_DIR, refresh_grand_total
from usage_stats import merge_daily

TOOLS = [("claude_code", "Claude Code"), ("codex", "Codex"), ("opencode", "opencode")]
TOOL_NAMES = dict(TOOLS)

DEFAULT_PATHS = {
    "claude_code": CLAUDE_PROJECTS_DIR,
    "codex": CODEX_SESSIONS_DIR,
    "opencode": OPENCODE_DB,
}


def detect_tools(paths=None):
    """Keys of the tools whose data exists on this Mac, in TOOLS order."""
    paths = paths or DEFAULT_PATHS
    return [key for key, _ in TOOLS if paths[key].exists()]


def scan_tools(state, enabled, paths=None):
    """Read new usage for each enabled tool into `state`."""
    paths = paths or DEFAULT_PATHS
    sources = state.setdefault("sources", {})
    if "claude_code" in enabled:
        refresh_grand_total(state, paths["claude_code"])
    if "codex" in enabled:
        scan_codex(sources.setdefault("codex", {}), paths["codex"])
    if "opencode" in enabled:
        scan_opencode(sources.setdefault("opencode", {}), paths["opencode"])


def tool_view(state, key):
    if key == "claude_code":
        daily, total, error = state.get("daily", {}), state.get("grand_total", 0), None
    else:
        source = state.get("sources", {}).get(key, {})
        if key == "codex":
            daily, total = codex_daily(source), codex_total(source)
        else:
            daily, total = opencode_daily(source), opencode_total(source)
        error = source.get("error")
    return {"key": key, "name": TOOL_NAMES[key], "daily": daily, "grand_total": total, "error": error}


def combined_view(state, enabled):
    views = [tool_view(state, key) for key, _ in TOOLS if key in enabled]
    errors = [f"{v['name']}: {v['error']}" for v in views if v["error"]]
    return {
        "key": "all",
        "name": "All tools",
        "daily": merge_daily([v["daily"] for v in views]),
        "grand_total": sum(v["grand_total"] for v in views),
        "error": errors[0] if errors else None,
    }
