package scheduler

import (
    "context"
    "errors"
    "sort"
    "sync"
    "testing"
    "time"
)

func TestRespectPriorityAndConcurrency(t *testing.T) {
    ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
    defer cancel()

    sched := New(2)
    var mu sync.Mutex
    var order []int
    var concurrency, maxConcurrency int
    var wg sync.WaitGroup

    tasks := []Task{}
    for i := 0; i < 6; i++ {
        priority := 5 - i
        wg.Add(1)
        tasks = append(tasks, Task{
            Priority: priority,
            Fn: func(ctx context.Context) error {
                defer wg.Done()
                mu.Lock()
                concurrency++
                if concurrency > maxConcurrency {
                    maxConcurrency = concurrency
                }
                mu.Unlock()

                select {
                case <-time.After(50 * time.Millisecond):
                case <-ctx.Done():
                    return ctx.Err()
                }

                mu.Lock()
                order = append(order, priority)
                concurrency--
                mu.Unlock()
                return nil
            },
        })
    }

    if err := sched.Run(ctx, tasks); err != nil {
        t.Fatalf("run returned error: %v", err)
    }

    wg.Wait()

    if maxConcurrency > 2 {
        t.Fatalf("expected concurrency limit 2, got %d", maxConcurrency)
    }

    expected := make([]int, len(tasks))
    for i := range expected {
        expected[i] = 5 - i
    }
    if !sort.IntsAreSorted(order) {
        t.Fatalf("tasks should be executed by descending priority: %v", order)
    }
}

func TestStopsOnContextCancel(t *testing.T) {
    ctx, cancel := context.WithCancel(context.Background())
    sched := New(3)

    started := make(chan struct{})
    tasks := []Task{
        {
            Priority: 10,
            Fn: func(ctx context.Context) error {
                close(started)
                <-ctx.Done()
                return ctx.Err()
            },
        },
        {
            Priority: 9,
            Fn: func(ctx context.Context) error {
                t.Fatalf("second task should not run after cancel")
                return nil
            },
        },
    }

    errc := make(chan error, 1)
    go func() {
        errc <- sched.Run(ctx, tasks)
    }()

    <-started
    cancel()

    err := <-errc
    if !errors.Is(err, context.Canceled) {
        t.Fatalf("expected context.Canceled, got %v", err)
    }
}

func TestPropagatesTaskErrors(t *testing.T) {
    ctx := context.Background()
    sched := New(4)
    expected := errors.New("boom")
    tasks := []Task{
        {
            Priority: 1,
            Fn: func(context.Context) error {
                return expected
            },
        },
        {
            Priority: 0,
            Fn: func(context.Context) error {
                t.Fatalf("subsequent task should not run after error")
                return nil
            },
        },
    }

    err := sched.Run(ctx, tasks)
    if !errors.Is(err, expected) {
        t.Fatalf("expected %v, got %v", expected, err)
    }
}
