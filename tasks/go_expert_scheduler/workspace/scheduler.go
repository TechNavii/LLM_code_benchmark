package scheduler

import "context"

// Task represents a unit of work with a priority.
type Task struct {
	Priority int
	Fn       func(context.Context) error
}

// Scheduler executes tasks with a concurrency limit.
type Scheduler struct {
	limit int
}

// New creates a scheduler with the provided concurrency limit.
func New(limit int) *Scheduler {
	return &Scheduler{limit: limit}
}

// Run executes tasks in FIFO order ignoring priority.
func (s *Scheduler) Run(ctx context.Context, tasks []Task) error {
	for _, task := range tasks {
		if err := task.Fn(ctx); err != nil {
			return err
		}
	}
	return nil
}
