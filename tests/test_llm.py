from datetime import timedelta

import pytest
from conftest import FakeOllama, Reply, fixture

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


@pytest.mark.parametrize(
    ("status", "body", "wanted"),
    [
        pytest.param(
            404,
            b'{"error":"model \'no-such-model:latest\' not found"}',
            ["404", "no-such-model:latest", "not found"],
            id="json error body",
        ),
        # A mistyped path never reaches Ollama's handlers, so the body is the
        # HTTP mux's plain text rather than JSON.
        pytest.param(404, b"404 page not found\n", ["404", "page not found"], id="plain text"),
        pytest.param(500, b"", ["500"], id="empty body"),
    ],
)
def test_server_errors(ollama: FakeOllama, status: int, body: bytes, wanted: list[str]) -> None:
    ollama.replies["/api/generate"] = Reply(body, status)

    with llm.Client(ollama.url, "m") as client, pytest.raises(llm.LLMError) as err:
        client.generate("hi")

    for want in wanted:
        assert want in str(err.value)


def test_generate_rejects_an_unparseable_reply(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(b"{not json")

    with llm.Client(ollama.url, "m") as client, pytest.raises(llm.LLMError, match="decoding"):
        client.generate("hi")


def test_an_unreachable_server_is_an_llm_error(dead_url: str) -> None:
    with llm.Client(dead_url, "m") as client, pytest.raises(llm.LLMError) as err:
        client.version()
    # The transport's own exception is kept, chained as the cause.
    assert err.value.__cause__ is not None


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
