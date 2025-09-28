# Task: Implement priority-aware concurrent scheduler

`scheduler.New(limit)` should execute tasks concurrently up to `limit`, processing highest priority first. The current implementation runs sequentially and ignores cancellation. Implement the following:

- `Run(ctx, tasks)` must process tasks in descending `Priority` order. Tasks with equal priority can run in FIFO order.
- Concurrency must never exceed `limit`; use worker goroutines and buffered queues.
- Respect context cancellation: if `ctx` is canceled, abort outstanding tasks immediately and return `ctx.Err()`.
- Propagate the first task error and stop scheduling additional tasks.
- Ensure no goroutines leak after `Run` completes.

Use only the standard library. Update both `scheduler.go` and accompanying tests as needed but keep the public API stable.

## Testing
```
go test ./...
```
