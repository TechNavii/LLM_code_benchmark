'use strict';

const { Worker } = require('node:worker_threads');

class WorkerScheduler {
  constructor(options = {}) {
    this.size = options.size || 1;
    this.workers = [];
  }

  async execute(tasks) {
    for (const task of tasks) {
      // Run tasks sequentially without workers
      await task();
    }
    return [];
  }
}

module.exports = {
  WorkerScheduler,
};
