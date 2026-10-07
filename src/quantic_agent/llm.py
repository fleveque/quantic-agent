"""The client for the local model server.

The agent generates through Ollama (design §4): one HTTP call per generation,
never streamed, so a reply is one JSON object rather than a sequence of them.
Tool schemas arrive in milestone 5 and deadlines in milestone 4; this is the
plain request/response floor underneath both.
"""

from datetime import datetime, timedelta
from typing import Annotated, Self

import httpx
from pydantic import BaseModel, BeforeValidator, ValidationError

DEFAULT_BASE_URL = "http://localhost:11434"


class LLMError(Exception):
    """Anything that went wrong talking to the model server.

    One type for now: the message says what failed, and the original error is
    chained as __cause__. Milestone 3 splits it into kinds a caller can tell
    apart.
    """


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

    It holds a pool of HTTP connections, so close it when done, or use it as a
    context manager: `with Client(url, model) as client: ...`.
    """

    def __init__(self, base_url: str, model: str, *, timeout: float = 300) -> None:
        # OLLAMA_HOST is conventionally "host:port", which isn't a URL.
        if "://" not in base_url:
            base_url = "http://" + base_url
        self._model = model
        # httpx's default timeout is 5 seconds, which a cold model load alone
        # can take six times over. A blunt ceiling until milestone 4 gives
        # each call its own deadline.
        self._http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    @property
    def model(self) -> str:
        """The model this client generates with."""
        return self._model

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def generate(
        self, prompt: str, *, think: bool | None = None, options: Options | None = None
    ) -> GenerateResponse:
        """Sends one prompt and returns the whole reply.

        think turns a thinking model's reasoning pass on or off; None leaves
        the model's own default alone.
        """
        body = _GenerateBody(model=self._model, prompt=prompt, think=think, options=options)
        return self._call("POST", "/api/generate", GenerateResponse, body)

    def version(self) -> str:
        """The server's version. Doubles as a reachability check that costs
        no GPU time."""
        return self._call("GET", "/api/version", _Version).version

    def models(self) -> list[PulledModel]:
        """What this server has pulled. The agent is developed on one machine
        and runs on another, so "what is actually on that box" has to be a
        question the agent itself can answer."""
        return self._call("GET", "/api/tags", _PulledModels).models

    def running(self) -> list[RunningModel]:
        """What the server is holding in memory right now."""
        return self._call("GET", "/api/ps", _RunningModels).models

    def _call[T: BaseModel](
        self, method: str, path: str, reply: type[T], body: BaseModel | None = None
    ) -> T:
        payload = None if body is None else body.model_dump(mode="json", exclude_none=True)
        try:
            resp = self._http.request(method, path, json=payload)
        except httpx.HTTPError as err:
            raise LLMError(f"{method} {path}: {err}") from err

        # 200, not httpx.codes.OK: pyright types that enum member as the tuple
        # it is defined from, (200, "OK"), and calls the comparison always true.
        if resp.status_code != 200:
            raise LLMError(f"{method} {path}: {_server_error(resp)}")
        try:
            return reply.model_validate_json(resp.content)
        except ValidationError as err:
            raise LLMError(f"decoding {path} reply: {err}") from err


def _server_error(resp: httpx.Response) -> str:
    """A failed response, readably. Ollama reports most failures as
    {"error": "..."}, but a mistyped path is answered in plain text, so the
    body is only treated as JSON if it parses."""
    status = f"{resp.status_code} {resp.reason_phrase}"
    text = resp.text[: 4 << 10].strip()
    if not text:
        return status
    try:
        return f"{status}: {_ErrorBody.model_validate_json(text).error}"
    except ValidationError:
        return f"{status}: {text}"
