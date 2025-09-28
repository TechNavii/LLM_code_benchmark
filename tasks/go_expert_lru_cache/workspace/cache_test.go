package cache

import (
    "sync"
    "testing"
)

func TestNewPanicsOnInvalidCapacity(t *testing.T) {
    defer func() {
        if r := recover(); r == nil {
            t.Fatalf("expected panic on non-positive capacity")
        }
    }()
    New(0)
}

func TestSetAndGetEvictionOrder(t *testing.T) {
    c := New(3)
    c.Set("a", 1)
    c.Set("b", 2)
    c.Set("c", 3)

    if val, ok := c.Get("a"); !ok || val.(int) != 1 {
        t.Fatalf("expected to fetch a")
    }

    // Insert new entry, should evict b (least recently used)
    c.Set("d", 4)
    if _, ok := c.Get("b"); ok {
        t.Fatalf("expected b to be evicted")
    }
    if c.Len() != 3 {
        t.Fatalf("expected len 3, got %d", c.Len())
    }
}

func TestPromoteOnGetPreventsEviction(t *testing.T) {
    c := New(2)
    c.Set("x", "first")
    c.Set("y", "second")

    if _, ok := c.Get("x"); !ok {
        t.Fatalf("expected to read x")
    }
    c.Set("z", "third")

    if _, ok := c.Get("x"); !ok {
        t.Fatalf("x should still be present")
    }
    if _, ok := c.Get("y"); ok {
        t.Fatalf("y should have been evicted")
    }
}

func TestUpdateDoesNotGrowSize(t *testing.T) {
    c := New(2)
    c.Set("id", 1)
    c.Set("id", 2)
    if c.Len() != 1 {
        t.Fatalf("expected len 1 after update")
    }
    if value, ok := c.Get("id"); !ok || value.(int) != 2 {
        t.Fatalf("expected updated value")
    }
}

func TestConcurrentReadersAndWriters(t *testing.T) {
    c := New(5)
    var wg sync.WaitGroup

    for i := 0; i < 5; i++ {
        key := string(rune('a' + i))
        c.Set(key, i)
    }

    for i := 0; i < 50; i++ {
        wg.Add(2)
        go func(idx int) {
            defer wg.Done()
            key := string(rune('a' + idx%5))
            c.Set(key, idx)
        }(i)

        go func(idx int) {
            defer wg.Done()
            key := string(rune('a' + idx%5))
            if _, ok := c.Get(key); !ok {
                t.Errorf("expected key %s to exist", key)
            }
        }(i)
    }

    wg.Wait()
    if c.Len() > 5 {
        t.Fatalf("cache size should not exceed capacity")
    }
}
