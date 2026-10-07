"""The tools the research loop can call.

So far that is only the deterministic calculators from design §3.3. When a
draft needs a derived figure (a percentage change, a difference, a total), the
model calls one of these instead of doing the arithmetic itself, so the result
enters the provenance manifest like any other tool response.

The results are full float precision. Rounding is presentation, and
presentation belongs to the Phoenix template (docs/rendering.md).
"""


def pct_change(previous: float, current: float) -> float:
    """The percentage change from previous to current: 1.50 → 1.55 is 3.33…, not 0.0333….

    previous must be positive. A zero base has no percentage change, and a
    negative one produces a sign that reads backwards (-2 → -1 is "-50%").
    Both are refused: a calculator that declines leaves the draft without a
    figure, which is safe; one that returns a misleading figure is not.
    """
    if previous <= 0:
        raise ValueError(f"pct_change needs a positive previous value, got {previous}")
    return (current - previous) / previous * 100


def diff(previous: float, current: float) -> float:
    """current minus previous."""
    return current - previous


def total(*values: float) -> float:
    """The sum of values. The sum of no values is 0.

    Named total so it doesn't hide the built-in sum, which it uses: since
    Python 3.12, sum() of floats compensates for rounding as it adds.
    """
    return sum(values, 0.0)
