# Task: Fix expert-level concurrency defects in ThreadPool

`ThreadPool` in `workspace/thread_pool.{h,cpp}` has multiple race conditions and lifetime issues:
- Worker threads are detached in the destructor, allowing tasks to outlive the pool and access freed state.
- `stop_` is mutated without holding the mutex causing data races, and tasks may be abandoned when shutdown occurs while work remains.
- Condition variable usage lacks a predicate, letting spurious wakeups drop tasks or exit prematurely.

Make the following guarantees:
- The destructor blocks until all queued tasks complete and all worker threads join.
- `enqueue` may be called concurrently and throws only when shutdown has started.
- No tasks are lost during shutdown—pending work drains before threads exit.
- `size()` remains lock-free but reflects the number of worker threads.

Use modern C++20 best practices: RAII, scoped guards, minimal locking, and avoid busy-waiting. Update both `.h` and `.cpp` as needed without changing the public API.

## Testing
```
bash tests/run-tests.sh
```
