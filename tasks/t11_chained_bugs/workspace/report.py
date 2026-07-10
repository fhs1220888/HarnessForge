from store import Store


def total_value(store: Store) -> float:
    total = 0.0
    for item in store.items().values():
        # BUG 3: multiplies price by itself instead of by quantity.
        total += item["price"] * item["price"]
    return total


def low_stock(store: Store, threshold: int = 3) -> list[str]:
    return sorted(n for n, i in store.items().items() if i["qty"] < threshold)
