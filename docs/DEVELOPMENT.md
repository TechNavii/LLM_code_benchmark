# Development Guide

## Getting Started

### Prerequisites

- Python 3.11+
- Git

### Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r server/requirements.txt
   pip install -r harness/requirements.txt
   pip install -r requirements-dev.txt
   ```

## Pre-commit Hooks (Optional but Recommended)

Pre-commit hooks help catch issues before they reach CI, reducing feedback cycles.

### Installation

```bash
# Install pre-commit hooks
pre-commit install
```

This is **optional** - CI remains the source of truth. Hooks are for developer convenience.

### What the Hooks Do

The pre-commit configuration runs:
- **ruff format**: Auto-formats Python code (staged files only)
- **ruff check**: Lints Python code with auto-fix (staged files only)
- **trailing-whitespace**: Removes trailing whitespace
- **end-of-file-fixer**: Ensures files end with a newline
- **check-yaml/toml/json**: Validates syntax
- **check-merge-conflict**: Detects merge conflict markers
- **check-case-conflict**: Detects case-insensitive filename conflicts
- **gitleaks**: Scans for accidentally committed secrets

### Running Manually

```bash
# Run on all files
pre-commit run --all-files

# Run on staged files only (default on commit)
pre-commit run

# Run specific hook
pre-commit run ruff --all-files
```

### Updating Hooks

```bash
# Update to latest versions
pre-commit autoupdate

# Re-install after updating
pre-commit install
```

### Skipping Hooks

If you need to skip hooks (not recommended):
```bash
git commit --no-verify
```

**Note**: CI will still run all checks, so skipping hooks just delays feedback.

### Platform Compatibility

The pre-commit configuration is tested on:
- macOS
- Linux
- Windows (via WSL or Git Bash)

Hooks run in isolated environments for consistency.

## Quality Gates

### Local Validators

Run these before pushing to catch issues early:

```bash
# Lint and format checks
./scripts/lint.sh

# Type checking
./scripts/typecheck.sh

# Tests with coverage
./scripts/test.sh

# Security scan
./scripts/security-scan.sh
```

### CI Validators

GitHub Actions automatically runs on every PR:
- Lint checks (ruff)
- Type checking (mypy)
- Tests with coverage (pytest)
- Security scanning (pip-audit)
- Secret scanning (gitleaks)

All checks must pass before merge.

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_api_endpoints.py

# Run with coverage report
pytest --cov=server --cov=harness --cov-report=html

# Run tests matching a pattern
pytest -k "test_health"
```

### Test Organization

- `tests/` - Unit and integration tests for server and general code
- `harness/tests/` - Tests specific to harness functionality
- `tasks/*/tests/` - Per-task test suites (not run by default)

### Coverage

Current baseline: **24%**

Coverage reports are generated in `htmlcov/` directory.
View by opening `htmlcov/index.html` in a browser.

## Code Style

This project uses:
- **ruff** for linting and formatting (line length: 120)
- **mypy** for type checking (brownfield-safe configuration)

Configuration in `pyproject.toml`.

## Security

See [SECURITY.md](SECURITY.md) for:
- Dependency vulnerability scanning
- Secret scanning
- Security reporting process

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Run validators locally: `./scripts/lint.sh && ./scripts/typecheck.sh && ./scripts/test.sh`
4. Commit with descriptive messages
5. Push and create a PR
6. Wait for CI checks to pass
7. Request review

## Troubleshooting

### Virtual environment issues

```bash
# Delete and recreate
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt -r harness/requirements.txt -r requirements-dev.txt
```

### Pre-commit hook issues

```bash
# Reinstall hooks
pre-commit uninstall
pre-commit install

# Clear cache
pre-commit clean
```

### Test failures

```bash
# Run with verbose output
pytest -v

# Run with debugging
pytest --pdb

# See print statements
pytest -s
```
