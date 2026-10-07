# Decisions

Why the design is what it is, one decision per file. New decisions are numbered on from the last.

| # | Decision | Date |
|---|---|---|
| [0001](0001-agentic-research-constrained-writing.md) | Agentic research, constrained writing | 2026-09-10 |
| [0002](0002-structured-data-not-markdown-prose.md) | Posts are structured data plus prose, not markdown documents | 2026-09-10 |
| [0003](0003-publish-as-files-via-pr.md) | Publish as files through a PR, not through a drafts API | 2026-09-10 |
| [0004](0004-ollama-now-llama-cpp-on-a-trigger.md) | Ollama now, llama.cpp on a trigger | 2026-09-24 |
| [0005](0005-default-model-by-measurement.md) | Keep the 9B as default; choose models by measurement, repeatedly | 2026-09-26 |
| [0006](0006-anonymous-mcp-for-public-tools.md) | Connect to Quantic's MCP server anonymously; a service token when it's needed | 2026-10-06 |
| [0007](0007-continue-in-python.md) | Continue the agent in Python; the Go version is finished | 2026-10-07 |

**0001–0007 were written for the Go version**, [quantic-agent-go](https://github.com/fleveque/quantic-agent-go),
and are carried over unchanged, links aside: they are records of what was decided and why, at the
time. So "this repository" in them is quantic-agent-go, and the Go names in them (`internal/llm`,
`go-github`, `yaml.Marshal`, `cmd/bench`) are the Go code they were written against. The decisions
themselves hold for the Python version; [design.md](../design.md) says how each is being built here.
