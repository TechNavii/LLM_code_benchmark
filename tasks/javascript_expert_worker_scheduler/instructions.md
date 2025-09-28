# Task: Implement priority worker scheduler

`WorkerScheduler.execute(jobs, options)` must schedule computational jobs across a pool of worker threads. The current implementation runs sequentially and ignores priorities, concurrency limits, and cancellation. Implement the following:

- Constructor accepts `{ size, workerPath }`. Initialize exactly `size` workers using `worker_threads.Worker` and reuse them across calls.
- `execute` accepts job objects `{ id, priority, duration, payload, handler }`. Jobs must run in descending priority order; equal priority preserves input order.
- Submit jobs to workers using `postMessage`. Workers will `require` `workspace/worker.js`, which should execute `handler(payload)` safely and return `{ id, result }` or `{ id, error }`.
- Concurrency must not exceed `size`; limit in-flight jobs per worker.
- Support `{ signal }`: aborting the signal must cancel pending jobs and reject with an `AbortError`.
- Resolve to an array of `{ id, status, result?, reason? }` in execution order.
- Ensure workers terminate on `close()` and no promises leak.

## Testing
```
node tests/test_scheduler.js
```
