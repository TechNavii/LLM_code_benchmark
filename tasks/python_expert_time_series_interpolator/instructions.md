# Python Expert Task: Time-Series Interpolator

Analytics teams stream metrics at irregular intervals and need a consolidated feed sampled at fixed spacing. Implement `interpolate_series(samples, interval, *, method='linear')` in `workspace/interpolate.py`.

Requirements:

- `samples` is an iterable of `(timestamp, value)` pairs. Timestamps are integers representing seconds and are strictly increasing. Values are floats.
- `interval` is a positive integer specifying the sample period in seconds.
- The first and last timestamps align with the requested interval grid. Return a **new** list of `(timestamp, value)` pairs covering every timestamp from the first sample to the last sample inclusive, spaced exactly `interval` seconds apart.
- If a timestamp already exists in the input, reuse its exact value.
- For missing timestamps:
  - If `method == 'linear'`, linearly interpolate between the closest surrounding known samples.
  - If `method == 'forward_fill'`, reuse the most recent known value. Gaps before the first sample should raise `ValueError`.
- Reject unsupported methods by raising `ValueError`.
- Do not mutate the input sequence.
- Preserve floating point stability: interpolation should be performed using standard arithmetic without rounding; tests compare with `pytest.approx`.

Edge cases covered by the tests:
- Consecutive long gaps requiring multiple interpolated points.
- Mixed scenarios where some points align with the interval and others require interpolation.
- Forward-fill behaviour, including validation for leading gaps.
- Guard rails for invalid interval or method arguments.
