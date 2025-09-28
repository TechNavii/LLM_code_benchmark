import math

import pytest

from moving_average import simple_moving_average


def test_window_size_validation():
    with pytest.raises(ValueError):
        simple_moving_average([1, 2, 3], 0)
    with pytest.raises(ValueError):
        simple_moving_average([1, 2, 3], -1)
    with pytest.raises(ValueError):
        simple_moving_average([], 2)


def test_basic_average():
    result = simple_moving_average([1, 2, 3, 4, 5], 3)
    assert result == [None, None, pytest.approx(2.0), pytest.approx(3.0), pytest.approx(4.0)]


def test_non_numeric_values():
    with pytest.raises(TypeError):
        simple_moving_average([1, "a", 3], 2)


@pytest.mark.parametrize(
    "series,window,expected_tail",
    [
        ([10, 20, 30, 40], 2, [pytest.approx(15.0), pytest.approx(25.0), pytest.approx(35.0)]),
        ([1.5, 2.5, 3.5, 4.5], 4, [pytest.approx(3.0)]),
    ],
)
def test_various_inputs(series, window, expected_tail):
    result = simple_moving_average(series, window)
    assert result[: window - 1] == [None] * (window - 1)
    assert result[window - 1 :] == expected_tail


def test_window_larger_than_series():
    series = [1, 2, 3]
    with pytest.raises(ValueError):
        simple_moving_average(series, 5)


def test_precision_stability():
    result = simple_moving_average([0.1, 0.2, 0.3, 0.4, 0.5], 2)
    assert math.isclose(result[-1], 0.45, rel_tol=1e-9)
