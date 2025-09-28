# Task: Implement TODO CLI helpers

The CLI should accept arguments in the form:
```
node index.js --tasks "Title | status; Another | status"
```
and produce a summary string that includes:
- Total number of tasks
- Count of tasks per status (status values lowercased)
- Alphabetical ordering of status blocks

Requirements:
- Argument parsing lives in `lib/parseArgs.js`.
- Summary generation lives in `lib/summary.js`.
- `index.js` orchestrates the workflow via the exported `run(argv)` function.
- Ignore empty task entries and trim whitespace around titles/status values.
- Treat status comparisons case-insensitively when counting.

Do not modify the test harness.

## Testing
```
node tests/run-tests.js
```
