# Lesson 13 — Sunday, without me

**Milestone 13** — the agent runs by itself. A systemd timer starts `quantic-agent --weekly` on
Sunday mornings: it records what I decided about last week's pull request, writes next week's post
and opens its pull request. It steps aside when I'm using the GPU, and running it twice changes
nothing. It also says what it's doing in a form the system journal understands. The first time it
ran against my real data, it opened a pull request it shouldn't have.

*Also readable as a [formatted page](https://claude.ai/artifact/KafaQjeZnB6NYqNrfqxvZt), with a [code walkthrough](https://claude.ai/artifact/UC8pHu5WxBkz5tJ3hiJLwF) of every
change the milestone made.*

---

## What I chose

Four decisions, from options put to me ([decision 0015](../decisions/0015-the-weekly-job.md)):
Sundays at 07:00, the day the content plan gives the post; **one command** that syncs, writes and
opens the pull request, rather than a timer running three; **step aside** when other programs hold
the GPU, and let systemd try again; and the **standard library's `logging`**, written for the
journal, rather than a logging library or JSON lines.

## A command you can run twice

A timer retries. A computer that was off on Sunday runs the missed one at login. So `--weekly` has
to be safe to run any number of times, which is design open question 4: no second post for a week.

The week a run belongs to was already defined: the week after the day it started. So `--weekly`
looks at the Week Ahead runs, keeps those of next week, and decides from them: one with a pull
request, the week is done; one that stopped or failed, resume it; none, start one. There's no table
keyed by week and no upsert. The key is found among the runs, not stored.

I tested that. Then I ran it under systemd against my real database, where this week had three
answered runs (my test runs from the morning), the middle one published. It took the newest, saw
no pull request on it, and opened one:

```
run 4: pull request #494, 7 file(s), for review run=4 pull_request=https://github.com/fleveque/quantic/pull/494
```

Merged, it would have replaced the week's published files with an unreviewed copy. We closed it. The
rule now is that **a week with any pull request is done**, open, merged or closed. That also means a
week I rejected isn't written again on every retry. The test that missed it had one run per week;
the new one has exactly that morning's three runs. Run again, the same command said:

```
run 4, 2026-W43's, has its pull request: https://github.com/fleveque/quantic/pull/494 run=4 period=2026-W43
```

## Logging, the standard library's

Everything the agent said on stderr was a `print`. Now it goes through one logger,
`quantic_agent`, with a level:

```python
logs.LOGGER.warning(message, extra=logs.fields(locale="ca"))
```

`extra=` is how Python's `logging` attaches anything beyond the message: its keys become attributes
of the record, and the formatter reads them. Go's `slog` takes key-value pairs directly
(`slog.Warn("held", "locale", "ca")`), and Elixir's `Logger` keeps them as metadata. Ruby's
`Logger` has neither; Rails adds tags. The idea is the same in all four. Python's API is just older
than the idea.

Two formatters. In a terminal nothing changed, and the existing tests prove it: all 361 passed
without an edit. Under systemd, a service's stderr goes to the journal, and systemd says so by
setting `JOURNAL_STREAM` to the device and inode of that stream. If stderr is that file, each line
starts with its syslog priority, and journald stores it as the entry's level:

```
<4>the GPU is in use: other programs hold 9405 MiB of 16376, more than 4096; try again later others_mib=9405 total_mib=16376 ollama_mib=0
```

So `journalctl --user -u quantic-agent -p warning` shows only what went wrong. The comparison is by
inode, not by "is the variable set": a service whose stderr was redirected to a file has the
variable too, and gets plain lines.

`logging.StreamHandler(sys.stderr)` would have been the obvious handler. It keeps the stream it was
given, though, and pytest replaces `sys.stderr` for each test. The first test would have captured
the agent's messages, and every later one nothing. The handler here looks `sys.stderr` up each time
it writes.

## The GPU is mine first

Before it starts a model, `--weekly` asks `nvidia-smi` how much video memory the card has in use and
how much Ollama's own runners hold. The rest is other programs. When this milestone started, I was
playing GTA V:

```
$ nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits
9518, 16376
```

The list of compute processes added up to 7.5GB, the card said 9.5GB. Graphics-only processes, the
compositor and a browser's GPU process, aren't in that list, but their memory is in the total. So
"others" is the total less Ollama, never a sum of the list. More than 4GB, and the agent exits 3, the
code that already meant "not now, try later". systemd shows it as `status=3/NOTIMPLEMENTED`, the
LSB name for 3, which is not what it means here, but systemd only needs the number.

`subprocess.run([...], capture_output=True, text=True, check=True, timeout=10)` is Go's
`exec.Command(...).Output()` with the timeout built in, or Elixir's `System.cmd`. With no NVIDIA
card, `nvidia-smi` isn't there, `FileNotFoundError` is an `OSError`, and the check says so and goes
ahead.

Ruff rewrote one line of mine as I saved:

```
except (OSError, subprocess.SubprocessError, ValueError):   # what I wrote
except OSError, subprocess.SubprocessError, ValueError:     # what ruff left
```

Python 3.14 allows several exception types without parentheses (PEP 758), and ruff's formatter
uses the new form when the project targets 3.14. In Python 2 that same line meant "catch `OSError`
and call it `subprocess.SubprocessError`".

## systemd, read carefully

The unit is a oneshot service: it runs `quantic-agent --weekly` once and exits. Three settings did
most of the work:

- `Restart=on-failure` with `RestartSec=30min`, `RestartPreventExitStatus=1 2`. Only exit 3, "not
  now", is retried, every half hour, for at most twelve hours (`StartLimitBurst`).
- `SuccessExitStatus=4 5 6`. Prose with figures, nothing to write about, a translation held: those
  are outcomes for me to read, not failures for systemd to retry.
- `Persistent=true` on the timer. A Sunday missed because the computer was off runs at my next
  login. It's a *user* unit, so it only runs while I'm logged in. The agent needs my Ollama anyway.

I first wrote that a oneshot's start has to finish within 90 seconds, the manager's default, and
set `TimeoutStartSec=20min` to raise it. The manual says otherwise: "except when Type=oneshot is
used, in which case the timeout is disabled by default". The setting stays, but as a backstop above
the agent's own `--timeout`.

The journal showed one more thing. `--sync`'s line, printed to stdout, came out after a warning
logged later on stderr. Python buffers stdout when it isn't a terminal, and the journal isn't one.
`Environment=PYTHONUNBUFFERED=1` in the unit, and the order was right.

## What runs is what's installed

The timer runs `~/.local/bin/quantic-agent`, which `uv tool install` puts there from `main`, never
the working copy. I'm often on a branch halfway through something, and Sunday shouldn't run that.
`uv tool` builds the wheel and installs it in an environment of its own, like `pipx`, or a
`go install` that keeps its own dependencies. The prompts, the locale table and the migrations are
package data, so they came along. I checked by installing it into a scratch directory and running
it against an empty database: it migrated, and found the prompts and all seven locales.

## The whole week, under systemd

With the game closed, the same unit settings in a transient service (`systemd-run --user`), an
empty database and no GitHub App, so nothing could be proposed. `journalctl -o cat`, the post's own
lines left out:

```
no GitHub App configured (QUANTIC_AGENT_REPO, QUANTIC_AGENT_GITHUB_APP_ID): the post stays in --out
the GPU is free enough: other programs hold 1828 MiB others_mib=1828 total_mib=16376 ollama_mib=0
tool dividend_calendar {"days": 11} → 1056 bytes (304ms) tool=dividend_calendar ms=304 bytes=1056
tool get_stock {"symbol": "IBE.MC"} → 1494 bytes (137ms) tool=get_stock ms=137 bytes=1494
...
tool earnings_calendar {"days": 12} → 12933 bytes (502ms) tool=earnings_calendar ms=502 bytes=12933
tool dividend_changes {"days": 7} → 52 bytes (129ms) tool=dividend_changes ms=129 bytes=52
prose written in 1 attempt(s) attempts=1
run 1 answered run=1 state=answered
en: .../out/2026/week-ahead-W43/en.md locale=en
```

Three minutes and twenty-six seconds, exit 0, seven files. "The post's own lines left out" was the
last fix: `--week-ahead` prints the post to stdout, which is right in a terminal and was about 600
lines of YAML in the journal. Under `--weekly` the files are the post, and nothing is printed. Run
again, it took 0.6 seconds and touched neither the GPU nor the model:

```
run 1, 2026-W43's, is written run=1 period=2026-W43
```

## What I'm taking on

- A job that a timer retries must be safe to run twice. Write the test with the data you actually
  have, not one tidy run per week.
- The standard library's logger is enough. What changes is the formatter, and only when someone
  else reads the lines.
- Check the platform's defaults in its own manual before writing them into a comment.
- "Not now" deserves its own exit code. A scheduler can only act on numbers.
- Run what you merged, not what you have checked out.

---

**Previous:** [Lesson 12 — A merge is a verdict](12-a-merge-is-a-verdict.md) · **Next:** [Lesson 14 — What I changed before merging](14-what-i-changed-before-merging.md)
