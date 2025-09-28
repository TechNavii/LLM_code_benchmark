# Task: Implement `waitFor` polling helper

Complete `waitFor` in `asyncUtils.js` so that it polls a synchronous condition function until it returns a truthy value, or rejects once a timeout is reached.

Requirements:
- `conditionFn` must be invoked repeatedly every `interval` milliseconds until it evaluates to truthy; return that truthy value immediately.
- Default options: `interval` of 50 ms and `timeout` of 1000 ms.
- Reject with an `Error` mentioning "timeout" if the condition is still falsy when the timeout expires.
- Validate options: both `interval` and `timeout` must be positive numbers (greater than zero). Throw a `TypeError` when they are not numbers and a `RangeError` when they are non-positive.
- Propagate errors thrown by `conditionFn` without wrapping them.
- The condition should run immediately before the first wait (i.e., no initial delay).

The tests invoke the helper using Node.js timers—avoid external dependencies.

## Testing
```
node tests/run-tests.js
```
