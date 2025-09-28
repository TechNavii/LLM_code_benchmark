# Go Expert Task: Concurrent LRU Cache

Implement an efficient, goroutine-safe LRU cache in `workspace/cache.go`.

### API

```go
package cache

type Cache struct { /* private fields */ }

func New(capacity int) *Cache
func (c *Cache) Get(key string) (value any, ok bool)
func (c *Cache) Set(key string, value any)
func (c *Cache) Len() int
```

Requirements:

- The cache must hold at most `capacity` entries. Inserting when full must evict the **least recently used** entry (ties broken by the oldest access).
- `Get` promotes the entry to most-recently used order.
- `Set` should update an existing entry without changing the size; inserting new data should respect eviction semantics.
- All exported methods must be safe for concurrent use by multiple goroutines.
- Eviction should run in constant time. Avoid rebuilding slices or scanning the map during every operation.
- Reject non-positive capacities by panicking with a message containing `capacity`.

The tests exercise interleaved readers/writers, repeated updates, and eviction correctness under pressure.
