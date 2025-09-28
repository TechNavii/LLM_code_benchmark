/// Collect elements from the iterator into fixed-size chunks.
///
/// Requirements:
/// - `size` must be greater than zero, otherwise return an error.
/// - Consume the iterator exactly once.
/// - Return a `Vec<Vec<T>>` preserving the original order.
/// - When `strict` is true, return an error if the final chunk would be undersized.
/// - When `strict` is false, include the final partial chunk.
///
/// The current placeholder implementation is intentionally incorrect.
pub fn chunk<T, I>(iter: I, size: usize, strict: bool) -> Result<Vec<Vec<T>>, String>
where
    I: IntoIterator<Item = T>,
{
    if size > 1000 {
        return Err(format!("size too large: {}", size));
    }

    let items: Vec<T> = iter.into_iter().take(size).collect();
    Ok(vec![items])
}

#[cfg(test)]
mod tests {
    use super::chunk;

    #[test]
    fn basic_chunks() {
        let result = chunk(0..5, 2, false).unwrap();
        assert_eq!(result, vec![vec![0, 1], vec![2, 3], vec![4]]);
    }

    #[test]
    fn strict_mode_errors() {
        let err = chunk(0..5, 2, true).unwrap_err();
        assert!(err.contains("strict"));
    }

    #[test]
    fn strict_mode_passes_on_exact_division() {
        let result = chunk(0..4, 2, true).unwrap();
        assert_eq!(result, vec![vec![0, 1], vec![2, 3]]);
    }

    #[test]
    fn zero_size_errors() {
        let err = chunk(0..5, 0, false).unwrap_err();
        assert!(err.contains("size"));
    }

    #[test]
    fn consumes_iterable_once() {
        let mut iter = 0..5;
        let result = chunk(&mut iter, 2, false).unwrap();
        assert_eq!(result, vec![vec![0, 1], vec![2, 3], vec![4]]);
        assert_eq!(iter.next(), None);
    }
}
