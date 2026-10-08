import math
import struct

import pytest

from quantic_agent import memory


def test_a_vector_is_stored_as_little_endian_float32() -> None:
    blob = memory.encode([1.0, -0.5, 0.1])
    assert len(blob) == 3 * 4
    assert struct.unpack("<3f", blob) == pytest.approx((1.0, -0.5, 0.1))
    # float32 keeps about seven significant digits, which is plenty for a
    # direction; it halves the storage of a Python float.
    assert list(memory.decode(blob)) == pytest.approx([1.0, -0.5, 0.1], rel=1e-7)


@pytest.mark.parametrize(
    ("a", "b", "want"),
    [
        pytest.param([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], 1.0, id="the same"),
        pytest.param([1.0, 2.0, 3.0], [10.0, 20.0, 30.0], 1.0, id="length doesn't matter"),
        pytest.param([1.0, 0.0], [0.0, 1.0], 0.0, id="unrelated"),
        pytest.param([1.0, 2.0], [-1.0, -2.0], -1.0, id="opposite"),
    ],
)
def test_cosine(a: list[float], b: list[float], want: float) -> None:
    assert memory.cosine(a, b) == pytest.approx(want)


def test_vectors_of_different_models_dont_compare() -> None:
    with pytest.raises(ValueError, match="768 and 1024"):
        memory.cosine([0.0] * 768, [0.0] * 1024)


def test_unit() -> None:
    assert memory.unit([3.0, 4.0]) == pytest.approx([0.6, 0.8])
    v = memory.unit([1.0, 2.0, 2.0])
    assert math.sumprod(v, v) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="zero vector"):
        memory.unit([0.0, 0.0])


def test_nearest_most_similar_first() -> None:
    stored = [
        memory.Memory(1, "east", memory.unit([1.0, 0.0])),
        memory.Memory(2, "north-east", memory.unit([1.0, 1.0])),
        memory.Memory(3, "west", memory.unit([-1.0, 0.0])),
    ]
    # The query needn't be a unit vector: nearest scales it.
    found = memory.nearest([5.0, 4.0], stored, k=2)
    assert [m.memory.text for m in found] == ["north-east", "east"]
    assert found[0].score == pytest.approx(memory.cosine([5.0, 4.0], [1.0, 1.0]))
