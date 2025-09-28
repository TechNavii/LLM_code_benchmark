#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const { generateToc } = require('../toc');

function flatten(nodes) {
  const output = [];
  (function walk(list) {
    for (const node of list) {
      output.push([node.level, node.text, node.slug]);
      walk(node.children);
    }
  })(nodes);
  return output;
}

async function run() {
  const markdown = `# Title\n\n## Overview\nSome text\n\n### Details\n\n## Overview\n\n	tab indented code\n\n\`\`\`\n# in code\n\`\`\`\n\n### Details\n`;
  const toc = generateToc(markdown);
  const flattened = flatten(toc);
  assert.deepEqual(flattened, [
    [1, 'Title', 'title'],
    [2, 'Overview', 'overview'],
    [3, 'Details', 'details'],
    [2, 'Overview', 'overview-1'],
    [3, 'Details', 'details-1'],
  ]);
  assert.equal(toc[0].children[1].children.length, 1);

  const filtered = generateToc(markdown, { minDepth: 2, maxDepth: 3 });
  assert.deepEqual(flatten(filtered), [
    [2, 'Overview', 'overview'],
    [3, 'Details', 'details'],
    [2, 'Overview', 'overview-1'],
    [3, 'Details', 'details-1'],
  ]);

  const customSlug = generateToc('# Café #\n# Café', {
    slugify: (text, index) => `${text.toUpperCase()}-${index}`,
  });
  assert.deepEqual(flatten(customSlug), [
    [1, 'Café', 'CAFÉ-0'],
    [1, 'Café', 'CAFÉ-1'],
  ]);

  console.log('All tests passed.');
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
