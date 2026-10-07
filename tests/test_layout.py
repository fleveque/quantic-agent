"""The layout is the one thing milestone 0 has to get right."""

from pathlib import Path

import quantic_agent

ROOT = Path(__file__).resolve().parent.parent


def test_the_package_under_test_is_the_one_in_src() -> None:
    # Tests must import the package the way an installed program would, not
    # whatever happens to sit in the working directory. With the code under
    # src/, the only way to import it is to install it (uv sync does, in
    # editable mode), so this passing means the install points here.
    assert Path(quantic_agent.__file__).resolve().parent == ROOT / "src" / "quantic_agent"
