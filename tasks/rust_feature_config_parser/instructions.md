# Task: Implement config file parser (Rust)

Implement `parser::parse_config` so that it parses key-value pairs from INI-like configuration text.

Requirements:
- Lines starting with `#` are comments and should be ignored.
- Keys and values are separated by `=`; leading/trailing whitespace around each should be trimmed.
- Keys must be non-empty; return `ConfigError::EmptyKey` otherwise.
- For malformed lines, return `ConfigError::InvalidLine` containing the original text.
- Blank lines should be ignored.
- Preserve the original insertion order in the returned vector.

Do not change the public API or the tests.

## Testing
```
cargo test
```
