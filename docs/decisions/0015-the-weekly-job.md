# 0015 — The weekly job: one idempotent command, a systemd user timer, logs for the journal

**Status:** accepted · **Date:** 2026-10-14

## Context

Milestone 12 left three commands to run by hand each week: `--week-ahead`, `--pr N` and `--sync`.
The content plan makes the Week Ahead a Sunday post ([content.md](../content.md)). Design open
question 5 weighed a daemon against "systemd timers invoking a one-shot command", and open question
4 asked that re-running after a crash never produce a second post for a week. The machine is the
author's desktop: it isn't always on, and its GPU is shared (design §3.6): with a game running on
2026-10-14, other programs held 9.5GB of 16, and Ollama got 5.4GB for a 14GB model. Design §4 left
logging "chosen at milestone 13: structured, and feeds N3". Nothing the agent printed said how
serious it was.

## Decision

The author chose, from options put to them:

1. **One command, `--weekly`, for the whole week**, safe to run again at any time: sync the
   verdicts; then next week's post, which is left alone once any of its runs has a pull request
   (open, merged or closed: a week reviewed is done, whatever the verdict), resumed if its run
   stopped or failed, started if none exists; then a pull request for an answered post that has
   none. The week of a run is the week after the day it started, as for its post; the natural key
   of open question 4 is (kind, week), found among the runs rather than stored.
2. **A systemd user timer, Sundays at 07:00**, `Persistent=true`, running the `uv tool` install of
   `main`, not a working copy. Exit 3 is retried every 30 minutes for up to 12 hours; 4, 5 and 6
   are outcomes, not failures; 1 and 2 aren't retried.
3. **It steps aside when the GPU is in use**: before starting a model, `nvidia-smi`'s memory in use
   less Ollama's own runners; over 4096 MiB (`--gpu-max-others`), exit 3, so systemd tries again
   later. Graphics-only processes (the compositor, a browser) aren't in the compute-process list,
   so it's the total less Ollama, not a sum of the list: with the game running, the list held
   7.5GB and the card 9.5GB. No `nvidia-smi`, no check.
4. **Logging with the standard library**, one logger, to stderr. In a terminal, the messages read
   as before. When stderr is the journal (`JOURNAL_STREAM` names it), each line starts with its
   syslog priority (`<3>`, `<4>`, `<6>`), which journald stores as the entry's level, and ends with
   the event's fields as `key=value`. No new dependency: python-systemd's native fields would need
   a C library at install time.

## Consequences

- The first `--weekly` run against the real database opened a second pull request for a week
  already published (quantic#494, closed unmerged): three answered runs for that week, and it took
  the newest, not the one with a pull request. The rule in point 1 is that fix, and a test with
  the same three runs keeps it.
- A user timer runs only while the author is logged in; a Sunday missed runs at the next login.
  Linger (`loginctl enable-linger`) would run it without a session, but the agent needs the
  author's Ollama anyway.
- A run killed without a chance to record it (`kill -9`, a power cut) stays `running` and blocks
  its week until someone looks: telling it apart from a run in progress would need a lock or a
  process id in the store.
- The GPU check measures memory, not use: a program holding little memory but all of the compute
  doesn't stop it.
- stdout is buffered when it isn't a terminal: the unit sets `PYTHONUNBUFFERED=1`, or `--sync`'s
  lines reached the journal after stderr lines written later.
