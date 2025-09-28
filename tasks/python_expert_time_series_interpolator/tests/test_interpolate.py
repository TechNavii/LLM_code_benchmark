import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "workspace"))

from interpolate import interpolate_series


def test_linear_interpolation_multiple_segments():
    samples = [(0, 0.0), (4, 2.0), (8, 6.0)]
    resampled = interpolate_series(samples, 2)
    expected = [
        (0, 0.0),
        (2, 1.0),
        (4, 2.0),
        (6, 4.0),
        (8, 6.0),
    ]
    assert resampled == pytest.approx(expected)
    # Ensure the source list was not mutated.
    assert samples == [(0, 0.0), (4, 2.0), (8, 6.0)]


def test_linear_interpolation_handles_dense_points():
    samples = [(10, 50.0), (12, 62.0), (16, 94.0)]
    resampled = interpolate_series(samples, 2)
    expected = [
        (10, 50.0),
        (12, 62.0),
        (14, 78.0),
        (16, 94.0),
    ]
    assert resampled == pytest.approx(expected)


def test_forward_fill_mode():
    samples = [(0, 100.0), (6, 160.0)]
    resampled = interpolate_series(samples, 2, method="forward_fill")
    assert resampled == [
        (0, 100.0),
        (2, 100.0),
        (4, 100.0),
        (6, 160.0),
    ]


def test_forward_fill_requires_leading_value():
    samples = [(4, 10.0), (8, 20.0)]
    with pytest.raises(ValueError):
        interpolate_series(samples, 2, method="forward_fill")


def test_invalid_interval_raises():
    with pytest.raises(ValueError):
        interpolate_series([(0, 1.0), (2, 3.0)], 0)


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        interpolate_series([(0, 1.0), (2, 3.0)], 2, method="nearest")
