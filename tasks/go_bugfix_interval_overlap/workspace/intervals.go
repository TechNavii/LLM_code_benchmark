package intervals

// Interval represents a half-open interval [Start, End).
type Interval struct {
	Start float64
	End   float64
}

// HasOverlap returns true when the two intervals share any interior points.
//
// BUG: the current implementation mishandles touching boundaries.
func HasOverlap(a, b Interval) bool {
	if a.Start >= a.End || b.Start >= b.End {
		panic("invalid interval")
	}

	if a.Start > b.Start {
		a, b = b, a
	}

	return a.End >= b.Start
}
