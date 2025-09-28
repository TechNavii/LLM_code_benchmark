package tokenbucket

import (
    "sync"
    "time"
)

// TokenBucket represents a time-aware token bucket.
type TokenBucket struct {
    mu sync.Mutex
    // participants must fill in appropriate fields.
}

func NewTokenBucket(capacity int, refillRate float64, start time.Time) *TokenBucket {
    // TODO: implement
    panic("not implemented")
}

func (b *TokenBucket) Allow(at time.Time, tokens int) bool {
    // TODO: implement
    panic("not implemented")
}
