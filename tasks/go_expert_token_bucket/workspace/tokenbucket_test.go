package tokenbucket

import (
    "sync"
    "testing"
    "time"
)

func TestBurstConsumptionAndRefill(t *testing.T) {
    start := time.Unix(0, 0)
    bucket := NewTokenBucket(10, 5, start)

    if ok := bucket.Allow(start, 7); !ok {
        t.Fatalf("expected burst to succeed")
    }
    if ok := bucket.Allow(start, 3); !ok {
        t.Fatalf("expected remaining tokens to be enough")
    }
    if ok := bucket.Allow(start, 1); ok {
        t.Fatalf("bucket should be empty after spending capacity")
    }

    afterHalfSecond := start.Add(500 * time.Millisecond)
    if ok := bucket.Allow(afterHalfSecond, 2); ok {
        t.Fatalf("only 2.5 tokens should be available, spending 2 must fail to preserve fractional balance")
    }

    afterOneSecond := start.Add(1 * time.Second)
    if ok := bucket.Allow(afterOneSecond, 2); !ok {
        t.Fatalf("expect refill to provide tokens")
    }
}

func TestInvalidInputs(t *testing.T) {
    start := time.Now()
    bucket := NewTokenBucket(4, 2, start)

    if ok := bucket.Allow(start, 0); ok {
        t.Fatalf("zero token request should be rejected")
    }
    if ok := bucket.Allow(start, -3); ok {
        t.Fatalf("negative token request should be rejected")
    }
}

func TestConcurrentAccess(t *testing.T) {
    start := time.Unix(0, 0)
    bucket := NewTokenBucket(20, 10, start)

    var wg sync.WaitGroup
    successes := int64(0)
    failures := int64(0)

    for i := 0; i < 100; i++ {
        wg.Add(1)
        go func(idx int) {
            defer wg.Done()
            at := start.Add(time.Duration(idx*30) * time.Millisecond)
            if bucket.Allow(at, 3) {
                syncAddInt64(&successes, 1)
            } else {
                syncAddInt64(&failures, 1)
            }
        }(i)
    }

    wg.Wait()

    if successes == 0 {
        t.Fatalf("expected at least one successful reservation")
    }
    if failures == 0 {
        t.Fatalf("expected some calls to be throttled")
    }
}

var int64Mu sync.Mutex

func syncAddInt64(dst *int64, delta int64) {
    int64Mu.Lock()
    *dst += delta
    int64Mu.Unlock()
}
