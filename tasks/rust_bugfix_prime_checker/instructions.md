# Task: Fix Rust primality checker

`prime::is_prime` contains several logic bugs:
- Numbers less than 2 should not be considered prime.
- Perfect squares (e.g. 9, 49) slip through.

Update the function so that it correctly identifies prime numbers without altering the function signature or the provided tests.

## Testing
```
cargo test
```
