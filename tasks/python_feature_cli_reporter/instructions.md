# Task: Implement reporting CLI helpers

The reporting CLI receives newline-separated records with comma-separated fields:
```
assignee, stage, duration_minutes
```

Implement the modules in `reporting/` so that `cli.generate_report` returns a human-readable report with:
- Total number of tasks
- Counts per stage (sorted alphabetically by stage)
- Average duration (one decimal place)

Requirements:
- Ignore blank lines and surrounding whitespace.
- Validate that each duration is a positive integer; raise `ValueError` otherwise.
- Treat stage names case-insensitively when counting (normalize to lowercase keys).
- Keep the code modular: parsing lives in `loader.py`, formatting in `formatting.py`, and `cli.py` orchestrates the flow.

Do not change the public API or the tests.

## Testing
```
pytest -q
```
