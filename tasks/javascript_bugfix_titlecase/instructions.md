# Task: Fix title case conversion

`stringUtils.toTitleCase` should convert input strings to title case while handling whitespace and punctuation gracefully. Currently it simply uppercases the entire string.

Requirements:
- Throw `TypeError` when the input is not a string.
- Trim leading/trailing whitespace.
- Collapse intermediate whitespace to single spaces.
- Title case each word by uppercasing the first letter and lowercasing the rest.
- Preserve punctuation characters such as hyphens, commas, colons, etc.

Do not modify the test runner. Keep changes local to `stringUtils.js` unless additional helpers are necessary within the workspace directory.

## Testing
```
node tests/run-tests.js
```
