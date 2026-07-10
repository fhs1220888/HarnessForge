# TTLCache(capacity: int, ttl: float, clock: Callable[[], float])

An LRU cache where entries also expire after `ttl` seconds.

- `clock` is injected (e.g. `time.monotonic` in production, a fake in tests).
- `put(key, value)`: insert/overwrite. Overwriting refreshes both the entry's
  timestamp and its recency. If inserting a NEW key when the cache is full,
  first drop all expired entries; if still full, evict the least-recently-used
  entry.
- `get(key)`: return the value and refresh recency (NOT the timestamp).
  Return None if the key is absent or expired. An expired entry is removed
  on access.
- `__len__`: number of NON-expired entries (expired ones must not be counted,
  even if not yet removed).
- An entry is expired when `clock() - inserted_at >= ttl`.
