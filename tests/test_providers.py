from datetime import date

from providers import PROVIDERS, provider_of, provider_view
from usage_stats import add_usage


def test_provider_names():
    assert PROVIDERS == [("openai", "OpenAI"), ("deepseek", "DeepSeek"), ("kimi", "Kimi")]


def test_openai_models():
    for model in ["gpt-5", "gpt-5.1-codex", "gpt-oss-120b", "o3", "o4-mini", "o1",
                  "codex-mini-latest", "chatgpt-4o-latest", "openai/gpt-5", "GPT-5"]:
        assert provider_of(model) == "openai", model


def test_deepseek_and_kimi_models():
    assert provider_of("deepseek-chat") == "deepseek"
    assert provider_of("deepseek/deepseek-r1") == "deepseek"
    assert provider_of("deepseek-v3.2-exp") == "deepseek"
    assert provider_of("kimi-k2-0905-preview") == "kimi"
    assert provider_of("moonshotai/kimi-k2") == "kimi"
    assert provider_of("moonshot-v1-8k") == "kimi"


def test_other_models_belong_to_none():
    for model in ["claude-opus-5-5", "gemini-4-argon", "unknown", "qwen3-coder", "olmo-2", "",
                  "grok-code-fast"]:
        assert provider_of(model) is None, model


def test_vendor_prefix_decides_unrecognised_names():
    assert provider_of("openai/some-new-model") == "openai"
    assert provider_of("moonshotai/k3") == "kimi"


def _state():
    claude, opencode, codex = {}, {}, {}
    add_usage(claude, date(2026, 11, 8), "claude-opus-5-5", "~/a", {"input": 100})
    add_usage(claude, date(2026, 11, 8), "deepseek-chat", "~/a", {"input": 7})
    add_usage(opencode, date(2026, 11, 8), "kimi-k2", "~/b", {"input": 5}, cost=0.01)
    add_usage(opencode, date(2026, 11, 8), "gpt-5", "~/b", {"input": 3}, cost=0.02)
    add_usage(codex, date(2026, 11, 7), "gpt-5-codex", "~/c", {"output": 11})
    return {
        "grand_total": 107, "daily": claude,
        "sources": {
            "opencode": {"daily": opencode},
            "codex": {"files": {"f": {"size": 1, "mtime": 1, "daily": codex}}},
        },
    }


def test_provider_view_collects_its_models_from_every_tool():
    view = provider_view(_state(), "openai")

    assert view["key"] == "openai"
    assert view["name"] == "OpenAI"
    assert view["grand_total"] == 14
    assert set(view["daily"]["2026-11-08"]["models"]) == {"gpt-5"}
    assert view["daily"]["2026-11-07"]["projects"] == {"~/c": 11}
    assert view["error"] is None


def test_provider_view_keeps_each_tools_costs_apart():
    view = provider_view(_state(), "kimi")

    assert view["grand_total"] == 5
    assert [v["daily"]["2026-11-08"]["recorded_cost"] for v in view["views"]] == [{"kimi-k2": 0.01}]


def test_provider_view_from_claude_code_routing():
    view = provider_view(_state(), "deepseek")

    assert view["grand_total"] == 7
    assert view["daily"]["2026-11-08"]["projects"] == {"~/a": 7}


def test_provider_view_with_no_data():
    view = provider_view({}, "kimi")

    assert view["daily"] == {}
    assert view["grand_total"] == 0
