from tool_icons import icon_source


def apps(mapping):
    return lambda bundle_id: mapping.get(bundle_id)


def make_extension(root, folder, rel):
    path = root / folder / rel
    path.parent.mkdir(parents=True)
    path.write_text("<svg/>")
    return path


def test_claude_uses_the_claude_app_icon():
    found = icon_source("claude_code", apps({"com.anthropic.claudefordesktop": "/Applications/Claude.app"}), [])
    assert found == {"path": "/Applications/Claude.app", "app": True, "template": False}


def test_opencode_uses_the_opencode_app_icon():
    found = icon_source("opencode", apps({"ai.opencode.desktop": "/Applications/OpenCode.app"}), [])
    assert found == {"path": "/Applications/OpenCode.app", "app": True, "template": False}


def test_codex_falls_back_to_the_editor_extension_icon(tmp_path):
    svg = make_extension(tmp_path, "openai.chatgpt-26.1021.22027-darwin-arm64", "resources/blossom-black.svg")

    found = icon_source("codex", apps({}), [tmp_path / "missing", tmp_path])

    assert found == {"path": str(svg), "app": False, "template": True}


def test_newest_extension_version_wins(tmp_path):
    make_extension(tmp_path, "openai.chatgpt-26.900.1-darwin-arm64", "resources/blossom-black.svg")
    newer = make_extension(tmp_path, "openai.chatgpt-26.1021.22027-darwin-arm64", "resources/blossom-black.svg")

    assert icon_source("codex", apps({}), [tmp_path])["path"] == str(newer)


def test_app_is_preferred_over_extension(tmp_path):
    make_extension(tmp_path, "openai.chatgpt-26.1-darwin-arm64", "resources/blossom-black.svg")

    found = icon_source("codex", apps({"com.openai.codex": "/Applications/Codex.app"}), [tmp_path])

    assert found["path"] == "/Applications/Codex.app"


def test_nothing_found_returns_none(tmp_path):
    assert icon_source("opencode", apps({}), [tmp_path]) is None
