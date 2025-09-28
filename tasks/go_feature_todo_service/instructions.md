# Task: Implement TODO service (Go)

Implement the logic in `pkg/todo` so that the service can add tasks, mark them complete, and produce a status summary.

Requirements:
- `Service.AddTask` must persist the task through the repository, assigning a new ID and defaulting the status to `pending`.
- `Service.CompleteTask` should mark the task `completed` when it exists and return whether an update occurred.
- `Service.Summary` returns a slice of strings formatted as `status: count`, sorted lexicographically by status.
- Repository methods should remain simple; add helper functions if needed but keep the public API unchanged.

Do not modify the tests.

## Testing
```
go test ./...
```
