import pytest

from intervals import Interval, has_overlap


@pytest.mark.parametrize(
    "interval_a, interval_b",
    [
        ((0.0, 2.0), (1.0, 3.0)),
        ((-5.0, -1.0), (-2.0, 0.0)),
        ((1.5, 4.5), (2.0, 2.5)),
    ],
)
def test_overlapping_intervals(interval_a: Interval, interval_b: Interval):
    assert has_overlap(interval_a, interval_b) is True


@pytest.mark.parametrize(
    "interval_a, interval_b",
    [
        ((0.0, 1.0), (1.0, 2.0)),  # touching at boundary should not count
        ((-3.0, -1.0), (0.0, 5.0)),
        ((10.0, 20.0), (20.0, 30.0)),
    ],
)
def test_non_overlapping_intervals(interval_a: Interval, interval_b: Interval):
    assert has_overlap(interval_a, interval_b) is False


@pytest.mark.parametrize(
    "interval_a, interval_b",
    [
        ((5.0, 5.0), (1.0, 2.0)),
        ((1.0, 0.0), (0.0, 1.0)),
    ],
)
def test_invalid_intervals_raise(interval_a: Interval, interval_b: Interval):
    with pytest.raises(ValueError):
        has_overlap(interval_a, interval_b)


def test_large_numbers_precision():
    assert has_overlap((0.0, 1e12), (1e12 - 1, 2e12)) is True
    assert has_overlap((0.0, 1e12), (1e12, 2e12)) is False
