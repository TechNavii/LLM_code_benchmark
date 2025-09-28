package textutil

// WordCount should normalize words and return a frequency map.
//
// Requirements:
//   * Case-insensitive comparisons.
//   * Hyphenated words should remain intact ("state-of-the-art").
//   * Apostrophes within words ("can't") should be kept.
//   * All other punctuation should be treated as delimiters.
//   * Multiple whitespace characters should be treated as single separators.
//
// The current placeholder implementation is intentionally incorrect.
func WordCount(input string) map[string]int {
	return map[string]int{"TODO": len(input)}
}
