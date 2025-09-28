#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { waitFor } = require('../asyncUtils');

const tests = [];

function test(name, fn) {
  tests.push({ name, fn });
}

function sleep(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

// Test definitions ---------------------------------------------------------

test('resolves immediately when condition already truthy', async () => {
  const value = await waitFor(() => 'ready', { interval: 5, timeout: 50 });
  assert.equal(value, 'ready');
});

test('polls until condition becomes truthy', async () => {
  let state = false;
  setTimeout(() => {
    state = 'done';
  }, 30);

  const start = Date.now();
  const result = await waitFor(() => state, { interval: 10, timeout: 200 });
  const elapsed = Date.now() - start;

  assert.equal(result, 'done');
  assert(elapsed >= 25);
});

test('rejects when timeout reached', async () => {
  const start = Date.now();
  await assert.rejects(
    waitFor(() => false, { interval: 10, timeout: 40 }),
    (error) => {
      assert.match(error.message, /timeout/i);
      const elapsed = Date.now() - start;
      assert(elapsed >= 35);
      return true;
    },
  );
});

test('validates options', async () => {
  await assert.rejects(() => waitFor(() => true, { interval: 0 }));
  await assert.rejects(() => waitFor(() => true, { timeout: 0 }));
  await assert.rejects(() => waitFor(() => true, { interval: -5 }));
});

test('propagates synchronous errors from condition', async () => {
  const error = new Error('bad condition');
  await assert.rejects(
    waitFor(() => {
      throw error;
    }, { interval: 5, timeout: 50 }),
    (err) => err === error,
  );
});

test('invokes condition repeatedly until resolved', async () => {
  let callCount = 0;
  let ready = false;

  setTimeout(() => {
    ready = true;
  }, 35);

  const result = await waitFor(() => {
    callCount += 1;
    return ready ? 'ok' : false;
  }, { interval: 10, timeout: 200 });

  assert.equal(result, 'ok');
  assert(callCount >= 3);
});

// Runner -------------------------------------------------------------------

(async () => {
  let failures = 0;
  for (const { name, fn } of tests) {
    try {
      await fn();
      console.log(`✔ ${name}`);
    } catch (error) {
      failures += 1;
      console.error(`✖ ${name}`);
      console.error(error.stack);
    }
  }

  if (failures > 0) {
    console.error(`\n${failures} test(s) failed.`);
    process.exitCode = 1;
  } else {
    console.log('\nAll tests passed.');
  }
})();
