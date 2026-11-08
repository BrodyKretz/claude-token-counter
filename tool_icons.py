"""Menu bar icons for each AI tool.

Icons are taken at runtime from the tool's own app or editor extension already
installed on this Mac; no logo files ship with Claude Tracker. If a tool's
icon can't be found, the menu bar keeps the coin; a provider without one gets
a drawn monogram instead, so it can still be told apart.
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
    "openai": {
        "apps": ["com.openai.chat", "com.openai.codex"],
        "extension": ("openai.chatgpt-", "resources/blossom-black.svg", True),
    },
    "deepseek": {"apps": [], "app_names": ["DeepSeek.app"], "extension": None},
    "kimi": {"apps": [], "app_names": ["Kimi.app"], "extension": None},
}

APP_DIRS = [Path("/Applications"), Path.home() / "Applications"]

MONOGRAMS = {"openai": "AI", "deepseek": "DS", "kimi": "K"}

EXTENSION_DIRS = [
    Path.home() / ".vscode" / "extensions",
    Path.home() / ".cursor" / "extensions",
    Path.home() / ".windsurf" / "extensions",
]

MENU_BAR_ICON_SIZE = 16


def _version_key(folder_name, prefix):
    numbers = re.findall(r"\d+", folder_name[len(prefix):].split("-")[0])
    return [int(n) for n in numbers]


def icon_source(tool, app_path_for_bundle, extension_dirs, app_dirs=()):
    """Where to get `tool`'s icon: {"path", "app", "template"}, or None.
    `app_path_for_bundle(bundle_id)` returns an installed app's path or None;
    apps without a known bundle id are looked up by name in `app_dirs`."""
    source = SOURCES.get(tool)
    if not source:
        return None
    for bundle_id in source["apps"]:
        path = app_path_for_bundle(bundle_id)
        if path:
            return {"path": str(path), "app": True, "template": False}
    for name in source.get("app_names", []):
        for folder in app_dirs:
            if (Path(folder) / name).is_dir():
                return {"path": str(Path(folder) / name), "app": True, "template": False}
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

    source = icon_source(tool, app_path, EXTENSION_DIRS, APP_DIRS)
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
    if image is None and tool in MONOGRAMS:
        image = _monogram_image(MONOGRAMS[tool])
    _cache[tool] = image
    return image


def _monogram_image(text):
    """Letters in a rounded square, drawn as a template image so it follows
    the menu bar's colours."""
    from AppKit import (
        NSBezierPath,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSImage,
        NSMakeRect,
        NSString,
    )

    size = MENU_BAR_ICON_SIZE
    image = NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()
    NSColor.blackColor().set()
    frame = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(1, 1, size - 2, size - 2), 3.5, 3.5
    )
    frame.setLineWidth_(1.3)
    frame.stroke()
    font = NSFont.systemFontOfSize_weight_(10 if len(text) == 1 else 7.5, 0.4)
    attrs = {NSFontAttributeName: font, NSForegroundColorAttributeName: NSColor.blackColor()}
    label = NSString.stringWithString_(text)
    width, height = label.sizeWithAttributes_(attrs)
    label.drawAtPoint_withAttributes_(((size - width) / 2, (size - height) / 2), attrs)
    image.unlockFocus()
    image.setTemplate_(True)
    return image
