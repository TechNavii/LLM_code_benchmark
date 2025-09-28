'use strict';

const { parentPort } = require('node:worker_threads');

if (!parentPort) {
  throw new Error('worker must be spawned in worker thread');
}

parentPort.on('message', async (payload) => {
  const { id, task } = payload;
  try {
    const result = await task();
    parentPort.postMessage({ id, result });
  } catch (error) {
    parentPort.postMessage({ id, error: error.message || String(error) });
  }
});
