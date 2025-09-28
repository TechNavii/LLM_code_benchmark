# Task: Implement iterable batching helper

Implement `batched` in `batching.py` so that it splits any finite iterable into fixed-size batches.

Requirements:
- `size` must be a positive integer. Raise `ValueError` when `size <= 0` and `TypeError` when `size` is not an integer.
- Return batches as tuples by default. When `as_tuple=False`, return lists instead.
- Preserve the original order and consume the iterable only once.
- If `strict=True`, raise `ValueError` when the final batch would be undersized.
- An empty iterable should return an empty list.

Do not modify the tests.

## Testing
```
pytest -q
```
