import math

import pytest

from prime import is_prime


@pytest.mark.parametrize("n", [-10, -3, -1, 0, 1])
def test_non_positive_integers_are_not_prime(n):
    assert is_prime(n) is False


@pytest.mark.parametrize("n", [2, 3, 5, 7, 11, 17, 19, 97])
def test_primes_return_true(n):
    assert is_prime(n) is True


@pytest.mark.parametrize("n", [4, 6, 8, 9, 12, 21, 100, 121, 143])
def test_composite_numbers_return_false(n):
    assert is_prime(n) is False


def test_large_prime_boundary():
    # 997 is prime, 999 is not
    assert is_prime(997) is True
    assert is_prime(999) is False


def test_high_square_root_checks():
    # ensures range upper bound includes sqrt(n)
    assert is_prime(49) is False


def test_input_type_validation():
    with pytest.raises(TypeError):
        is_prime(3.14)

    with pytest.raises(TypeError):
        is_prime("5")


def test_memory_of_previous_calls():
    # ensure function has no hidden state by calling sequentially
    results = [is_prime(x) for x in [2, 4, 5, 6, 7]]
    assert results == [True, False, True, False, True]
