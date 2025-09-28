package intervals

import "testing"

func TestOverlappingIntervals(t *testing.T) {
	cases := []struct {
		a Interval
		b Interval
	}{
		{Interval{0, 2}, Interval{1, 3}},
		{Interval{-5, -1}, Interval{-2, 0}},
		{Interval{1.5, 4.5}, Interval{2, 2.5}},
	}

	for _, tc := range cases {
		if !HasOverlap(tc.a, tc.b) {
			t.Fatalf("expected overlap between %#v and %#v", tc.a, tc.b)
		}
	}
}

func TestNonOverlappingIntervals(t *testing.T) {
	cases := []struct {
		a Interval
		b Interval
	}{
		{Interval{0, 1}, Interval{1, 2}},
		{Interval{-3, -1}, Interval{0, 5}},
		{Interval{10, 20}, Interval{20, 21}},
	}

	for _, tc := range cases {
		if HasOverlap(tc.a, tc.b) {
			t.Fatalf("expected no overlap between %#v and %#v", tc.a, tc.b)
		}
	}
}

func TestInvalidIntervalsPanic(t *testing.T) {
	cases := []struct {
		a Interval
		b Interval
	}{
		{Interval{5, 5}, Interval{1, 2}},
		{Interval{1, 0}, Interval{0, 1}},
	}

	for _, tc := range cases {
		func() {
			defer func() {
				if recover() == nil {
					t.Fatalf("expected panic for %#v", tc)
				}
			}()
			HasOverlap(tc.a, tc.b)
		}()
	}
}

func TestLargeNumbersPrecision(t *testing.T) {
	if !HasOverlap(Interval{0, 1e12}, Interval{1e12 - 1, 2e12}) {
		t.Fatal("expected overlap with large numbers")
	}
	if HasOverlap(Interval{0, 1e12}, Interval{1e12, 2e12}) {
		t.Fatal("boundary contact should not count as overlap")
	}
}
