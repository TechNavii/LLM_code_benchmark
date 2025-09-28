# Task: Fix primality check edge cases

`prime.is_prime` has multiple defects:
- Numbers less than 2 (including negatives) are incorrectly reported as prime.
- Perfect squares slip through because the trial division upper bound stops too early.
- Non-integer inputs should raise `TypeError` instead of being coerced.

Update the implementation to satisfy the unit tests without modifying the tests or changing the public API.

## Testing
```
pytest -q
```
