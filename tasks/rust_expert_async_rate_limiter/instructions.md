# Task: Implement asynchronous token bucket rate limiter

`RateLimiter::new(max_permits, interval)` should behave like a token bucket replenished every `interval`. Current implementation is a thin semaphore wrapper with no replenishment or cancellation support. Implement the following:

- `acquire()` waits until a token is available. Tokens replenish every `interval` while the limiter is alive.
- Burst capacity equals `max_permits`; callers beyond capacity wait for replenishment.
- Dropping the limiter cancels pending waiters immediately.
- `release()` should return a token immediately without waiting for the interval (for early completion).
- Implementation must be fair (FIFO ordering) and race-free under Tokio’s multi-threaded runtime.

You may create background tasks, but ensure they terminate promptly when the limiter is dropped.

## Testing
```
cargo test
```
