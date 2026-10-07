import socket
from datetime import timedelta

import httpx
import pytest
from conftest import DEAD_URL, FakeOllama, Reply, fixture

from quantic_agent import llm


def test_generate_decodes_the_reply(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    with llm.Client(ollama.url, "quantic-9b:latest") as client:
        resp = client.generate("Reply with exactly: ok", think=False)

    assert resp.response == "ok"
    assert resp.done_reason == "stop"
    assert not resp.truncated
    assert resp.eval_count == 2
    # 205098000 nanoseconds on the wire is 205.098 milliseconds.
    assert resp.eval_duration == timedelta(milliseconds=205.098)
    assert resp.created_at is not None

    sent = ollama.bodies[0]
    assert sent["model"] == "quantic-9b:latest"
    # Ollama streams unless told not to, so False has to be sent, not left out.
    assert sent["stream"] is False
    assert sent["think"] is False


def test_generate_reports_truncation(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate-thinking.json"))

    with llm.Client(ollama.url, "quantic-9b:latest") as client:
        resp = client.generate("hi")

    assert resp.truncated, f"done_reason {resp.done_reason!r}"
    # A thinking model spends its budget on the reasoning pass first, so a
    # truncated reply can carry thinking and no answer at all.
    assert resp.response == ""
    assert resp.thinking != ""


def test_generate_omits_what_was_not_set(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    with llm.Client(ollama.url, "m") as client:
        client.generate("hi")

    assert "think" not in ollama.bodies[0]
    assert "options" not in ollama.bodies[0]


def test_generate_sends_options_whose_value_is_zero(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    with llm.Client(ollama.url, "m") as client:
        client.generate("hi", options=llm.Options(temperature=0, seed=0))

    # 0 is a real temperature and a real seed; None is "not set".
    assert ollama.bodies[0]["options"] == {"temperature": 0, "seed": 0}


def test_version(ollama: FakeOllama) -> None:
    ollama.replies["/api/version"] = Reply(b'{"version":"0.30.3"}')

    with llm.Client(ollama.url, "m") as client:
        assert client.version() == "0.30.3"
    assert ollama.paths == ["/api/version"]


def causes(err: BaseException) -> list[type[BaseException]]:
    """The classes in err's chain of causes, outermost first."""
    found: list[type[BaseException]] = []
    current: BaseException | None = err
    while current is not None:
        found.append(type(current))
        current = current.__cause__ or current.__context__
    return found


# Every body here is what a real Ollama 0.34.4 sent for that request.
@pytest.mark.parametrize(
    ("status", "body", "message", "kind"),
    [
        pytest.param(
            404,
            fixture("generate-model-not-found.json"),
            "model 'no-such-model:latest' not found",
            llm.ModelNotFoundError,
            id="unknown model",
        ),
        # A mistyped path never reaches Ollama's handlers, so the body is the
        # router's plain text, and the 404 is not about a model.
        pytest.param(404, b"404 page not found\n", "404 page not found", llm.APIError, id="plain"),
        pytest.param(
            400,
            b'{"error":"invalid character \'n\' looking for beginning of object key string"}',
            "invalid character 'n' looking for beginning of object key string",
            llm.APIError,
            id="malformed request",
        ),
        pytest.param(500, b"", "", llm.APIError, id="empty body"),
    ],
)
def test_server_errors(
    ollama: FakeOllama, status: int, body: bytes, message: str, kind: type[llm.APIError]
) -> None:
    ollama.replies["/api/generate"] = Reply(body, status)

    with llm.Client(ollama.url, "m") as client, pytest.raises(llm.APIError) as err:
        client.generate("hi")

    # The exact class: a plain 404 must not be taken for a missing model.
    assert type(err.value) is kind
    assert err.value.status_code == status
    assert err.value.message == message
    # The message still reads as one line with the status in it.
    assert str(status) in str(err.value)


def test_generate_rejects_an_unparseable_reply(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(b"{not json")

    with (
        llm.Client(ollama.url, "m") as client,
        pytest.raises(llm.LLMError, match="decoding") as err,
    ):
        client.generate("hi")
    # A reply that arrived but made no sense is neither kind of known failure.
    assert type(err.value) is llm.LLMError


def test_unavailable_when_nothing_listens() -> None:
    with llm.Client(DEAD_URL, "m") as client, pytest.raises(llm.ServerUnavailableError) as err:
        client.version()
    # The network's own reason is still there, as the cause.
    assert ConnectionRefusedError in causes(err.value)


@pytest.mark.parametrize(
    ("reply", "cause"),
    [
        # Accepted, then closed without a reply, as a restarting Ollama does.
        pytest.param(Reply(drop=True), httpx.RemoteProtocolError, id="dropped"),
        pytest.param(Reply(reset=True), ConnectionResetError, id="reset"),
    ],
)
def test_unavailable_when_the_connection_goes(
    ollama: FakeOllama, reply: Reply, cause: type[BaseException]
) -> None:
    ollama.replies["/api/generate"] = reply

    with llm.Client(ollama.url, "m") as client, pytest.raises(llm.ServerUnavailableError) as err:
        client.generate("hi")
    assert cause in causes(err.value)


def test_an_unknown_host_is_not_unavailable() -> None:
    # .invalid is reserved and never resolves. An unresolvable name is almost
    # always a typo in OLLAMA_HOST, which should fail rather than be waited on.
    with (
        llm.Client("http://no-such-host.invalid:11434", "m") as client,
        pytest.raises(llm.LLMError) as err,
    ):
        client.version()
    assert type(err.value) is llm.LLMError
    assert socket.gaierror in causes(err.value)


def test_a_host_without_a_scheme_is_accepted(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    # OLLAMA_HOST is conventionally "host:port", with no scheme.
    with llm.Client(ollama.host_port, "m") as client:
        assert client.generate("hi").response == "ok"


def test_models(ollama: FakeOllama) -> None:
    ollama.replies["/api/tags"] = Reply(fixture("tags.json"))

    with llm.Client(ollama.url, "qwen3.5:9b") as client:
        models = client.models()

    assert len(models) == 3
    got = models[0]
    assert got.name == "qwen3.5:9b"
    assert got.details.parameter_size == "9.7B"
    assert got.details.quantization_level == "Q4_K_M"
    assert got.details.context_length == 262144
    assert got.size == 6594474711
    # Milestone 5 needs tool calling, so the capability list is read, not assumed.
    assert got.supports("tools")
    assert got.supports("thinking")
    assert not got.supports("telepathy")


def test_running(ollama: FakeOllama) -> None:
    ollama.replies["/api/ps"] = Reply(fixture("ps.json"))

    with llm.Client(ollama.url, "qwen3.5:9b") as client:
        running = client.running()

    assert len(running) == 1
    got = running[0]
    assert got.name == "qwen3.5:9b"
    # Captured on a machine with no CUDA GPU, so nothing is in VRAM: exactly
    # the case the benchmark has to make obvious.
    assert got.size_vram == 0
    assert got.on_gpu == 0
    # The server reports its default window, not the model's maximum.
    assert got.context_length == 4096


@pytest.mark.parametrize(
    ("size", "size_vram", "want"),
    [
        pytest.param(100, 100, 1, id="fully resident"),
        pytest.param(100, 75, 0.75, id="partly offloaded"),
        pytest.param(100, 0, 0, id="cpu only"),
        pytest.param(0, 0, 0, id="nothing loaded"),
    ],
)
def test_on_gpu_fraction(size: int, size_vram: int, want: float) -> None:
    assert llm.RunningModel(name="m", size=size, size_vram=size_vram).on_gpu == want
