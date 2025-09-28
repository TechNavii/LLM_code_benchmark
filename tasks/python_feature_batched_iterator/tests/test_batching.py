import itertools

import pytest

from batching import batched


def test_invalid_size():
    with pytest.raises(ValueError):
        batched([1, 2, 3], 0)
    with pytest.raises(ValueError):
        batched([1, 2], -5)

    with pytest.raises(TypeError):
        batched([1], 2.5)


def test_basic_batches_tuple_default():
    items = [1, 2, 3, 4, 5]
    result = batched(items, 2)
    assert result == [(1, 2), (3, 4), (5,)]


def test_list_batches_when_requested():
    items = ["a", "b", "c", "d"]
    result = batched(items, 3, as_tuple=False)
    assert result == [["a", "b", "c"], ["d"]]


def test_strict_mode_errors_on_incomplete_batch():
    with pytest.raises(ValueError):
        batched([1, 2, 3, 4, 5], 2, strict=True)

    # should still succeed when divisible
    assert batched([1, 2, 3, 4], 2, strict=True) == [(1, 2), (3, 4)]


def test_consumes_iterable_once():
    iterator = iter(range(5))
    result = batched(iterator, 2)
    assert list(iterator) == []
    assert result == [(0, 1), (2, 3), (4,)]


def test_handles_iterable_without_len():
    counter = itertools.count(1)
    values = list(batched(itertools.islice(counter, 5), 2))
    assert values == [(1, 2), (3, 4), (5,)]


def test_strict_mode_allows_exact_batches():
    letters = "abcdefghijkl"
    result = batched(letters, 3, strict=True)
    assert result == [("a", "b", "c"), ("d", "e", "f"), ("g", "h", "i"), ("j", "k", "l")]


def test_empty_iterable_returns_empty_list():
    assert batched([], 3) == []


def test_generator_input_produces_sequences():
    def gen():
        for number in range(5):
            yield number * number

    output = batched(gen(), 4, as_tuple=False)
    assert output == [[0, 1, 4, 9], [16]]
