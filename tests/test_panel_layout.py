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
    panel = Panel(on_action=lambda action, value: None)

    panel.render([tab], "footer", False,
                 tool_choices=[("claude_code", "Claude Code"), ("codex", "Codex"), ("opencode", "opencode")],
                 selected_tool="codex")

    popups = [v for v in panel.root.subviews() if isinstance(v, NSPopUpButton)]
    assert len(popups) == 1
    assert list(popups[0].itemTitles()) == ["Claude Code", "Codex", "opencode"]
    assert popups[0].indexOfSelectedItem() == 1
    assert not [v for v in panel.root.subviews() if isinstance(v, NSSegmentedControl)]


TAB = {"key": "overview", "title": "Overview", "short": "Home", "icon": "square.grid.2x2",
       "cards": [{"title": None, "items": [("note", "hi")]}]}


def test_settings_button_asks_the_app_to_open_the_settings_window():
    from AppKit import NSButton

    from panel_view import Panel

    calls = []
    panel = Panel(on_action=lambda action, value: calls.append((action, value)))
    panel.render([TAB], "footer", False)

    button = next(v for v in panel.root.subviews()
                  if isinstance(v, NSButton) and v.toolTip() == "Settings")
    panel._fire(button.tag(), None)

    assert calls == [("open_settings", None)]
    assert panel.selected == "overview"  # the popover itself doesn't change


def test_popover_no_longer_shows_settings_inline():
    from panel_view import Panel

    panel = Panel(on_action=lambda action, value: None, selected_tab="settings")
    panel.render([TAB], "footer", False)

    assert panel.selected == "overview"


def test_settings_window_draws_the_settings_cards():
    from AppKit import NSSwitch, NSTextField

    from panel_view import SettingsWindow

    calls = []
    settings = {"key": "settings", "title": "Settings", "short": "Settings", "icon": "gear",
                "cards": [{"title": "AI tools", "items": [("switch", "Codex", True, "tool:codex")]}]}
    window = SettingsWindow(on_action=lambda action, value: calls.append((action, value)))

    window.render(settings)

    assert window.window.title() == "Claude Tracker Settings"
    labels = [v.stringValue() for v in window.root.subviews() if isinstance(v, NSTextField)]
    assert "AI tools" in labels and "Codex" in labels
    switch = next(v for v in window.root.subviews() if isinstance(v, NSSwitch))
    window._fire(switch.tag(), False)
    assert calls == [("tool:codex", False)]
