# Python lessons

Notes written while porting `quantic-agent` from Go to Python, by someone whose daily languages are
Elixir and Ruby, who has just learned Go building
[the first version](https://github.com/fleveque/quantic-agent-go/tree/main/docs/lessons), and who is
coming to Python now.

Each lesson pairs with a milestone from the [roadmap](../../README.md#roadmap). They're not a Python
tutorial. They're the things that surprised me, the assumptions I carried over from Go, Elixir and
Ruby that turned out wrong, and what changed from the Go version and why.

| # | Lesson | Milestone | Read online | Code walkthrough |
|---|---|---|---|---|
| [00](00-layout-packages-and-privacy-by-convention.md) | Layout, packages, and privacy by convention | 0 — layout and design | [Layout, packages and privacy](https://claude.ai/artifact/2gGJyhaVj83SxVquTc4ATD) | [The layout, line by line](https://claude.ai/artifact/CoifveReWASLXJkBjt9aj9) |
| [01](01-a-command-a-module-and-pytest.md) | A command, a module, and pytest | 1 — first code and tests | [A command, a module, and pytest](https://claude.ai/artifact/PNf2nngL7T3FPAaPquhEcv) | [The first command, line by line](https://claude.ai/artifact/QvzKAQqd5Jee9C4Q5LUCBJ) |
| [02](02-pydantic-models-and-one-http-call.md) | Pydantic models and one HTTP call | 2 — the Ollama client | [Pydantic models and one HTTP call](https://claude.ai/artifact/UsGoUQ6UEyicTvGaWCHyeC) | [The Ollama client, line by line](https://claude.ai/artifact/EZRDtdwTdMmHzqqjSNsTZM) |
| [03](03-exceptions-you-can-tell-apart.md) | Exceptions you can tell apart | 3 — errors the agent can tell apart | [Exceptions you can tell apart](https://claude.ai/artifact/URFbirkFqqQNFbe2xfRqLJ) | [Errors, line by line](https://claude.ai/artifact/KjWES5unohRZjtyiMhxCBE) |
| [04](04-async-deadlines-and-letting-go.md) | Async, deadlines and letting go | 4 — timeouts and cancellation | [Async, deadlines and letting go](https://claude.ai/artifact/Rrre4qcYJJdAMwTrMw1RLq) | [Deadlines, line by line](https://claude.ai/artifact/LjytQhW7PHSoTDN8XDn5Ps) |
| [05](05-the-first-real-tool.md) | The first real tool | 5 — MCP client, schemas from types | [The first real tool](https://claude.ai/artifact/T5ixXHQr63Bx6Nuzwj1GJj) | [The first tool, line by line](https://claude.ai/artifact/JAHtPs3kXL3WZhwe4x1eiz) |
| [06](06-every-figure-has-a-source.md) | Every figure has a source | 6 — the provenance validator | [Every figure has a source](https://claude.ai/artifact/P2UTWg28qBgcLkCVXDYbDP) | [Provenance, line by line](https://claude.ai/artifact/3oJ654NbHc8nioJo7JHVkr) |
| [07](07-a-memory-that-can-be-audited.md) | A memory that can be audited | 7 — SQLite: runs, drafts, audit log | [A memory that can be audited](https://claude.ai/artifact/GioJKqVLzs6r5fKFbgu2yn) | [The run history, line by line](https://claude.ai/artifact/BmisnMg62AC2VpT7TcbzW4) |
| [08](08-a-loop-that-can-stop.md) | A loop that can stop | 8 — the research loop: budgets, retries, phases, resume | [A loop that can stop](https://claude.ai/artifact/VqfYLE86knX1NP1Agt9XNP) | [The research loop, line by line](https://claude.ai/artifact/R4AmcMHTenLcAeaQqAWeDY) |
| [09](09-one-gpu-many-calls.md) | One GPU, many calls | 9 — the worker pool: serialised GPU, parallel I/O | [One GPU, many calls](https://claude.ai/artifact/7yD52xXv3yLvBBbVwCJoQG) | [The worker pool, line by line](https://claude.ai/artifact/WQCK76jbtKB5WtQRRh5Qgv) |
| [10](10-a-memory-for-the-house-voice.md) | A memory for the house voice | 10 — retrieval: embeddings, brute-force cosine, style memory | [A memory for the house voice](https://claude.ai/artifact/X7S4oMKwVZt3gSCJGnox6V) | [Style memory, line by line](https://claude.ai/artifact/6SFcTdLKojwjeAts7cf1np) |
| [11](11-seven-files-one-set-of-figures.md) | Seven files, one set of figures | 11 — the Week Ahead end to end, 7 locales, translation validator | [Seven files, one set of figures](https://claude.ai/artifact/VFJgaAxgiZx8YiwPFuFBgL) | [The Week Ahead, line by line](https://claude.ai/artifact/M1FoS3w2xAD3AehxYu7G2u) |

Lessons tell the story of a milestone: what surprised me and why. Walkthroughs go through the code
itself in reading order, the way a tech lead would with a new teammate. Formatted pages are built
with the stylesheet in [pages/](pages/README.md).

More land as the milestones do.
