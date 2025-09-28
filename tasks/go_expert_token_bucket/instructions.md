# Go Expert Task: Token Bucket Rate Limiter

Implement a production-grade token bucket in `workspace/tokenbucket.go`.

### API

```go
package tokenbucket

type TokenBucket struct { /* private fields */ }

func NewTokenBucket(capacity int, refillRate float64, start time.Time) *TokenBucket
func (b *TokenBucket) Allow(at time.Time, tokens int) bool
```

- `capacity` is the maximum whole tokens the bucket can store. `refillRate` is the number of tokens regenerated per second (can be fractional).
- `NewTokenBucket` should initialise the bucket at `start` time holding a full capacity of tokens.
- `Allow` attempts to spend `tokens` at timestamp `at`. It must:
  - Refill the bucket according to the elapsed time since the last event.
  - Clamp the stored tokens to `capacity`.
  - Reject non-positive `tokens` arguments.
  - Return `true` and deduct the tokens when there is sufficient balance, otherwise return `false` without mutating the balance.
- Make the implementation safe for concurrent callers. Use standard library primitives only.
- Support high resolution timestamps (nanosecond precision) without accumulating significant floating point drift.

The provided tests cover burst consumption, partial refills, concurrency against mixed workloads, and validation of edge cases.
