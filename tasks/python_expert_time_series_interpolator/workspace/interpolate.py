from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

Sample = Tuple[int, float]


def interpolate_series(samples: Sequence[Sample], interval: int, *, method: str = "linear") -> List[Sample]:
    """Return a resampled series at a fixed interval.

    Implementation required by the participant. Refer to the instructions for
    the full contract.
    """
    raise NotImplementedError("interpolate_series is not implemented yet")
