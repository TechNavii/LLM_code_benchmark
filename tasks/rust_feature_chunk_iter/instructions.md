# Task: Implement chunking helper (Rust)

Implement `chunk::chunk` to split an iterator into fixed-size batches.

Requirements:
- Reject `size == 0` by returning an error describing the size issue.
- Consume the iterator exactly once without cloning data.
- Preserve element order and return `Vec<Vec<T>>` chunks.
- When `strict` is `true`, return an error mentioning `strict` if the final chunk would be incomplete.
- When `strict` is `false`, include the final partial chunk.

You may adjust the error messages for clarity, but ensure the tests continue to pass.

## Testing
```
cargo test
```
