# JavaScript Expert Task: Promise Pool

Implement a high-performance promise pool in `workspace/pool.js`.

Export an async function `promisePool(tasks, limit, options = {})` that satisfies:

- `tasks` is an iterable of functions returning promises (or values). Tasks must execute in order and results are returned in an array matching the original order.
- `limit` is a positive integer controlling the maximum concurrent executions. Reject with a `RangeError` if invalid.
- The function resolves when every task completes, or rejects immediately when the first task rejects. When rejecting, all in-flight jobs may continue but their rejections must not trigger unhandled rejections.
- Optional `options.signal` is an [`AbortSignal`]. If the signal fires, stop launching new tasks and reject with the abort reason. Already running tasks continue but their results should be ignored.
- Expose progress via an optional `options.onProgress(completed, total)` callback invoked whenever a task settles. Callbacks must never throw (wrap errors).

The pool should minimise microtask churn, avoid starving the event loop, and reuse resolved slots immediately.

[`AbortSignal`]: https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal
