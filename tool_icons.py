"""Menu bar icons for each AI tool.

Icons are taken at runtime from the tool's own app or editor extension already
installed on this Mac; no logo files ship with Claude Tracker. If a tool's
icon can't be found, the menu bar keeps the coin.
"""

import re
from pathlib import Path

# Per tool: app bundle ids to try, then (extension folder prefix, icon file
# inside it, draw as a template image that follows the menu bar's colors).
SOURCES = {
    "claude_code": {
        "apps": ["com.anthropic.claudefordesktop"],
        "extension": ("anthropic.claude-code-", "resources/claude-logo.svg", False),
    },
    "codex": {
        "apps": ["com.openai.codex", "com.openai.chat"],
        "extension": ("openai.chatgpt-", "resources/blossom-black.svg", True),
    },
    "opencode": {
        "apps": ["ai.opencode.desktop"],
        "extension": None,
    },
}

EXTENSION_DIRS = [
    Path.home() / ".vscode" / "extensions",
    Path.home() / ".cursor" / "extensions",
    Path.home() / ".windsurf" / "extensions",
]

MENU_BAR_ICON_SIZE = 16


def _version_key(folder_name, prefix):
    numbers = re.findall(r"\d+", folder_name[len(prefix):].split("-")[0])
    return [int(n) for n in numbers]


def icon_source(tool, app_path_for_bundle, extension_dirs):
    """Where to get `tool`'s icon: {"path", "app", "template"}, or None.
    `app_path_for_bundle(bundle_id)` returns an installed app's path or None."""
    source = SOURCES.get(tool)
    if not source:
        return None
    for bundle_id in source["apps"]:
        path = app_path_for_bundle(bundle_id)
        if path:
            return {"path": str(path), "app": True, "template": False}
    if source["extension"]:
        prefix, relative, template = source["extension"]
        candidates = [
            folder / relative
            for root in extension_dirs if Path(root).is_dir()
            for folder in Path(root).iterdir()
            if folder.name.startswith(prefix) and (folder / relative).exists()
        ]
        if candidates:
            newest = max(candidates, key=lambda p: _version_key(p.parent.parent.name, prefix))
            return {"path": str(newest), "app": False, "template": template}
    return None


_cache = {}


def menu_bar_image(tool):
    """An NSImage sized for the menu bar, or None to keep the coin."""
    if tool in _cache:
        return _cache[tool]
    from AppKit import NSImage, NSWorkspace

    workspace = NSWorkspace.sharedWorkspace()

    def app_path(bundle_id):
        url = workspace.URLForApplicationWithBundleIdentifier_(bundle_id)
        return url.path() if url else None

    source = icon_source(tool, app_path, EXTENSION_DIRS)
    image = None
    if source:
        if source["app"]:
            image = workspace.iconForFile_(source["path"])
        else:
            image = NSImage.alloc().initWithContentsOfFile_(source["path"])
        if image is not None:
            image = image.copy()
            image.setSize_((MENU_BAR_ICON_SIZE, MENU_BAR_ICON_SIZE))
            image.setTemplate_(source["template"])
    _cache[tool] = image
    return image
