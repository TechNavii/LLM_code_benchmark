use rate_limiter::RateLimiter;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::task::JoinSet;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn enforces_rate_over_interval() {
    let limiter = Arc::new(RateLimiter::new(2, Duration::from_millis(100)));
    let start = Instant::now();

    let mut set = JoinSet::new();
    for _ in 0..4 {
        let limiter = limiter.clone();
        set.spawn(async move {
            limiter.acquire().await;
            tokio::time::sleep(Duration::from_millis(10)).await;
            limiter.release().await;
        });
    }
    while (set.join_next().await).is_some() {}

    let elapsed = start.elapsed();
    assert!(elapsed >= Duration::from_millis(150), "Limiter should throttle bursts; elapsed={:?}", elapsed);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn cancels_pending_when_dropped() {
    let limiter = Arc::new(RateLimiter::new(1, Duration::from_millis(50)));
    let pending = limiter.clone();
    let handle = tokio::spawn(async move {
        pending.acquire().await;
    });

    tokio::time::sleep(Duration::from_millis(10)).await;
    drop(limiter);

    let result = tokio::time::timeout(Duration::from_millis(100), handle).await;
    assert!(result.is_ok(), "Pending acquisition should be cancelled when limiter dropped");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn fairness_across_tasks() {
    let limiter = Arc::new(RateLimiter::new(3, Duration::from_millis(120)));
    let mut set = JoinSet::new();
    let order = Arc::new(tokio::sync::Mutex::new(Vec::new()));

    for i in 0..6 {
        let limiter = limiter.clone();
        let order = order.clone();
        set.spawn(async move {
            limiter.acquire().await;
            {
                let mut guard = order.lock().await;
                guard.push(i);
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
            limiter.release().await;
        });
    }

    while (set.join_next().await).is_some() {}

    let collected = order.lock().await.clone();
    assert!(collected.len() == 6, "All tasks should complete");
    assert!(collected.windows(2).any(|w| w[0] < w[1]), "Expected multiple batches respecting FIFO fairness: {:?}", collected);
}
