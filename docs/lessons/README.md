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

Lessons tell the story of a milestone: what surprised me and why. Walkthroughs go through the code
itself in reading order, the way a tech lead would with a new teammate. Formatted pages are built
with the stylesheet in [pages/](pages/README.md).

More land as the milestones do.
