"""Approximate USD prices per million tokens (input, output), for cost estimates only."""

from __future__ import annotations

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """USD cost, or None if the model's price is unknown."""
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return None
    return input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]


def estimate_tokens(text: str) -> int:
    """Rough token count (about 4 characters per token for English prose and JSON)."""
    return max(1, len(text) // 4)
