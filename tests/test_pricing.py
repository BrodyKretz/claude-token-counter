import pytest

from pricing import estimate_cost, format_dollars, price_for


def test_longest_prefix_wins():
    assert price_for("claude-opus-5-5") == (4.00, 20.00, 0.20)
    assert price_for("claude-opus-5") == (5.00, 25.00, 0.50)
    assert price_for("claude-haiku-4-5-20251001") == (1.00, 5.00, 0.10)


def test_unknown_model_has_no_price():
    assert price_for("<synthetic>") is None
    assert price_for("claude-opus-55") is None


def test_estimate_cost_all_categories():
    models = {
        "claude-opus-5-5": {
            "input": 1_000_000,
            "output": 1_000_000,
            "cache_write_5m": 1_000_000,
            "cache_write_1h": 1_000_000,
            "cache_read": 1_000_000,
        }
    }
    dollars, unpriced = estimate_cost(models)
    # 4 + 20 + 4*1.25 + 4*2 + 0.20
    assert dollars == pytest.approx(37.20)
    assert unpriced == 0


def test_estimate_cost_reports_unpriced_tokens():
    dollars, unpriced = estimate_cost({"mystery": {"input": 7}})
    assert dollars == 0
    assert unpriced == 7


def test_format_dollars():
    assert format_dollars(3.456) == "$3.46"
    assert format_dollars(12345.6) == "$12,346"


def test_estimate_cost_uses_recorded_cost():
    models = {
        "gemini-4-argon": {"input": 1_000_000},
        "mystery": {"input": 5},
        "claude-opus-5-5": {"input": 1_000_000},
    }

    dollars, unpriced = estimate_cost(models, recorded={"gemini-4-argon": 0.75})

    assert dollars == pytest.approx(4.75)
    assert unpriced == 5
