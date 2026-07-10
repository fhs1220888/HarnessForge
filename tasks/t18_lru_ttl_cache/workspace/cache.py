from typing import Callable


class TTLCache:
    """See SPEC.md."""

    def __init__(self, capacity: int, ttl: float, clock: Callable[[], float]):
        raise NotImplementedError
