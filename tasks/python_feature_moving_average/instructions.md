# Task: Implement simple moving average

Implement `simple_moving_average` in `moving_average.py` so that it returns the simple moving average for a numeric series. The function should:

- Validate that `window` is an integer greater than zero and not larger than the input length.
- Raise `TypeError` if any element of the series is not numeric.
- Return a list with length matching the input. The first `window - 1` elements must be `None`, and subsequent entries must be the average of the trailing window.
- Preserve floating point precision (do not round the result).

Do not change the public API of the module or the tests.

## Testing
```
pytest -q
```
