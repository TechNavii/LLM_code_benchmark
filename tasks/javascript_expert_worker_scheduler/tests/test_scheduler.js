'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const workerThreads = require('node:worker_threads');

class MockWorker {
  constructor() {
    this.listeners = new Map();
    MockWorker.instances.push(this);
    this.activeJobs = 0;
  }

  postMessage(job) {
    this.activeJobs++;
    MockWorker.activeCount++;
    if (MockWorker.activeCount > MockWorker.maxConcurrent) {
      MockWorker.maxConcurrent = MockWorker.activeCount;
    }
    setTimeout(() => {
      this.activeJobs--;
      MockWorker.activeCount--;
      const listener = this.listeners.get('message');
      if (listener) {
        try {
          const result = job.handler(job.payload);
          listener({ data: { id: job.id, result } });
        } catch (error) {
          listener({ data: { id: job.id, error: error.message || String(error) } });
        }
      }
    }, job.duration);
  }

  on(event, handler) {
    this.listeners.set(event, handler);
  }

  terminate() {
    // no-op for mock
  }
}
MockWorker.instances = [];
MockWorker.activeCount = 0;
MockWorker.maxConcurrent = 0;

function loadSchedulerWithMock() {
  const originalWorker = workerThreads.Worker;
  workerThreads.Worker = MockWorker;
  const schedulerPath = path.join(__dirname, '..', 'workspace', 'scheduler.js');
  delete require.cache[require.resolve(schedulerPath)];
  const { WorkerScheduler } = require(schedulerPath);
  workerThreads.Worker = originalWorker;
  return { WorkerScheduler };
}

function createJobs() {
  return [
    { id: 'c', priority: 3, duration: 60, payload: { value: 3 }, handler: ({ value }) => value * 2 },
    { id: 'a', priority: 5, duration: 30, payload: { value: 5 }, handler: ({ value }) => value + 1 },
    { id: 'b', priority: 4, duration: 40, payload: { value: 4 }, handler: ({ value }) => value - 1 },
    { id: 'd', priority: 1, duration: 10, payload: { value: 1 }, handler: () => { throw new Error('boom'); } },
  ];
}

(async () => {
  const { WorkerScheduler } = loadSchedulerWithMock();
  const scheduler = new WorkerScheduler({ size: 2 });

  const controller = new AbortController();
  const jobs = createJobs();

  const start = Date.now();
  const results = await scheduler.execute(jobs, { signal: controller.signal });
  const elapsed = Date.now() - start;

  assert(MockWorker.instances.length === 2, 'Expected scheduler to spin up worker pool');
  assert(MockWorker.maxConcurrent <= 2, 'Concurrency limit must be enforced');
  assert(elapsed < 120, 'Jobs should execute concurrently');

  const map = new Map(results.map((item) => [item.id, item]));
  assert(map.get('a').status === 'fulfilled' && map.get('a').result === 6);
  assert(map.get('b').status === 'fulfilled' && map.get('b').result === 3);
  assert(map.get('c').status === 'fulfilled' && map.get('c').result === 6);
  assert(map.get('d').status === 'rejected' && map.get('d').reason.includes('boom'));

  // Ensure priorities respected (descending order)
  const executionOrder = results.map((item) => item.id);
  assert.deepEqual(executionOrder.slice(0, 3), ['a', 'b', 'c']);

  // Cancellation after completion should prevent new jobs
  controller.abort();
  await assert.rejects(
    scheduler.execute(createJobs(), { signal: controller.signal }),
    /aborted/i,
    'Aborted controller should cause execute to reject'
  );

  console.log('All tests passed.');
})().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
