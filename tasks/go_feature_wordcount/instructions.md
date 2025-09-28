# Task: Implement word counting utility (Go)

Implement `textutil.WordCount` so that it returns a normalized frequency map of words in the input string.

Requirements:
- Split on whitespace and punctuation, but preserve hyphenated words and internal apostrophes.
- Treat the result case-insensitively (all keys should be lowercase).
- Ignore empty tokens after splitting.
- Handle Unicode letters (use `unicode` helpers rather than ASCII-only logic).

Do not modify the function signature or the provided tests.

## Testing
```
go test ./...
```
