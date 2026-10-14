"""What the agent says on stderr, through the standard library's logging.

One logger, "quantic_agent", and two ways to write a message. In a terminal
it reads as it always has: "quantic-agent: run 3 answered". Under systemd,
which connects a service's stderr to the journal, each line starts with its
syslog priority ("<6>"), which journald takes as the entry's level, and ends
with the event's fields as key=value pairs:

    <6>run 3 answered run=3 state=answered

so journalctl -p warning shows what went wrong, and grep run=3 one run's
lines. The database stays the audit log (design N3); this is the account of
what the process did, kept by the journal with the rest of the system's.
"""

import io
import json
import logging
import os
import sys
from typing import Any, TextIO

LOGGER = logging.getLogger("quantic_agent")
PREFIX = "quantic-agent: "

# The syslog priorities journald reads from a "<N>" prefix (sd-daemon(3)).
_PRIORITY = {
    logging.DEBUG: 7,
    logging.INFO: 6,
    logging.WARNING: 4,
    logging.ERROR: 3,
    logging.CRITICAL: 2,
}


def fields(*, bare: bool = False, **values: Any) -> dict[str, Any]:
    """The extra= for a message: its fields, and whether a terminal shows it
    without the "quantic-agent: " prefix (a tool call's trace line)."""
    return {"fields": values, "bare": bare}


def _value(value: Any) -> str:
    """A field's value, quoted as JSON when a space, quote or = would break
    the key=value reading."""
    text = str(value)
    if not text or any(c in text for c in ' "=\\\n'):
        return json.dumps(text, ensure_ascii=False)
    return text


class Plain(logging.Formatter):
    """A terminal's line: the message, prefixed, fields left out."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        return message if getattr(record, "bare", False) else PREFIX + message


class Journal(logging.Formatter):
    """A journal line: priority, message, then the fields."""

    def format(self, record: logging.LogRecord) -> str:
        values: dict[str, Any] = getattr(record, "fields", {})
        pairs = "".join(f" {key}={_value(v)}" for key, v in values.items())
        # Every line of a multi-line message is its own journal entry: each
        # gets the priority, and only the last the fields.
        priority = f"<{_PRIORITY.get(record.levelno, 6)}>"
        lines = record.getMessage().split("\n")
        return "\n".join(priority + line for line in lines) + pairs


def to_journal(stream: TextIO) -> bool:
    """Whether stream is the journal. systemd sets JOURNAL_STREAM to the
    device and inode of the stream it connected to the journal; stderr is
    that stream only if they match, so a service whose stderr was
    redirected to a file still writes plain lines (systemd.exec(5))."""
    expected = os.environ.get("JOURNAL_STREAM")
    if not expected:
        return False
    try:
        st = os.fstat(stream.fileno())
    except OSError, ValueError, io.UnsupportedOperation:
        return False  # no file behind it: pytest's capture, a StringIO
    return expected == f"{st.st_dev}:{st.st_ino}"


class _Stderr(logging.Handler):
    """Writes to whatever sys.stderr is when a message comes, not when the
    handler was made: pytest replaces sys.stderr for each test, and a
    StreamHandler would keep writing to the first one."""

    plain = Plain()
    journal = Journal()

    def emit(self, record: logging.LogRecord) -> None:
        stream = sys.stderr
        formatter = self.journal if to_journal(stream) else self.plain
        try:
            stream.write(formatter.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


def setup() -> None:
    """Sends the agent's messages to stderr. Safe to call more than once:
    main() runs many times in one test process."""
    if not any(isinstance(h, _Stderr) for h in LOGGER.handlers):
        LOGGER.addHandler(_Stderr())
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False  # not also through the root logger's handlers
