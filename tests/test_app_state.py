import copy

from app import init_tool_state

EXISTING = {
    "grand_total": 3_600_000_000,
    "file_offsets": {"/Users/me/.claude/projects/p/s.jsonl": 1234},
    "daily": {"2026-11-07": {"models": {}, "projects": {}}},
    "daily_backfilled": True,
    "first_seen_at": "2026-11-07",
    "title_mode": "today",
    "menu_bar_font_size": 11,
    "leaderboard_enabled": True,
    "leaderboard_view": "day",
    "panel_tab": "cost",
    "scan_interval_seconds": 60,
    "start_at_login": False,
}


def test_existing_install_keeps_preferences():
    state = copy.deepcopy(EXISTING)

    init_tool_state(state, fresh_install=False)

    for key, value in EXISTING.items():
        assert state[key] == value, key
    assert state["enabled_tools"] == ["claude_code"]
    assert state["combine_tools"] is False
    assert state["selected_tool"] == "claude_code"
    assert state["onboarding_done"] is True


def test_fresh_install_starts_with_no_tools():
    state = {}

    init_tool_state(state, fresh_install=True)

    assert state["enabled_tools"] == []
    assert state["onboarding_done"] is False


def test_init_is_idempotent_and_keeps_choices():
    state = {"enabled_tools": ["codex"], "combine_tools": True, "selected_tool": "codex",
             "onboarding_done": True}

    init_tool_state(state, fresh_install=False)

    assert state == {"enabled_tools": ["codex"], "combine_tools": True, "selected_tool": "codex",
                     "onboarding_done": True}


def test_menu_bar_label_uses_tool_icon_or_coin():
    from app import menu_bar_label

    assert menu_bar_label("all", "3.8B", has_icon=True) == ("🪙 3.8B", False)
    assert menu_bar_label("codex", "39.4M", has_icon=True) == (" 39.4M", True)
    assert menu_bar_label("codex", "39.4M", has_icon=False) == ("🪙 39.4M", False)
    assert menu_bar_label("codex", None, has_icon=True) == ("", True)  # icon-only mode
    assert menu_bar_label("all", None, has_icon=False) == ("🪙", False)
