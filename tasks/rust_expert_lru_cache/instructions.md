# Rust Expert Task: Lock-Free LRU Cache

Implement a performant LRU cache in `workspace/src/lib.rs`.

### API Skeleton

```rust
pub struct LruCache<K, V> {
    // private fields
}

impl<K: Eq + std::hash::Hash + Clone, V: Clone> LruCache<K, V> {
    pub fn new(capacity: usize) -> Self;
    pub fn len(&self) -> usize;
    pub fn get(&mut self, key: &K) -> Option<V>;
    pub fn put(&mut self, key: K, value: V);
}
```

Requirements:

- `capacity` must be greater than zero; `new` should panic with a message containing `capacity` if invalid.
- `get` returns a clone of the stored value and marks the entry as most recently used.
- `put` inserts or updates an entry. When at capacity, insertions must evict the **least recently used** entry.
- All operations must run in amortised `O(1)`.
- The cache must avoid storing duplicate keys and should not leak memory (no reference cycles).

The tests stress eviction, promotion on access, mass updates, and cloning semantics.
