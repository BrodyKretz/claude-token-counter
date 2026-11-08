import json
from datetime import date

from tools import TOOLS, combined_view, detect_tools, scan_tools, tool_view
from usage_stats import add_usage

PARTS = {"input": 0, "output": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0}


def parts(**kw):
    return {**PARTS, **kw}


def paths(tmp_path):
    return {
        "claude_code": tmp_path / "claude" / "projects",
        "codex": tmp_path / "codex" / "sessions",
        "opencode": tmp_path / "opencode.db",
    }


def test_tool_names():
    assert TOOLS == [("claude_code", "Claude Code"), ("codex", "Codex"), ("opencode", "opencode")]


def test_detect_only_existing(tmp_path):
    p = paths(tmp_path)
    p["claude_code"].mkdir(parents=True)
    p["opencode"].write_bytes(b"")

    assert detect_tools(p) == ["claude_code", "opencode"]


def test_claude_view_uses_existing_keys():
    daily = {}
    add_usage(daily, date(2026, 7, 29), "claude-opus-5-5", "~/p", parts(input=7))
    state = {"grand_total": 100, "daily": daily}

    view = tool_view(state, "claude_code")

    assert view == {"key": "claude_code", "name": "Claude Code", "daily": daily,
                    "grand_total": 100, "error": None}
    assert "sources" not in state


def test_combined_sums_tools_and_groups_by_model():
    claude_daily, opencode_daily = {}, {}
    add_usage(claude_daily, date(2026, 7, 29), "claude-opus-5-5", "~/p", parts(input=7))
    add_usage(opencode_daily, date(2026, 7, 29), "claude-opus-5-5", "~/p", parts(input=3))
    add_usage(opencode_daily, date(2026, 7, 29), "gemini-4-argon", "~/p", parts(output=5))
    state = {
        "grand_total": 100,
        "daily": claude_daily,
        "sources": {"opencode": {"daily": opencode_daily, "error": "boom"}},
    }

    view = combined_view(state, ["claude_code", "opencode"])

    assert view["key"] == "all" and view["name"] == "All tools"
    assert view["grand_total"] == 108
    models = view["daily"]["2026-07-29"]["models"]
    assert models["claude-opus-5-5"]["input"] == 10
    assert models["gemini-4-argon"]["output"] == 5
    assert view["error"] == "opencode: boom"


def test_scan_skips_disabled_tools(tmp_path):
    p = paths(tmp_path)
    project = p["claude_code"] / "proj"
    project.mkdir(parents=True)
    (project / "s.jsonl").write_text(json.dumps({
        "type": "assistant", "timestamp": "2026-07-29T12:00:00.000Z",
        "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": 9, "output_tokens": 1}},
    }) + "\n")
    sessions = p["codex"] / "2026"
    sessions.mkdir(parents=True)
    (sessions / "rollout.jsonl").write_text("\n".join(json.dumps(e) for e in [
        {"timestamp": "2026-07-29T12:00:00.000Z", "type": "turn_context", "payload": {"model": "gpt-x", "cwd": "/x"}},
        {"timestamp": "2026-07-29T12:00:00.000Z", "type": "token_usage_record",
         "payload": {"response_id": "r", "usage": {"input_tokens": 4, "output_tokens": 2}}},
    ]) + "\n")
    state = {"grand_total": 0, "file_offsets": {}, "daily": {}}

    scan_tools(state, ["codex"], p)

    assert state["grand_total"] == 0
    assert tool_view(state, "codex")["grand_total"] == 6

    scan_tools(state, ["claude_code", "codex"], p)

    assert state["grand_total"] == 10
    assert tool_view(state, "codex")["grand_total"] == 6
