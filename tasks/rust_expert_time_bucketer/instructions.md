# Rust Expert Task: Time Bucketing Aggregator

Implement a streaming-friendly time bucketer in `workspace/src/lib.rs`.

### Required API

```rust
#[derive(Debug, Clone, PartialEq)]
pub struct Bucket {
    pub start: i64,
    pub end: i64,
    pub count: usize,
    pub average: f64,
    pub min: f64,
    pub max: f64,
}

pub fn bucketize(points: &[(i64, f64)], width: i64) -> Vec<Bucket>
```

- `points` is sorted by timestamp ascending. Timestamps are expressed in seconds.
- `width` is a positive number of seconds defining each bucket.
- Determine the first bucket start by rounding the first timestamp down to the nearest multiple of `width` (allowing negatives). Each bucket covers `[start, start + width)`.
- Assign every point to the appropriate bucket. Buckets with no samples inside the covered range should still be emitted with `count = 0` and the previous bucket's average/min/max values preserved.
- The result must cover the range from the first bucket start up to and including the bucket that contains the last timestamp.
- Floating point aggregates must be computed using `f64` arithmetic without intermediate rounding.
- Reject non-positive widths by panicking with a message containing `width`.

The tests check bucket boundaries across gaps, negative timestamps, stability with large datasets, and propagation of statistics for empty buckets.
