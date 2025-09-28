'use strict';

/**
 * Poll `conditionFn` until it returns a truthy value or reject on timeout.
 *
 * The implementation is intentionally incorrect for the benchmark task.
 */
async function waitFor(conditionFn, options = {}) {
  if (typeof conditionFn !== 'function') {
    throw new TypeError('conditionFn must be a function');
  }
  return conditionFn();
}

module.exports = {
  waitFor,
};
