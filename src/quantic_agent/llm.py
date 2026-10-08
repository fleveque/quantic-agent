"""The client for the local model server.

The agent generates through Ollama (design §4): one HTTP call per generation,
never streamed, so a reply is one JSON object rather than a sequence of them.
chat() offers the model tools and may get back a request to call one.

Every call is a coroutine (decision 0008), and the caller decides how long it
may take: the client sets no timeout of its own. Wrap calls in
`asyncio.timeout(...)`, or cancel the task. Cancelling ends the request, and
Ollama then stops working on it too: a cancelled generation frees the GPU
within about a second. Cancelling while a model is still loading aborts the
load, so a deadline must allow for a cold start. Neither a timeout nor a
cancellation is an LLMError: they arrive as asyncio's own TimeoutError and
CancelledError.

Failures are exceptions a caller can tell apart by class, never by message:
ServerUnavailableError when the server isn't there to answer,
ModelNotFoundError when it is but lacks the model, APIError for any other
refusal. All are LLMErrors.
"""

import asyncio
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, Self

import httpx
from pydantic import BaseModel, BeforeValidator, ValidationError

from quantic_agent import network

DEFAULT_BASE_URL = "http://localhost:11434"


class LLMError(Exception):
    """Anything that went wrong talking to the model server. Raised as itself
    for a failure with no kind of its own, such as a reply that isn't valid;
    the subclasses below are the kinds a caller acts on differently."""


class ServerUnavailableError(LLMError):
    """No reply came back because the server wasn't there to give one: nothing
    listening, the connection dropped or reset before a reply, or no route to
    the address. That is what a stopped or restarting Ollama looks like, and
    design §3.6 treats it as "wait and retry", not as a failure of the task.
    The network error is chained as __cause__."""


class APIError(LLMError):
    """A reply whose status wasn't 200 OK: the server was reached and said no.

    message is the server's explanation: the "error" field of a JSON body, or
    the text of a body that isn't JSON. Empty if there was none.
    """

    def __init__(self, method: str, path: str, status_code: int, message: str) -> None:
        self.method = method
        self.path = path
        self.status_code = status_code
        self.message = message
        text = f"{method} {path}: {status_code} {httpx.codes.get_reason_phrase(status_code)}"
        super().__init__(f"{text}: {message}" if message else text)


class ModelNotFoundError(APIError):
    """The server answered, and has no such model: it was never pulled on this
    machine, or the name is misspelt. An APIError, so it carries the status."""


def _from_nanoseconds(value: object) -> object:
    # Ollama sends durations as integer nanoseconds. Pydantic reads an integer
    # timedelta as *seconds*, so without this 205098000 (0.2s) decodes as
    # 2,373 days. timedelta keeps microseconds, so the last three digits go.
    if isinstance(value, int):
        return timedelta(microseconds=value / 1000)
    return value


Nanoseconds = Annotated[timedelta, BeforeValidator(_from_nanoseconds)]


class Options(BaseModel):
    """Ollama's per-request knobs. None means "not set": the key isn't sent.

    num_ctx is the one that bites: the server uses a 4096-token window unless
    asked for more, whatever the model itself supports, and a longer prompt is
    truncated to fit. A research context has to ask.
    """

    num_predict: int | None = None
    num_ctx: int | None = None
    temperature: float | None = None
    seed: int | None = None


class _GenerateBody(BaseModel):
    """The wire format of POST /api/generate."""

    model: str
    prompt: str
    # Sent even though it's False: Ollama streams unless told not to. Requests
    # are serialised with exclude_none, which drops None and keeps False.
    stream: bool = False
    think: bool | None = None
    options: Options | None = None


class GenerateResponse(BaseModel):
    """One non-streamed reply from /api/generate. Keys not declared here
    (such as the long `context` array) are ignored."""

    model: str
    created_at: datetime | None = None
    response: str
    thinking: str = ""
    done: bool
    done_reason: str = ""

    prompt_eval_count: int = 0
    eval_count: int = 0

    total_duration: Nanoseconds = timedelta()
    load_duration: Nanoseconds = timedelta()
    prompt_eval_duration: Nanoseconds = timedelta()
    eval_duration: Nanoseconds = timedelta()

    @property
    def truncated(self) -> bool:
        """Whether the model stopped because it ran out of token budget rather
        than because it finished. A truncated draft is a broken draft: half a
        table is worse than no table."""
        return self.done_reason == "length"


class FunctionCall(BaseModel):
    """A tool the model asked for, and the arguments it chose.

    Ollama sends the arguments as a JSON object, not a string. They're kept as
    they arrived: whether they fit the tool is for the tool to decide, and a
    model can produce anything.
    """

    name: str
    arguments: dict[str, Any] = {}


class ToolCall(BaseModel):
    id: str | None = None
    function: FunctionCall


class Message(BaseModel):
    """One message in a conversation.

    tool_calls is set on an assistant message that asks for tools instead of
    answering; sending it back as part of the history keeps the conversation
    coherent for the model. tool_name is set on a "tool" message: which
    tool's output content is.
    """

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_name: str | None = None


class FunctionDef(BaseModel):
    """What the model is told about a tool. parameters is a JSON Schema."""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolDef(BaseModel):
    """One tool offered to the model."""

    type: Literal["function"] = "function"
    function: FunctionDef


class _ChatBody(BaseModel):
    """The wire format of POST /api/chat."""

    model: str
    messages: Sequence[Message]
    tools: Sequence[ToolDef] | None = None
    stream: bool = False  # sent, as for /api/generate
    think: bool | None = None
    options: Options | None = None


class _EmbedBody(BaseModel):
    """The wire format of POST /api/embed."""

    model: str
    input: Sequence[str]
    # Sent as false: Ollama's default cuts an input longer than the embedding
    # model's context to fit, silently, and the vector then stands for text
    # it never saw. Refused, the input has to be made to fit on purpose.
    truncate: bool = False


class EmbedResponse(BaseModel):
    """The vectors for each input, in the order given."""

    model: str
    embeddings: list[list[float]]
    prompt_eval_count: int = 0
    total_duration: Nanoseconds = timedelta()
    load_duration: Nanoseconds = timedelta()


class ChatResponse(BaseModel):
    """One non-streamed reply from /api/chat: the model's next message, which
    is either an answer or a request to call tools."""

    model: str
    created_at: datetime | None = None
    message: Message
    done: bool
    done_reason: str = ""

    prompt_eval_count: int = 0
    eval_count: int = 0

    total_duration: Nanoseconds = timedelta()
    load_duration: Nanoseconds = timedelta()
    prompt_eval_duration: Nanoseconds = timedelta()
    eval_duration: Nanoseconds = timedelta()

    @property
    def truncated(self) -> bool:
        """Whether the model ran out of token budget mid-reply."""
        return self.done_reason == "length"


class ModelDetails(BaseModel):
    """How a pulled model was built."""

    parameter_size: str = ""
    quantization_level: str = ""
    context_length: int = 0


class PulledModel(BaseModel):
    """One model the server has pulled, from /api/tags."""

    name: str
    size: int
    modified_at: datetime | None = None
    details: ModelDetails = ModelDetails()
    capabilities: list[str] = []

    def supports(self, capability: str) -> bool:
        """Whether the model advertises a capability. The ones that matter here
        are "tools", which milestone 5 depends on, and "thinking", which
        decides whether think=False is doing anything."""
        return capability in self.capabilities


class RunningModel(BaseModel):
    """A model the server currently holds in memory, from /api/ps."""

    name: str
    size: int
    size_vram: int = 0
    context_length: int = 0
    expires_at: datetime | None = None
    details: ModelDetails = ModelDetails()

    @property
    def on_gpu(self) -> float:
        """How much of the loaded model sits in VRAM, from 0 (entirely in
        system RAM) to 1 (entirely on the card). A model too large for the GPU
        keeps running with some layers on the CPU, which is the difference
        between a heavy tier that is merely slow and one that is unusable."""
        if self.size == 0:
            return 0.0
        return self.size_vram / self.size


class _ErrorBody(BaseModel):
    error: str


class _Version(BaseModel):
    version: str


class _PulledModels(BaseModel):
    models: list[PulledModel]


class _RunningModels(BaseModel):
    models: list[RunningModel]


class Client:
    """A handle on one Ollama server and one model.

    It holds a pool of HTTP connections, so close it when done, or use it as an
    async context manager: `async with Client(url, model) as client: ...`.

    It is also the GPU's queue (design §3.6). At most slots requests that use
    the model (generate, chat) are sent at once; the others wait here. With
    one GPU that is one: concurrent runs take turns
    at the model, and spend their waits on everything else. Requests that
    don't touch the model (version, models, running) never wait.
    """

    def __init__(self, base_url: str, model: str, *, slots: int = 1) -> None:
        # OLLAMA_HOST is conventionally "host:port", which isn't a URL.
        if "://" not in base_url:
            base_url = "http://" + base_url
        self._model = model
        # timeout=None: no limit of httpx's own (its default is 5 seconds, a
        # sixth of a cold model load). How long a call may take is decided by
        # whoever awaits it.
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=None)
        self._gpu = asyncio.Semaphore(slots)

    @property
    def model(self) -> str:
        """The model this client generates with."""
        return self._model

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def generate(
        self, prompt: str, *, think: bool | None = None, options: Options | None = None
    ) -> GenerateResponse:
        """Sends one prompt and returns the whole reply.

        think turns a thinking model's reasoning pass on or off; None leaves
        the model's own default alone.
        """
        body = _GenerateBody(model=self._model, prompt=prompt, think=think, options=options)
        async with self._gpu:
            return await self._call("POST", "/api/generate", GenerateResponse, body)

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[ToolDef] | None = None,
        think: bool | None = None,
        options: Options | None = None,
    ) -> ChatResponse:
        """One conversation turn through /api/chat: the messages so far go in,
        the model's next message comes out. Unlike generate it can offer the
        model tools, and the reply may then ask to call one instead of
        answering."""
        body = _ChatBody(
            model=self._model, messages=messages, tools=tools, think=think, options=options
        )
        async with self._gpu:
            return await self._call("POST", "/api/chat", ChatResponse, body)

    async def embed(self, texts: Sequence[str], *, model: str) -> EmbedResponse:
        """One vector per text, from an embedding model. model is named per
        call: the client's own model generates, a separate one embeds, and
        both run on the same GPU, so embedding takes its turn with the rest."""
        body = _EmbedBody(model=model, input=texts)
        async with self._gpu:
            return await self._call("POST", "/api/embed", EmbedResponse, body)

    async def version(self) -> str:
        """The server's version. Doubles as a reachability check that costs
        no GPU time."""
        return (await self._call("GET", "/api/version", _Version)).version

    async def models(self) -> list[PulledModel]:
        """What this server has pulled. The agent is developed on one machine
        and runs on another, so "what is actually on that box" has to be a
        question the agent itself can answer."""
        return (await self._call("GET", "/api/tags", _PulledModels)).models

    async def running(self) -> list[RunningModel]:
        """What the server is holding in memory right now."""
        return (await self._call("GET", "/api/ps", _RunningModels)).models

    async def _call[T: BaseModel](
        self, method: str, path: str, reply: type[T], body: BaseModel | None = None
    ) -> T:
        payload = None if body is None else body.model_dump(mode="json", exclude_none=True)
        try:
            resp = await self._http.request(method, path, json=payload)
        # A cancellation (asyncio.CancelledError) passes through untouched:
        # it is a BaseException, not an httpx.HTTPError, so it can never be
        # mistaken for an unavailable server.
        except httpx.HTTPError as err:
            kind = ServerUnavailableError if network.unreachable(err) else LLMError
            raise kind(f"{method} {path}: {err}") from err

        # 200, not httpx.codes.OK: pyright types that enum member as the tuple
        # it is defined from, (200, "OK"), and calls the comparison always true.
        if resp.status_code != 200:
            raise _api_error(method, path, resp)
        try:
            return reply.model_validate_json(resp.content)
        except ValidationError as err:
            raise LLMError(f"decoding {path} reply: {err}") from err


def _api_error(method: str, path: str, resp: httpx.Response) -> APIError:
    """The error for a reply that wasn't 200 OK. Ollama reports most failures
    as {"error": "..."}, but a mistyped path is answered in plain text by the
    router in front of its handlers. That difference is also how a missing
    model is told apart from a missing endpoint: both are 404s, and only
    Ollama's own says why."""
    text = resp.text[: 4 << 10].strip()
    try:
        message = _ErrorBody.model_validate_json(text).error
    except ValidationError:
        return APIError(method, path, resp.status_code, text)
    if resp.status_code == 404 and "not found" in message:
        return ModelNotFoundError(method, path, resp.status_code, message)
    return APIError(method, path, resp.status_code, message)
