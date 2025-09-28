#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { renderHeatmap } = require('../heatmap.js');

function normalize(html) {
  return html.replace(/\s+/g, ' ').trim();
}

function run() {
  const data = [
    {
      model: 'Deep <Think>',
      totals: { score: 31, percent: 86.1, outOf: 36 },
      cells: [
        { id: 'q1', status: 'pass' },
        { id: 'q2', status: 'warn' },
        { id: 'q3', status: 'fail' },
      ],
    },
    {
      model: 'Gemini',
      totals: { score: 25, percent: 72.0, outOf: 36 },
      cells: [
        { id: 'q1', status: 'pass' },
        { id: 'q2', status: 'pass' },
        { id: 'q3', status: 'pass' },
      ],
    },
  ];

  const html = renderHeatmap(data, { palette: { pass: 'green', fail: 'red', warn: 'amber' } });
  const clean = normalize(html);
  assert(clean.startsWith('<table'));
  assert(clean.includes('<thead>'));
  assert(clean.includes('<tbody>'));
  assert(clean.includes('class="heatmap-cell status-pass green"'));
  assert(clean.includes('class="heatmap-cell status-warn amber"'));
  assert(clean.includes('class="heatmap-cell status-fail red"'));
  assert(clean.includes('span class="sr-only"'));
  assert(clean.includes('Deep &lt;Think&gt;'));
  assert(clean.includes('data-question="q1"'));
  assert(clean.includes('31 / 36 (86.1%)'));

  const filtered = renderHeatmap([], {});
  assert(normalize(filtered) === '<table><thead></thead><tbody></tbody></table>');

  assert.throws(() => renderHeatmap(null), /TypeError/);

  console.log('All tests passed.');
}

run();
