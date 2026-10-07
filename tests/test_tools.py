import pytest

from quantic_agent import tools


def approx(want: float) -> object:
    """want, give or take a billionth.

    Floats are compared within a tolerance, never with ==: values like 1.55
    have no exact binary representation, so correct arithmetic routinely lands
    a few units in the last place away from the decimal a person would write.
    abs= alone makes the tolerance absolute; pytest's default is relative
    (a millionth of want), which would be looser than this for any figure
    above 0.001.
    """
    return pytest.approx(want, abs=1e-9)


@pytest.mark.parametrize(
    ("previous", "current", "want"),
    [
        pytest.param(1.50, 1.55, 10 / 3, id="raise"),
        pytest.param(0.80, 0.40, -50, id="cut in half"),
        pytest.param(2.00, 2.00, 0, id="unchanged"),
        pytest.param(0.25, 0, -100, id="suspended"),
        pytest.param(0.2695, 0.539, 100, id="doubled"),
    ],
)
def test_pct_change(previous: float, current: float, want: float) -> None:
    assert tools.pct_change(previous, current) == approx(want)


@pytest.mark.parametrize(
    ("previous", "current"),
    [
        pytest.param(0, 1.25, id="zero base"),
        pytest.param(-2, -1, id="negative base"),
    ],
)
def test_pct_change_refuses_a_base_that_is_not_positive(previous: float, current: float) -> None:
    with pytest.raises(ValueError, match="positive previous value"):
        tools.pct_change(previous, current)


@pytest.mark.parametrize(
    ("previous", "current", "want"),
    [
        pytest.param(1.50, 1.55, 0.05, id="raise"),
        pytest.param(0.80, 0.40, -0.40, id="cut"),
        pytest.param(2.00, 2.00, 0, id="unchanged"),
    ],
)
def test_diff(previous: float, current: float, want: float) -> None:
    assert tools.diff(previous, current) == approx(want)


@pytest.mark.parametrize(
    ("values", "want"),
    [
        pytest.param((), 0, id="no values"),
        pytest.param((0.83,), 0.83, id="one value"),
        pytest.param((0.83, 0.83, 0.83, 0.91), 3.40, id="a year of quarterly payments"),
    ],
)
def test_total(values: tuple[float, ...], want: float) -> None:
    assert tools.total(*values) == approx(want)
