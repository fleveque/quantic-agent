package tools_test

import (
	"math"
	"testing"

	"github.com/fleveque/quantic-agent/internal/tools"
)

// Float results are compared within a tolerance, never with ==. Values like
// 1.55 have no exact float64 representation, so correct arithmetic routinely
// lands a few ulps away from the decimal answer a human would write down.
const epsilon = 1e-9

func approxEqual(a, b float64) bool {
	return math.Abs(a-b) <= epsilon
}

func TestPctChange(t *testing.T) {
	tests := []struct {
		name              string
		previous, current float64
		want              float64
	}{
		{name: "raise", previous: 1.50, current: 1.55, want: 10.0 / 3},
		{name: "cut in half", previous: 0.80, current: 0.40, want: -50},
		{name: "unchanged", previous: 2.00, current: 2.00, want: 0},
		{name: "suspended", previous: 0.25, current: 0, want: -100},
		{name: "doubled", previous: 0.2695, current: 0.539, want: 100},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := tools.PctChange(tt.previous, tt.current)
			if err != nil {
				t.Fatalf("PctChange(%v, %v) returned error: %v", tt.previous, tt.current, err)
			}
			if !approxEqual(got, tt.want) {
				t.Errorf("PctChange(%v, %v) = %v, want %v", tt.previous, tt.current, got, tt.want)
			}
		})
	}
}

func TestPctChangeRefusesNonPositiveBase(t *testing.T) {
	tests := []struct {
		name              string
		previous, current float64
	}{
		{name: "zero base", previous: 0, current: 1.25},
		{name: "negative base", previous: -2, current: -1},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := tools.PctChange(tt.previous, tt.current)
			if err == nil {
				t.Fatalf("PctChange(%v, %v) = %v, want an error", tt.previous, tt.current, got)
			}
		})
	}
}

func TestDiff(t *testing.T) {
	tests := []struct {
		name              string
		previous, current float64
		want              float64
	}{
		{name: "raise", previous: 1.50, current: 1.55, want: 0.05},
		{name: "cut", previous: 0.80, current: 0.40, want: -0.40},
		{name: "unchanged", previous: 2.00, current: 2.00, want: 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tools.Diff(tt.previous, tt.current)
			if !approxEqual(got, tt.want) {
				t.Errorf("Diff(%v, %v) = %v, want %v", tt.previous, tt.current, got, tt.want)
			}
		})
	}
}

func TestSum(t *testing.T) {
	tests := []struct {
		name   string
		values []float64
		want   float64
	}{
		{name: "no values", values: nil, want: 0},
		{name: "one value", values: []float64{0.83}, want: 0.83},
		{name: "a year of quarterly payments", values: []float64{0.83, 0.83, 0.83, 0.91}, want: 3.40},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := tools.Sum(tt.values...)
			if !approxEqual(got, tt.want) {
				t.Errorf("Sum(%v) = %v, want %v", tt.values, got, tt.want)
			}
		})
	}
}
