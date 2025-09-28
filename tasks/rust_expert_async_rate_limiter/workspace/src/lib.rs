use std::time::Duration;

use tokio::sync::Semaphore;

pub struct RateLimiter {
    max_permits: usize,
    semaphore: Semaphore,
    _interval: Duration,
}

impl RateLimiter {
    pub fn new(max_permits: usize, interval: Duration) -> Self {
        Self {
            max_permits,
            semaphore: Semaphore::new(max_permits),
            _interval: interval,
        }
    }

    pub async fn acquire(&self) {
        let _permit = self.semaphore.acquire().await.unwrap();
    }

    pub async fn release(&self) {
        self.semaphore.add_permits(1);
    }
}
