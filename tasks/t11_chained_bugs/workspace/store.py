class Store:
    def __init__(self):
        self._items: dict[str, dict] = {}

    def add_item(self, name: str, price: float, qty: int) -> None:
        if name in self._items:
            # BUG 1: overwrites quantity instead of accumulating.
            self._items[name]["qty"] = qty
        else:
            self._items[name] = {"price": price, "qty": qty}

    def remove_item(self, name: str, qty: int) -> None:
        item = self._items[name]
        if qty > item["qty"]:
            raise ValueError("not enough stock")
        item["qty"] -= qty
        # BUG 2: item should be deleted when qty reaches 0, but isn't.

    def items(self) -> dict[str, dict]:
        return self._items
