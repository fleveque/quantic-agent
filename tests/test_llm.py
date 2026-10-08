import asyncio
import socket
from datetime import timedelta

import httpx
import pytest
from conftest import DEAD_URL, FakeOllama, Reply, fixture

from quantic_agent import llm

pytestmark = pytest.mark.anyio


async def test_generate_decodes_the_reply(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    async with llm.Client(ollama.url, "quantic-9b:latest") as client:
        resp = await client.generate("Reply with exactly: ok", think=False)

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


async def test_generate_reports_truncation(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate-thinking.json"))

    async with llm.Client(ollama.url, "quantic-9b:latest") as client:
        resp = await client.generate("hi")

    assert resp.truncated, f"done_reason {resp.done_reason!r}"
    # A thinking model spends its budget on the reasoning pass first, so a
    # truncated reply can carry thinking and no answer at all.
    assert resp.response == ""
    assert resp.thinking != ""


async def test_generate_omits_what_was_not_set(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    async with llm.Client(ollama.url, "m") as client:
        await client.generate("hi")

    assert "think" not in ollama.bodies[0]
    assert "options" not in ollama.bodies[0]


async def test_generate_sends_options_whose_value_is_zero(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    async with llm.Client(ollama.url, "m") as client:
        await client.generate("hi", options=llm.Options(temperature=0, seed=0))

    # 0 is a real temperature and a real seed; None is "not set".
    assert ollama.bodies[0]["options"] == {"temperature": 0, "seed": 0}


async def test_version(ollama: FakeOllama) -> None:
    ollama.replies["/api/version"] = Reply(b'{"version":"0.30.3"}')

    async with llm.Client(ollama.url, "m") as client:
        assert await client.version() == "0.30.3"
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
async def test_server_errors(
    ollama: FakeOllama, status: int, body: bytes, message: str, kind: type[llm.APIError]
) -> None:
    ollama.replies["/api/generate"] = Reply(body, status)

    async with llm.Client(ollama.url, "m") as client:
        with pytest.raises(llm.APIError) as err:
            await client.generate("hi")

    # The exact class: a plain 404 must not be taken for a missing model.
    assert type(err.value) is kind
    assert err.value.status_code == status
    assert err.value.message == message
    # The message still reads as one line with the status in it.
    assert str(status) in str(err.value)


async def test_generate_rejects_an_unparseable_reply(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(b"{not json")

    async with llm.Client(ollama.url, "m") as client:
        with pytest.raises(llm.LLMError, match="decoding") as err:
            await client.generate("hi")
    # A reply that arrived but made no sense is neither kind of known failure.
    assert type(err.value) is llm.LLMError


async def test_unavailable_when_nothing_listens() -> None:
    async with llm.Client(DEAD_URL, "m") as client:
        with pytest.raises(llm.ServerUnavailableError) as err:
            await client.version()
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
async def test_unavailable_when_the_connection_goes(
    ollama: FakeOllama, reply: Reply, cause: type[BaseException]
) -> None:
    ollama.replies["/api/generate"] = reply

    async with llm.Client(ollama.url, "m") as client:
        with pytest.raises(llm.ServerUnavailableError) as err:
            await client.generate("hi")
    assert cause in causes(err.value)


async def test_an_unknown_host_is_not_unavailable() -> None:
    # .invalid is reserved and never resolves. An unresolvable name is almost
    # always a typo in OLLAMA_HOST, which should fail rather than be waited on.
    async with llm.Client("http://no-such-host.invalid:11434", "m") as client:
        with pytest.raises(llm.LLMError) as err:
            await client.version()
    assert type(err.value) is llm.LLMError
    assert socket.gaierror in causes(err.value)


async def test_a_host_without_a_scheme_is_accepted(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(fixture("generate.json"))

    # OLLAMA_HOST is conventionally "host:port", with no scheme.
    async with llm.Client(ollama.host_port, "m") as client:
        assert (await client.generate("hi")).response == "ok"


async def test_models(ollama: FakeOllama) -> None:
    ollama.replies["/api/tags"] = Reply(fixture("tags.json"))

    async with llm.Client(ollama.url, "qwen3.5:9b") as client:
        models = await client.models()

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


async def test_running(ollama: FakeOllama) -> None:
    ollama.replies["/api/ps"] = Reply(fixture("ps.json"))

    async with llm.Client(ollama.url, "qwen3.5:9b") as client:
        running = await client.running()

    assert len(running) == 1
    got = running[0]
    assert got.name == "qwen3.5:9b"
    # Captured on a machine with no CUDA GPU, so nothing is in VRAM: exactly
    # the case the benchmark has to make obvious.
    assert got.size_vram == 0
    assert got.on_gpu == 0
    # The server reports its default window, not the model's maximum.
    assert got.context_length == 4096


async def test_a_deadline_ends_the_request(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(hang=True)

    async with llm.Client(ollama.url, "m") as client:
        # Not an LLMError: running out of time is the caller's decision, and
        # a slow server is not a missing one.
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await client.generate("hi")

    # The connection was closed, which is what tells Ollama to stop.
    assert ollama.wait_for_hangups(1)


async def test_cancelling_ends_the_request(ollama: FakeOllama) -> None:
    ollama.replies["/api/generate"] = Reply(hang=True)

    async with llm.Client(ollama.url, "m") as client:
        request = asyncio.create_task(client.generate("hi"))
        await asyncio.sleep(0.1)  # long enough for the request to be on its way
        request.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request

    assert ollama.wait_for_hangups(1)


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


async def test_chat_reads_a_tool_call(ollama: FakeOllama) -> None:
    # One real exchange with qwen3.5:9b: the model's first reply asks for a tool.
    ollama.replies["/api/chat"] = Reply(fixture("chat-tool-call.json"))
    definition = llm.ToolDef(
        function=llm.FunctionDef(name="dividend_calendar", description="d", parameters={})
    )

    async with llm.Client(ollama.url, "qwen3.5:9b") as client:
        resp = await client.chat(
            [llm.Message(role="user", content="next 10 days?")], tools=[definition], think=False
        )

    assert resp.message.content == ""
    assert resp.message.tool_calls is not None
    call = resp.message.tool_calls[0].function
    # Ollama sends the arguments as a JSON object, not a string.
    assert (call.name, call.arguments) == ("dividend_calendar", {"days": 10})

    sent = ollama.bodies[0]
    assert sent["stream"] is False
    assert sent["tools"][0]["function"]["name"] == "dividend_calendar"
    # Unset message fields aren't sent: no "tool_calls": null for a user message.
    assert sent["messages"] == [{"role": "user", "content": "next 10 days?"}]


async def test_chat_sends_a_tool_result_back(ollama: FakeOllama) -> None:
    ollama.replies["/api/chat"] = Reply(fixture("chat-tool-answer.json"))
    asked = llm.Message(
        role="assistant",
        tool_calls=[
            llm.ToolCall(
                function=llm.FunctionCall(name="dividend_calendar", arguments={"days": 10})
            )
        ],
    )
    result = llm.Message(role="tool", tool_name="dividend_calendar", content='{"stocks":[]}')

    async with llm.Client(ollama.url, "qwen3.5:9b") as client:
        resp = await client.chat([asked, result])

    assert resp.message.tool_calls is None
    assert "ex-dividend" in resp.message.content
    sent = ollama.bodies[0]["messages"]
    assert sent[0]["tool_calls"][0]["function"]["arguments"] == {"days": 10}
    assert sent[1] == {"role": "tool", "content": '{"stocks":[]}', "tool_name": "dividend_calendar"}


QUESTION = [llm.Message(role="user", content="q")]


async def test_model_calls_take_turns(ollama: FakeOllama) -> None:
    # Three runs asking at once, one GPU: the server sees one at a time.
    ollama.replies["/api/chat"] = Reply(fixture("chat-tool-answer.json"), delay=0.1)

    async with llm.Client(ollama.url, "qwen3.5:9b") as client:
        await asyncio.gather(*(client.chat(QUESTION) for _ in range(3)))

    assert len(ollama.bodies) == 3
    assert ollama.peak == 1


async def test_more_slots_let_more_through(ollama: FakeOllama) -> None:
    ollama.replies["/api/chat"] = Reply(fixture("chat-tool-answer.json"), delay=0.1)

    async with llm.Client(ollama.url, "qwen3.5:9b", slots=3) as client:
        await asyncio.gather(*(client.chat(QUESTION) for _ in range(3)))

    assert ollama.peak == 3


async def test_what_doesnt_use_the_model_doesnt_wait(ollama: FakeOllama) -> None:
    ollama.replies["/api/chat"] = Reply(fixture("chat-tool-answer.json"), delay=0.5)
    ollama.replies["/api/version"] = Reply(b'{"version":"0.34.4"}')

    async with llm.Client(ollama.url, "qwen3.5:9b") as client:
        chat = asyncio.create_task(client.chat(QUESTION))
        await asyncio.sleep(0.05)  # the chat is on the GPU
        async with asyncio.timeout(0.3):
            assert await client.version() == "0.34.4"
        await chat
