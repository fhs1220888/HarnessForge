from cache import TTLCache


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make(capacity=2, ttl=10.0):
    clock = FakeClock()
    return TTLCache(capacity, ttl, clock), clock


def test_basic_put_get():
    c, _ = make()
    c.put("a", 1)
    assert c.get("a") == 1
    assert c.get("missing") is None


def test_lru_eviction_order():
    c, _ = make(capacity=2)
    c.put("a", 1)
    c.put("b", 2)
    c.get("a")            # refresh a's recency -> b is now LRU
    c.put("c", 3)
    assert c.get("b") is None
    assert c.get("a") == 1 and c.get("c") == 3


def test_ttl_expiry():
    c, clock = make(ttl=10.0)
    c.put("a", 1)
    clock.advance(10.0)
    assert c.get("a") is None


def test_get_does_not_refresh_ttl():
    c, clock = make(ttl=10.0)
    c.put("a", 1)
    clock.advance(6.0)
    assert c.get("a") == 1      # refreshes recency, not timestamp
    clock.advance(5.0)
    assert c.get("a") is None   # 11s since insert -> expired


def test_overwrite_refreshes_ttl():
    c, clock = make(ttl=10.0)
    c.put("a", 1)
    clock.advance(6.0)
    c.put("a", 2)
    clock.advance(6.0)
    assert c.get("a") == 2      # only 6s since overwrite


def test_expired_dropped_before_lru_eviction():
    c, clock = make(capacity=2, ttl=10.0)
    c.put("a", 1)
    clock.advance(11.0)         # a expires
    c.put("b", 2)
    c.put("c", 3)               # cache full, but a is expired -> drop a, keep b
    assert c.get("b") == 2 and c.get("c") == 3


def test_len_ignores_expired():
    c, clock = make(capacity=5, ttl=10.0)
    c.put("a", 1)
    c.put("b", 2)
    clock.advance(11.0)
    c.put("c", 3)
    assert len(c) == 1
