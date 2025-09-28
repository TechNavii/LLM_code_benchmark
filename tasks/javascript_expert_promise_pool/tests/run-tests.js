#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { promisePool } = require('../workspace/pool');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runTests() {
  await testResolvesInOrder();
  await testConcurrencyLimit();
  await testRejectsOnFailure();
  await testAbortSignal();
  await testProgressCallback();
  console.log('All tests passed.');
}

async function testResolvesInOrder() {
  const tasks = [
    () => sleep(20).then(() => 'a'),
    () => sleep(5).then(() => 'b'),
    () => sleep(10).then(() => 'c'),
  ];
  const results = await promisePool(tasks, 2);
  assert.deepEqual(results, ['a', 'b', 'c']);
}

async function testConcurrencyLimit() {
  let active = 0;
  let maxActive = 0;
  const tasks = Array.from({ length: 6 }, (_, i) => async () => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await sleep(15 + i * 2);
    active -= 1;
    return i;
  });
  const results = await promisePool(tasks, 3);
  assert.equal(maxActive, 3);
  assert.deepEqual(results, [0, 1, 2, 3, 4, 5]);
}

async function testRejectsOnFailure() {
  let unhandled = false;
  const handler = () => {
    unhandled = true;
  };
  process.once('unhandledRejection', handler);

  const tasks = [
    () => sleep(5).then(() => 'ok'),
    () => Promise.reject(new Error('fail')),
    () => sleep(5).then(() => 'late'),
  ];

  await assert.rejects(promisePool(tasks, 2), /fail/);
  process.removeListener('unhandledRejection', handler);
  assert.equal(unhandled, false, 'should not leak unhandled rejections');
}

async function testAbortSignal() {
  const controller = new AbortController();
  const started = [];
  const tasks = Array.from({ length: 4 }, (_, i) => async () => {
    started.push(i);
    if (i === 1) {
      controller.abort(new Error('stop'));
    }
    await sleep(20);
    return i;
  });

  await assert.rejects(
    promisePool(tasks, 2, { signal: controller.signal }),
    /stop/
  );
  assert.ok(started.includes(0) && started.includes(1));
}

async function testProgressCallback() {
  const seen = [];
  const tasks = Array.from({ length: 3 }, (_, i) => async () => {
    await sleep(5 + i * 5);
    return i * i;
  });

  const results = await promisePool(tasks, 2, {
    onProgress(completed, total) {
      seen.push([completed, total]);
      if (completed === 2) {
        throw new Error('progress errors must be swallowed');
      }
    },
  });

  assert.deepEqual(results, [0, 1, 4]);
  assert.deepEqual(seen[0], [1, 3]);
  assert(seen.find(([c]) => c === 3), 'expected final progress callback');
}

runTests().catch((error) => {
  console.error(error);
  process.exit(1);
});
