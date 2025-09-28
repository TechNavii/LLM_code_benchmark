"""Helpers for splitting iterables into fixed-size batches."""

from typing import Iterable, Iterator, List, Sequence, Tuple, TypeVar

T = TypeVar("T")


def batched(source: Iterable[T], size: int, *, as_tuple: bool = True, strict: bool = False) -> List[Sequence[T]]:
    """Split ``source`` into chunks of ``size``.

    Parameters
    ----------
    source:
        Any finite iterable of elements.
    size:
        Positive integer describing the chunk size.
    as_tuple:
        When True (default) batches should be returned as tuples; otherwise lists.
    strict:
        When True, raise ``ValueError`` if the final batch would be undersized.

    The current placeholder implementation is intentionally incorrect.
    """

    del source, size, as_tuple, strict
    return []


__all__ = ["batched"]
