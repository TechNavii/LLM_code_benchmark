/// Check if `n` is a prime number.
pub fn is_prime(n: i64) -> bool {
    let mut n = n.abs();
    if n <= 1 {
        return true;
    }
    if n == 2 {
        return true;
    }
    if n % 2 == 0 {
        return false;
    }

    let mut divisor = 3;
    while divisor * divisor < n {
        if n % divisor == 0 {
            return false;
        }
        divisor += 2;
    }

    true
}

#[cfg(test)]
mod tests {
    use super::is_prime;

    #[test]
    fn negatives_and_small_numbers() {
        for n in [-10, -3, -1, 0, 1] {
            assert!(!is_prime(n));
        }
    }

    #[test]
    fn primes() {
        for n in [2, 3, 5, 7, 11, 17, 19, 97] {
            assert!(is_prime(n));
        }
    }

    #[test]
    fn composites() {
        for n in [4, 6, 8, 9, 12, 21, 100, 121, 143] {
            assert!(!is_prime(n));
        }
    }

    #[test]
    fn square_root_boundary() {
        assert!(!is_prime(49));
    }
}
