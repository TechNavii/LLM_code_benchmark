package cache

import "sync"

// Cache is a concurrency-safe LRU cache.
type Cache struct {
    mu sync.Mutex
    // TODO: add fields
}

// New creates a cache with the given positive capacity.
func New(capacity int) *Cache {
    // TODO: implement
    panic("not implemented")
}

// Get fetches a value, marking the key as recently used.
func (c *Cache) Get(key string) (any, bool) {
    // TODO: implement
    panic("not implemented")
}

// Set inserts or updates a value, evicting the least recently used entry.
func (c *Cache) Set(key string, value any) {
    // TODO: implement
    panic("not implemented")
}

// Len returns the current number of entries.
func (c *Cache) Len() int {
    // TODO: implement
    panic("not implemented")
}
