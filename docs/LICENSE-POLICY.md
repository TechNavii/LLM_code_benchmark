# License Compliance Policy

This document describes the license compliance scanning policy for the benchmark repository.

## Overview

The project uses `pip-licenses` to scan Python dependencies for license compliance. This ensures all dependencies use licenses compatible with the project's use case.

## Running License Scans

```bash
# Run the license scan
./scripts/license-scan.sh

# View the generated license inventory
cat docs/license-inventory.txt
```

## Approved Licenses

The following license families are pre-approved for use:

### Fully Approved (Permissive)
- **MIT** / **MIT-0**: Permissive, commercial-friendly
- **BSD-2-Clause** / **BSD-3-Clause**: Permissive, commercial-friendly
- **Apache-2.0**: Permissive, includes patent grant
- **ISC**: Functionally equivalent to MIT
- **PSF-2.0**: Python Software Foundation License
- **Unlicense** / **CC0** / **WTFPL**: Public domain dedications
- **Zlib**: Permissive, similar to MIT

### Conditionally Approved (Weak Copyleft)
- **LGPL-2.1** / **LGPL-3.0**: Allowed for dynamically-linked libraries
- **MPL-2.0**: Allowed, file-level copyleft only

## Denied Licenses

The following licenses require explicit approval before use:

- **GPL-2.0** / **GPL-3.0**: Strong copyleft, may require source disclosure
- **AGPL-3.0**: Network copyleft, strict requirements for server software

If a dependency uses a denied license, it must be:
1. Reviewed for compatibility with project use
2. Added to `.license-policy.txt` with justification
3. Approved by project maintainers

## Unknown Licenses

Packages with `UNKNOWN` or unrecognized licenses require manual review:

1. Check the package's repository for license information
2. If permissive, add the license to the allowed list in `scripts/license-scan.sh`
3. If restricted, add to denied list or request an exception
4. Document the decision in `.license-policy.txt`

## Adding Exceptions

To add a license exception for a specific package:

1. Review the license terms and usage requirements
2. Add the package name to `.license-policy.txt`
3. Include a comment explaining why the exception is acceptable
4. Example:

```
# gpl-dev-tool - Only used for development, not distributed with product
gpl-dev-tool
```

## License Inventory

The full license inventory is generated at `docs/license-inventory.txt` and includes:
- Package name and version
- License identifier
- Project URL
- Author information

This inventory is regenerated on each scan.

## CI Integration

License scanning runs in CI as part of the quality gates workflow:
- Denied licenses cause build failure
- Unknown licenses generate warnings (warn-only for brownfield adoption)
- The license inventory is generated but not committed (regenerated on demand)

## Updating Dependencies

When adding or updating dependencies:

1. Run `./scripts/license-scan.sh` locally
2. Review any new packages or license changes
3. Address any denied or unknown licenses before committing
4. Update `.license-policy.txt` if exceptions are needed

## Related Files

- `scripts/license-scan.sh`: License scanning script
- `.license-policy.txt`: Package-specific exceptions
- `docs/license-inventory.txt`: Generated license inventory (not committed)
