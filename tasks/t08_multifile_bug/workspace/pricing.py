from discounts import discount_rate


def final_price(base: float, tier: str) -> float:
    # BUG: discount applied twice.
    once = base * (1 - discount_rate(tier))
    return once * (1 - discount_rate(tier))
