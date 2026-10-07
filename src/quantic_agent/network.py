"""The one network judgement both clients share: is the server simply not there?

The model client uses httpx and the MCP SDK uses httpx2, a separate package
with its own exception classes. What they wrap is the same: the operating
system's own error, reached by following the chain of causes.
"""

import errno
from collections.abc import Iterator

import httpx
import httpx2


def causes(err: BaseException) -> Iterator[BaseException]:
    """err, then what caused it, then what caused that. An HTTP library raises
    its own exception from its transport's, which is raised from the
    operating system's."""
    current: BaseException | None = err
    while current is not None:
        yield current
        current = current.__cause__ or current.__context__


def unreachable(err: BaseException) -> bool:
    """Whether a transport error means the server wasn't there to answer.

    Each case was reproduced: connection refused (nothing listening), reset by
    the peer, network unreachable (no route), and a connection closed before
    any reply, as a restart does (RemoteProtocolError; a server answering
    malformed HTTP would raise it too, which neither server does).

    Two are left out on purpose. A DNS failure: the HTTP libraries raise the
    same ConnectError as for a refused connection, so only the cause tells
    them apart. Its cause is a socket.gaierror, whose error numbers are the
    resolver's (-2, "Name or service not known"), never one checked below. An
    unknown host is far more often a typo than a machine that's off, and a
    typo should fail, not be waited on. And a timeout: a slow server is not a
    missing one.
    """
    chain = list(causes(err))
    if any(isinstance(c, httpx.RemoteProtocolError | httpx2.RemoteProtocolError) for c in chain):
        return True
    return any(
        isinstance(c, ConnectionRefusedError | ConnectionResetError)
        or (isinstance(c, OSError) and c.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH))
        for c in chain
    )
