#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { parseArgs } = require('../workspace/lib/parseArgs');
const { summarizeTasks } = require('../workspace/lib/summary');
const { run } = require('../workspace/index');

let failures = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`✔ ${name}`);
  } catch (error) {
    failures += 1;
    console.error(`✖ ${name}`);
    console.error(error.stack);
  }
}

test('parseArgs extracts tasks from argv', () => {
  const argv = ['node', 'index.js', '--tasks', 'Buy milk | Completed;  Write docs | Pending ; ; '];
  const tasks = parseArgs(argv);
  assert.deepEqual(tasks, [
    { title: 'Buy milk', status: 'completed' },
    { title: 'Write docs', status: 'pending' },
  ]);
});

test('summarizeTasks reports totals in alpha order', () => {
  const tasks = [
    { title: 'A', status: 'pending' },
    { title: 'B', status: 'completed' },
    { title: 'C', status: 'Completed' },
    { title: 'D', status: 'blocked' },
  ];
  const summary = summarizeTasks(tasks).split('\n');
  assert.equal(summary[0], 'total_tasks: 4');
  assert.deepEqual(summary.slice(1), [
    'blocked: 1',
    'completed: 2',
    'pending: 1',
  ]);
});

test('run generates the same summary', () => {
  const argv = ['node', 'index.js', '--tasks', 'Demo | Done; Draft | Pending'];
  const output = run(argv).split('\n');
  assert.equal(output[0], 'total_tasks: 2');
  assert.deepEqual(output.slice(1), ['done: 1', 'pending: 1']);
});

test('missing --tasks flag returns empty summary', () => {
  const argv = ['node', 'index.js'];
  const output = run(argv);
  assert.equal(output, 'total_tasks: 0');
});

if (failures > 0) {
  console.error(`\n${failures} test(s) failed.`);
  process.exitCode = 1;
} else {
  console.log('\nAll tests passed.');
}
