from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Sequence


def compute_schedule(definitions: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Return timing metadata for the given workflow definitions.

    Implemented by the participant. See instructions for the required behaviour.
    """
    raise NotImplementedError("compute_schedule is not implemented yet")
