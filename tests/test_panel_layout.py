from panel_view import SCREEN_MARGIN, panel_height


def test_short_content_uses_its_own_height():
    assert panel_height(500, screen_height=800) == 500


def test_tall_content_is_capped_to_the_screen():
    assert panel_height(900, screen_height=800) == 800 - SCREEN_MARGIN


def test_tool_switcher_is_a_dropdown():
    from AppKit import NSPopUpButton, NSSegmentedControl

    from panel_view import Panel

    tab = {"key": "overview", "title": "Overview", "short": "Home", "icon": "square.grid.2x2",
           "cards": [{"title": None, "items": [("note", "hi")]}]}
    settings = {**tab, "key": "settings", "title": "Settings"}
    panel = Panel(on_action=lambda action, value: None)

    panel.render([tab], settings, "footer", False,
                 tool_choices=[("claude_code", "Claude Code"), ("codex", "Codex"), ("opencode", "opencode")],
                 selected_tool="codex")

    popups = [v for v in panel.root.subviews() if isinstance(v, NSPopUpButton)]
    assert len(popups) == 1
    assert list(popups[0].itemTitles()) == ["Claude Code", "Codex", "opencode"]
    assert popups[0].indexOfSelectedItem() == 1
    assert not [v for v in panel.root.subviews() if isinstance(v, NSSegmentedControl)]
