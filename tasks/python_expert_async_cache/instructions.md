# Task: Implement cancellable async resource cache

`AsyncResourceCache` must provide coalesced asynchronous reads with TTL-based eviction and graceful shutdown. Current implementation is naive and fails to coordinate concurrent callers or handle cancellation correctly. Implement the following:

- Concurrent calls to `get(key, loader)` while a loader is pending must await the same future (loader invoked once). If the loader raises, the error should propagate to all callers and the cache entry must not be stored.
- Per-entry TTL: entries older than `ttl_seconds` must be refreshed on subsequent `get` calls.
- `invalidate(key)` cancels any pending load for that key and removes cached value.
- `close()` waits for pending loaders to finish (or cancel them if `cancel_pending=True` parameter is passed) and prevents new `get` calls.
- Implementation must be asyncio-friendly (no blocking locks) and free of race conditions.

Use `asyncio.Lock` / `asyncio.Event` primitives as needed. Update the public API only as described (allow `close(cancel_pending: bool = False)`).

## Testing
```
pytest -q
```
