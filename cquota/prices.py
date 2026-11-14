#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API-equivalent cost of token usage, from the list prices in prices.json."""
import functools
import json
import os

PRICES_PATH = os.path.join(os.path.dirname(os.path.realpath(__file__)), "prices.json")
TOKENS_PER_PRICE_UNIT = 1_000_000
# Ledger column -> price key
PRICED_COLUMNS = {
    "input_tokens":          "input",
    "output_tokens":         "output",
    "cache_write_5m_tokens": "cache_write_5m",
    "cache_write_1h_tokens": "cache_write_1h",
    "cache_read_tokens":     "cache_read",
}


@functools.lru_cache(maxsize=1)
def load_prices() -> dict:
    with open(PRICES_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)["models"]


def get_cost(model: str, usage: dict) -> float | None:
    """Cost in USD of the usage of one model, or None when the model has no price."""
    price = load_prices().get(model)
    if price is None:
        return None
    amount = 0.0
    for column, price_key in PRICED_COLUMNS.items():
        amount += usage[column] * price[price_key]
    return amount / TOKENS_PER_PRICE_UNIT


def main():
    pass


if __name__ == "__main__":
    main()
