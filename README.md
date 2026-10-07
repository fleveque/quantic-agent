# quantic-agent

A local agent that drafts data-grounded content and data-quality reports for
[Quantic](https://quantic.finance), using local models through Ollama. Every figure traces to a real
tool call; nothing ships without a human.

> **Status: starting.** The agent was first built in Go, up to milestone 8:
> [quantic-agent-go](https://github.com/fleveque/quantic-agent-go), now archived. It continues here
> in Python, chosen for what comes next: retrieval, document handling, model evaluation and
> experimenting with local models ([decision 0007](https://github.com/fleveque/quantic-agent-go/blob/main/docs/decisions/0007-continue-in-python.md)).
> Milestones 0–8 are ported first, one pull request each, with a lesson that compares Python with Go.

## Working on this

`main` is protected: every change goes through a pull request, and CI must pass before merge.

## License

[MIT](LICENSE)
