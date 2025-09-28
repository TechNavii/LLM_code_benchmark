#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { toTitleCase } = require('../stringUtils');

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

function run() {
  test('basic words', () => {
    assert.equal(toTitleCase('hello world'), 'Hello World');
  });

  test('multiple spaces collapsed', () => {
    assert.equal(toTitleCase('  multiple   spaces here '), 'Multiple Spaces Here');
  });

  test('mixed casing', () => {
    assert.equal(toTitleCase('nODE js Rocks'), 'Node Js Rocks');
  });

  test('punctuation preserved', () => {
    assert.equal(toTitleCase('hello-world! time,to:code'), 'Hello-world! Time,to:code');
  });

  test('single letter word', () => {
    assert.equal(toTitleCase('a tale of two cities'), 'A Tale Of Two Cities');
  });

  test('empty string', () => {
    assert.equal(toTitleCase(''), '');
  });

  test('non-string throws', () => {
    assert.throws(() => toTitleCase(null), TypeError);
  });
}

run();

if (failures > 0) {
  console.error(`\n${failures} test(s) failed.`);
  process.exitCode = 1;
} else {
  console.log('\nAll tests passed.');
}
