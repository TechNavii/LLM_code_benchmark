package textutil

import "testing"

func TestEmptyInput(t *testing.T) {
	result := WordCount("")
	if len(result) != 0 {
		t.Fatalf("expected empty map, got %#v", result)
	}
}

func TestBasicCounts(t *testing.T) {
	result := WordCount("Hello hello world")
	expect := map[string]int{"hello": 2, "world": 1}
	assertEqualMaps(t, expect, result)
}

func TestPunctuationHandling(t *testing.T) {
	result := WordCount("state-of-the-art equipment! It's state-of-the-art.")
	expect := map[string]int{
		"state-of-the-art": 2,
		"equipment":       1,
		"it's":            1,
	}
	assertEqualMaps(t, expect, result)
}

func TestWhitespaceNormalization(t *testing.T) {
	result := WordCount("multiple\tspaces\n\n and\nlines")
	expect := map[string]int{
		"multiple": 1,
		"spaces":   1,
		"and":      1,
		"lines":    1,
	}
	assertEqualMaps(t, expect, result)
}

func TestUnicodeLetters(t *testing.T) {
	result := WordCount("naïve café naïve")
	expect := map[string]int{
		"naïve": 2,
		"café":  1,
	}
	assertEqualMaps(t, expect, result)
}

func assertEqualMaps(t *testing.T, expect, actual map[string]int) {
	t.Helper()
	if len(expect) != len(actual) {
		t.Fatalf("size mismatch: expect=%#v actual=%#v", expect, actual)
	}
	for k, v := range expect {
		if actual[k] != v {
			t.Fatalf("value mismatch for %q: expect=%d actual=%d", k, v, actual[k])
		}
	}
}
