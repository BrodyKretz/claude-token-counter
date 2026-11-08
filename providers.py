"""AI providers (the companies whose models ran), as views across every tool.

A provider view has the same shape as a tool view (see tools.py): that
provider's models, filtered out of each tool's per-day buckets. The numbers
are the tools' own counts, so no account or API key is needed for them.
"""

import re

from tools import TOOLS, tool_view
from usage_stats import filter_daily, merge_daily

PROVIDERS = [("openai", "OpenAI"), ("deepseek", "DeepSeek"), ("kimi", "Kimi")]
PROVIDER_NAMES = dict(PROVIDERS)

# A "vendor/" prefix some tools put before the model name (e.g. OpenRouter's
# "moonshotai/kimi-k2").
VENDORS = {
    "openai": "openai",
    "deepseek": "deepseek",
    "deepseek-ai": "deepseek",
    "moonshotai": "kimi",
    "moonshot": "kimi",
}

OPENAI_MODEL = re.compile(r"^(gpt|chatgpt|codex)(-|$)|^o\d+(-|$)")


def provider_of(model):
    """The provider key whose model this is, or None."""
    vendor, _, name = (model or "").lower().rpartition("/")
    if OPENAI_MODEL.match(name):
        return "openai"
    if "deepseek" in name:
        return "deepseek"
    if "kimi" in name or "moonshot" in name:
        return "kimi"
    return VENDORS.get(vendor)


def tools_to_scan(state, detected):
    """Enabled tools, plus every tool on this Mac while any provider is on
    (a provider's models can run in any of them)."""
    wanted = set(state.get("enabled_tools", []))
    if state.get("enabled_providers"):
        wanted |= set(detected)
    return [key for key, _ in TOOLS if key in wanted]


def provider_view(state, key):
    """Usage of `key`'s models through every tool with data on this Mac."""
    views = []
    errors = []
    for tool, _ in TOOLS:
        view = tool_view(state, tool)
        if view["error"]:
            errors.append(f"{view['name']}: {view['error']}")
        daily = filter_daily(view["daily"], lambda m: provider_of(m) == key)
        if daily:
            views.append({**view, "daily": daily, "grand_total": _total(daily)})
    daily = merge_daily([v["daily"] for v in views])
    return {
        "key": key,
        "name": PROVIDER_NAMES[key],
        "daily": daily,
        "grand_total": _total(daily),
        "error": errors[0] if errors else None,
        "views": views,  # per tool, so each tool's recorded costs stay its own
    }


def _total(daily):
    return sum(
        sum(parts.values()) for bucket in daily.values() for parts in bucket["models"].values()
    )
