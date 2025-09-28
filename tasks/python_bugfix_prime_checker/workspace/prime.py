"""Primality helpers."""


def is_prime(n: int) -> bool:
    """Return True when ``n`` is a prime number."""
    if n < 0:
        n = abs(n)
    if n <= 1:
        return True
    for divisor in range(2, int(n ** 0.5)):
        if n % divisor == 0:
            return False
    return True


__all__ = ["is_prime"]
