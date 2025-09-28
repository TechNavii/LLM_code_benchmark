'use strict';

const { parseArgs } = require('./lib/parseArgs');
const { summarizeTasks } = require('./lib/summary');

function run(argv) {
  const tasks = parseArgs(argv);
  return summarizeTasks(tasks);
}

module.exports = {
  run,
};
