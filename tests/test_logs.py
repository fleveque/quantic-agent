import io
import logging
import os
from pathlib import Path

import pytest

from quantic_agent import logs
from quantic_agent.cli import main


def record(level: int, message: str, **extra: object) -> logging.LogRecord:
    rec = logs.LOGGER.makeRecord("quantic_agent", level, __file__, 0, message, (), None)
    for key, value in extra.items():
        setattr(rec, key, value)
    return rec


def test_a_terminal_reads_the_message_as_before() -> None:
    plain = logs.Plain()
    assert plain.format(record(logging.ERROR, "run 3 failed")) == "quantic-agent: run 3 failed"
    # A tool call's trace line has always been bare.
    bare = record(logging.INFO, 'tool get_stock {"symbol": "KO"}', **logs.fields(bare=True))
    assert plain.format(bare) == 'tool get_stock {"symbol": "KO"}'


@pytest.mark.parametrize(
    ("level", "priority"),
    [(logging.INFO, "<6>"), (logging.WARNING, "<4>"), (logging.ERROR, "<3>")],
)
def test_the_journal_gets_the_priority_and_the_fields(level: int, priority: str) -> None:
    rec = record(level, "run 3 answered", **logs.fields(run=3, state="answered"))
    assert logs.Journal().format(rec) == f"{priority}run 3 answered run=3 state=answered"


def test_a_value_that_would_break_key_value_is_quoted() -> None:
    values = logs.fields(locale="ca", problems='summary: figure "3"', empty="")
    line = logs.Journal().format(record(logging.WARNING, "ca: held", **values))
    assert line == '<4>ca: held locale=ca problems="summary: figure \\"3\\"" empty=""'


def test_every_line_of_a_long_message_has_its_priority() -> None:
    line = logs.Journal().format(record(logging.ERROR, "first\nsecond", **logs.fields(run=1)))
    assert line == "<3>first\n<3>second run=1"


def test_the_journal_is_the_stream_systemd_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with (tmp_path / "stderr").open("w") as stream:
        st = os.fstat(stream.fileno())
        monkeypatch.setenv("JOURNAL_STREAM", f"{st.st_dev}:{st.st_ino}")
        assert logs.to_journal(stream)
        with (tmp_path / "other").open("w") as other:
            assert not logs.to_journal(other)  # redirected: not the journal
    assert not logs.to_journal(io.StringIO())  # no file behind it
    monkeypatch.delenv("JOURNAL_STREAM")
    with (tmp_path / "stderr").open("w") as stream:
        assert not logs.to_journal(stream)  # not under systemd at all


def test_under_systemd_the_agent_writes_journal_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "stderr"
    with path.open("w") as stream:
        st = os.fstat(stream.fileno())
        monkeypatch.setenv("JOURNAL_STREAM", f"{st.st_dev}:{st.st_ino}")
        monkeypatch.setattr("sys.stderr", stream)
        assert main(["--approve", "5"]) == 1
    assert path.read_text() == "<3>there is no run 5\n"
