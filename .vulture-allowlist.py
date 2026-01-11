# Vulture allowlist for known false positives
# This file documents intentional "unused" code that should not be flagged

# Pydantic validators use 'cls' parameter by convention (required by framework)
# These are called by Pydantic's internal machinery
_.cls  # Pydantic validator method parameter

# SQLAlchemy Column import used for type hints and may be used in future schema definitions
_.Column  # SQLAlchemy Column import

# Type checking imports used by mypy/type checkers (not runtime)
_.Coroutine  # Type hint import for async type checking

# Brownfield imports that may be needed for future functionality
# TODO: Incrementally review and remove if truly unused
_.defaultdict  # harness/run_harness.py - imported but not currently used
