# Task: Fix interval overlap detection

The function `intervals.has_overlap` should operate on half-open intervals `(start, end)` and return `True` only when the intervals share at least one interior point. The current implementation incorrectly treats intervals that merely touch at their boundaries as overlapping.

Fix the implementation to satisfy the tests without modifying the tests or the exported API.

## Testing
```
pytest -q
```
