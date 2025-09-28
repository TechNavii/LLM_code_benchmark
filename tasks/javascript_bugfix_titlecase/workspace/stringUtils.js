'use strict';

/**
 * Convert a string to title case.
 *
 * Expected behavior:
 * - Each word should start with an uppercase letter followed by lowercase letters.
 * - Multiple whitespace characters should be reduced to single spaces in the output.
 * - Leading/trailing whitespace should be trimmed.
 * - Existing punctuation should be preserved.
 *
 * The current implementation is incorrect and needs to be fixed.
 */
function toTitleCase(input) {
  if (typeof input !== 'string') {
    throw new TypeError('input must be a string');
  }
  return input.toUpperCase();
}

module.exports = {
  toTitleCase,
};
