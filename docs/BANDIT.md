# Bandit SAST Scanning

This project uses [Bandit](https://bandit.readthedocs.io/) for Python static application security testing (SAST).

## Configuration

Bandit is configured via `.bandit.yml` with the following settings:

- **Scope**: `server/` and `harness/` directories
- **Exclusions**: Test directories (`tests/`, `harness/tests/`)
- **Skipped checks**:
  - `B101`: assert_used - Asserts are acceptable for invariants and type narrowing
  - `B404`: import subprocess - Subprocess is necessary for harness execution
  - `B603`: subprocess_without_shell_equals_true - We use `shell=False` by default (secure)

## Running Bandit

```bash
# Run via script (recommended)
./scripts/bandit.sh

# Run directly
.venv/bin/bandit -c .bandit.yml -r server/ harness/
```

## Suppression Policy

Bandit findings can be suppressed using inline `# nosec <CODE>` comments **only with explicit justification**:

```python
# nosec B310: URLs are localhost http:// only (from validated config)
with urlopen(request, timeout=3) as response:  # nosec B310
    raw = response.read().decode("utf-8")
```

### Suppression Guidelines

1. **Document the reason**: Every suppression must include a comment explaining why it is safe
2. **Be specific**: Use the specific check code (e.g., `# nosec B310`, not just `# nosec`)
3. **Keep minimal**: Suppress only the specific line, not entire functions
4. **Review regularly**: Suppressions should be revisited when code changes

### Current Suppressions

| Location | Check | Justification |
|----------|-------|---------------|
| `server/routes/router.py:325` | B310 | URLs are localhost http:// only (from validated config) |
| `harness/expert_questions/run_benchmark.py:354` | B113 | Timeout is present (false positive) |

## CI Integration

Bandit runs in CI as part of the quality gates workflow. The build will fail if:
- New medium or high severity issues are introduced
- Suppressions lack justification

## False Positives

If you encounter a false positive:

1. Verify it is truly a false positive (not a real security issue)
2. Add an inline suppression with justification
3. Document it in this file's "Current Suppressions" table
4. Consider opening an issue with the Bandit project if the false positive is common
