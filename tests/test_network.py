import errno
import socket

import httpx
import httpx2
import pytest

from quantic_agent import network


def raised_from(outer: BaseException, cause: BaseException) -> BaseException:
    """outer, raised from cause, as an HTTP library chains them."""
    try:
        try:
            raise cause
        except BaseException as err:
            raise outer from err
    except BaseException as chained:
        return chained


@pytest.mark.parametrize(
    ("err", "unavailable"),
    [
        pytest.param(
            raised_from(httpx.ConnectError("x"), ConnectionRefusedError()), True, id="refused"
        ),
        pytest.param(
            raised_from(httpx2.ConnectError("x"), ConnectionResetError()), True, id="reset"
        ),
        pytest.param(
            raised_from(httpx2.ConnectError("x"), OSError(errno.ENETUNREACH, "unreachable")),
            True,
            id="no route",
        ),
        # The two libraries' "closed before a reply" are different classes.
        pytest.param(httpx.RemoteProtocolError("closed"), True, id="dropped, httpx"),
        pytest.param(httpx2.RemoteProtocolError("closed"), True, id="dropped, httpx2"),
        pytest.param(
            raised_from(httpx2.ConnectError("x"), socket.gaierror(-2, "unknown")), False, id="dns"
        ),
        pytest.param(raised_from(httpx2.ConnectTimeout("x"), TimeoutError()), False, id="timeout"),
    ],
)
def test_unreachable(err: BaseException, unavailable: bool) -> None:
    assert network.unreachable(err) is unavailable
