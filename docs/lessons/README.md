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
| [02](02-pydantic-models-and-one-http-call.md) | Pydantic models and one HTTP call | 2 — the Ollama client | — | — |

Lessons tell the story of a milestone: what surprised me and why. Walkthroughs go through the code
itself in reading order, the way a tech lead would with a new teammate. Formatted pages are built
with the stylesheet in [pages/](pages/README.md).

More land as the milestones do.
