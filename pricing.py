"""Estimated pay-as-you-go API cost of Claude Code usage.

This is for fun/context only: a Claude Pro or Max subscription is flat-rate,
so none of this is actually billed. Prices are USD per million tokens from
Anthropic's public API pricing and will drift over time.
"""

# prefix -> (input, output, cache_read) USD per 1M tokens.
# Longest matching prefix wins, so "claude-opus-5-5" beats "claude-opus-5".
PRICES = {
    "claude-fable-5-1": (10.00, 50.00, 0.25),
    "claude-fable-5": (10.00, 50.00, 1.00),
    "claude-mythos-5-1": (10.00, 50.00, 0.25),
    "claude-mythos-5": (10.00, 50.00, 1.00),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
    "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
    "claude-opus-4-5": (5.00, 25.00, 0.50),
    "claude-opus-4-1": (15.00, 75.00, 1.50),
    "claude-opus-4": (15.00, 75.00, 1.50),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-sonnet-4": (3.00, 15.00, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
}

# Cache writes are billed as a multiple of the model's input price.
CACHE_WRITE_5M_MULTIPLIER = 1.25
CACHE_WRITE_1H_MULTIPLIER = 2.0


def price_for(model):
    """(input, output, cache_read) per 1M tokens, or None if unknown."""
    matches = [p for p in PRICES if model == p or model.startswith(p + "-")]
    if not matches:
        return None
    return PRICES[max(matches, key=len)]


def estimate_cost(models, recorded=None):
    """Estimate USD for {model: {category: tokens}}.

    `recorded` is {model: dollars} a tool recorded itself (opencode does);
    those models use that amount instead of the price table.
    Returns (dollars, unpriced_tokens): tokens from models with no known
    price are left out of the dollar figure and counted separately.
    """
    recorded = recorded or {}
    dollars = 0.0
    unpriced = 0
    for model, parts in models.items():
        if model in recorded:
            dollars += recorded[model]
            continue
        price = price_for(model)
        if price is None:
            unpriced += sum(parts.values())
            continue
        input_price, output_price, cache_read_price = price
        dollars += (
            parts.get("input", 0) * input_price
            + parts.get("output", 0) * output_price
            + parts.get("cache_write_5m", 0) * input_price * CACHE_WRITE_5M_MULTIPLIER
            + parts.get("cache_write_1h", 0) * input_price * CACHE_WRITE_1H_MULTIPLIER
            + parts.get("cache_read", 0) * cache_read_price
        ) / 1_000_000
    return dollars, unpriced


def format_dollars(amount):
    if amount >= 1000:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"
