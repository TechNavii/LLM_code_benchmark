# OpenAPI Diff - Breaking Change Detection

This document describes the OpenAPI diff tooling that detects breaking API changes by comparing the generated OpenAPI schema against a stored snapshot.

## Overview

The `scripts/openapi-diff.sh` script compares the current FastAPI OpenAPI schema against a committed snapshot (`docs/openapi-snapshot.json`) to detect breaking and additive API changes.

## Change Classification

### Breaking Changes (Fail CI)

The following changes are classified as **breaking** and will fail CI:

- **Removed endpoints** - Any path removed from the API
- **Removed HTTP methods** - e.g., removing DELETE from an existing endpoint
- **Removed schema properties** - Removing fields from request/response schemas
- **Removed schemas** - Removing component schemas entirely
- **Added required fields** - Adding new required fields without defaults
- **Type changes** - Changing field types (e.g., string to integer)
- **Validation tightening** - Adding stricter patterns, reducing enum values

### Additive Changes (Warn Only)

The following changes are classified as **additive** and will only warn (not fail):

- **New endpoints** - Adding new API paths
- **New HTTP methods** - Adding new methods to existing endpoints
- **New optional fields** - Adding optional properties to schemas
- **New schemas** - Adding new component schemas
- **Loosened validation** - Making fields optional, adding enum values
- **Metadata changes** - Version, title, description updates

## Usage

### Check for Breaking Changes

```bash
# Run diff check (fails on breaking changes, warns on additive)
./scripts/openapi-diff.sh

# Run strict mode (fails on any change)
./scripts/openapi-diff.sh --strict
```

### Update the Snapshot

When you intentionally make API changes (breaking or additive), update the snapshot:

```bash
# Update the snapshot with current schema
./scripts/openapi-diff.sh --update

# Then commit the updated snapshot
git add docs/openapi-snapshot.json
git commit -m "Update OpenAPI snapshot for API changes"
```

## CI Integration

The diff check runs in the Quality Gates CI workflow:

1. **Validate OpenAPI schema** - Ensures the schema is valid OpenAPI 3.x
2. **Check for OpenAPI breaking changes** - Compares against snapshot

If breaking changes are detected, CI will fail with a clear message listing each breaking change.

## Workflow for API Changes

### Non-Breaking Changes (Additive)

1. Make your changes (add endpoints, optional fields, etc.)
2. Run `./scripts/openapi-diff.sh` to see the detected changes
3. If satisfied, update the snapshot: `./scripts/openapi-diff.sh --update`
4. Commit both your code changes and the updated snapshot

### Breaking Changes

1. Make your changes
2. Run `./scripts/openapi-diff.sh` to see the breaking changes
3. Consider if there's a non-breaking alternative (e.g., deprecation period)
4. If the breaking change is intentional:
   - Update the snapshot: `./scripts/openapi-diff.sh --update`
   - Document the breaking change in your PR description
   - Consider versioning the API if major changes are made
5. Commit both your code changes and the updated snapshot

## Implementation Details

The diff algorithm:

1. Generates the current OpenAPI schema using `create_app().openapi()`
2. Loads the snapshot from `docs/openapi-snapshot.json`
3. Performs deep comparison of paths, methods, schemas, and properties
4. Classifies each difference as breaking or additive
5. Reports findings and returns appropriate exit code

The process is **hermetic**:
- No network calls
- No task execution
- No external API dependencies
- Uses only the FastAPI app factory

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | No changes, or only additive changes (warn-only mode) |
| 1 | Breaking changes detected |
| 2 | Configuration or setup error |

## Related Files

- `scripts/openapi-diff.sh` - Main diff script
- `scripts/openapi-validate.sh` - Schema validation script
- `docs/openapi-snapshot.json` - Stored OpenAPI snapshot
