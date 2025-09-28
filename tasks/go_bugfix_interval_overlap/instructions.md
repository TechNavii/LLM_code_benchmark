# Task: Fix interval overlap logic (Go)

`intervals.HasOverlap` should treat intervals as half-open `[start, end)` ranges. Two intervals only overlap when they share at least one interior point. The current implementation incorrectly treats intervals that merely touch at their boundaries as overlapping.

Update the implementation to satisfy the tests without modifying the public API.

## Testing
```
go test ./...
```
