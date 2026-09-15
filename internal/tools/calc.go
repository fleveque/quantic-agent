// Package tools holds the tools the research loop can call.
//
// So far that is only the deterministic calculators from design §3.3. When a
// draft needs a derived figure — a percentage change, a difference, a total —
// the model calls one of these instead of doing the arithmetic itself, so the
// result enters the provenance manifest like any other tool response.
package tools

import "errors"

// PctChange returns the percentage change from previous to current, as a
// percentage: 1.50 → 1.55 is 3.33…, not 0.0333….
//
// previous must be positive. A zero base has no percentage change, and a
// negative one produces a sign that reads backwards (−2 → −1 is "−50%"). Both
// are refused: a calculator that declines leaves the draft without a figure,
// which is safe; one that returns a misleading figure is not.
//
// The result is full float64 precision. Rounding is presentation, and
// presentation belongs to the Phoenix template (see docs/rendering.md).
func PctChange(previous, current float64) (float64, error) {
	if previous <= 0 {
		return 0, errors.New("tools: pct_change needs a positive previous value")
	}
	return (current - previous) / previous * 100, nil
}

// Diff returns current minus previous.
func Diff(previous, current float64) float64 {
	return current - previous
}

// Sum returns the total of values. The sum of no values is 0.
func Sum(values ...float64) float64 {
	var total float64
	for _, v := range values {
		total += v
	}
	return total
}
