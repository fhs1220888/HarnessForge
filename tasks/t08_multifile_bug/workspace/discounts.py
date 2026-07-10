# Discount rates by customer tier.
RATES = {
    "standard": 0.0,
    "silver": 0.05,
    "gold": 0.10,
}


def discount_rate(tier: str) -> float:
    # BUG: unknown tiers silently get gold-level discount.
    return RATES.get(tier, 0.10)
