import json
import os
import re
import signal
import sqlite3
import threading
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from conftest import DEAD_URL, FakeGitHub, FakeMCP, FakeOllama, Reply, fixture

from quantic_agent import cli, quantic, store, weekahead
from quantic_agent.agent import Call
from quantic_agent.cli import main


def test_no_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    out, err = capsys.readouterr()
    assert out == "quantic-agent: no tasks defined yet\n"
    assert err == ""


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--version"])
    assert exit_.value.code == 0
    assert capsys.readouterr().out == "quantic-agent 0.0.0\n"


def test_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--help"])
    assert exit_.value.code == 0
    assert "--version" in capsys.readouterr().out


def test_unknown_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--publish"])
    assert exit_.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "unrecognized arguments: --publish" in err


TAGS = (
    b'{"models":[{"name":"qwen3.5:9b","size":6594474711,'
    b'"details":{"parameter_size":"9.7B","quantization_level":"Q4_K_M",'
    b'"context_length":262144},"capabilities":["completion","tools","thinking"]}]}'
)


def test_ask(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    ollama.replies["/api/generate"] = Reply(
        b'{"model":"quantic-9b:latest","response":"ok","done":true,'
        b'"done_reason":"stop","eval_count":2,"eval_duration":205098000}'
    )

    assert main(["--ollama", ollama.url, "--ask", "Reply with exactly: ok"]) == 0
    out, err = capsys.readouterr()
    assert out == "ok\n"
    # The run line goes to stderr so that stdout stays pipeable.
    assert err == "quantic-9b:latest · 2 tokens · 205ms\n"
    # Thinking is suppressed for every question.
    assert ollama.bodies[0]["think"] is False


def check_server(ollama: FakeOllama) -> None:
    ollama.replies["/api/version"] = Reply(b'{"version":"0.30.3"}')
    ollama.replies["/api/tags"] = Reply(TAGS)


def test_check(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    check_server(ollama)

    assert main(["--ollama", ollama.url, "--model", "qwen3.5:9b", "--check"]) == 0
    out = capsys.readouterr().out
    for want in ["ollama 0.30.3", "* qwen3.5:9b", "6.6 GB", "256K", "tools"]:
        assert want in out


def test_check_fails_for_a_model_that_was_not_pulled(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    check_server(ollama)

    # A model never pulled on the target machine has to fail here, not later
    # in the middle of a task.
    assert main(["--ollama", ollama.url, "--model", "not-pulled:latest", "--check"]) == 1
    assert "not-pulled:latest is not on this server" in capsys.readouterr().err


def test_check_matches_model_names_case_insensitively(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    check_server(ollama)

    # Ollama resolves names case-insensitively, so --check must too, or it
    # reports a perfectly usable model as missing.
    assert main(["--ollama", ollama.url, "--model", "QWEN3.5:9B", "--check"]) == 0
    assert "* qwen3.5:9b" in capsys.readouterr().out


@pytest.mark.parametrize("action", [["--ask", "hi"], ["--check"]], ids=["ask", "check"])
def test_an_unreachable_server_exits_3(
    action: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    # 3, not 1: nothing was attempted, so a scheduler can retry the run.
    assert main(["--ollama", DEAD_URL, *action]) == 3
    out, err = capsys.readouterr()
    assert out == ""
    assert "Is Ollama running?" in err


def test_ask_says_how_to_pull_a_missing_model(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    # What Ollama 0.34.4 answers for a model it doesn't have.
    ollama.replies["/api/generate"] = Reply(
        b'{"error":"model \'not-pulled:latest\' not found"}', 404
    )

    assert main(["--ollama", ollama.url, "--model", "not-pulled:latest", "--ask", "hi"]) == 1
    assert "ollama pull not-pulled:latest" in capsys.readouterr().err


def test_a_server_failure_points_at_its_log(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama.replies["/api/generate"] = Reply(b"", 500)

    assert main(["--ollama", ollama.url, "--ask", "hi"]) == 1
    err = capsys.readouterr().err
    assert "500 Internal Server Error" in err
    assert "journalctl -u ollama" in err


def test_the_server_and_model_come_from_the_environment(
    ollama: FakeOllama, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    check_server(ollama)
    # OLLAMA_HOST is conventionally host:port, with no scheme.
    monkeypatch.setenv("OLLAMA_HOST", ollama.host_port)
    monkeypatch.setenv("QUANTIC_MODEL", "qwen3.5:9b")

    assert main(["--check"]) == 0
    assert "* qwen3.5:9b" in capsys.readouterr().out


def test_check_and_ask_are_one_or_the_other(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--check", "--ask", "hi"])
    assert exit_.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err


def test_timeout_gives_up(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    ollama.replies["/api/generate"] = Reply(hang=True)

    assert main(["--ollama", ollama.url, "--timeout", "0.2", "--ask", "hi"]) == 1
    assert "gave up after 0.2s (--timeout)" in capsys.readouterr().err
    assert ollama.wait_for_hangups(1)


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM], ids=["ctrl-c", "sigterm"])
def test_a_signal_cancels_the_request_in_flight(
    ollama: FakeOllama, signum: signal.Signals, capsys: pytest.CaptureFixture[str]
) -> None:
    ollama.replies["/api/generate"] = Reply(hang=True)
    # The real signal, to this process, while the request hangs.
    threading.Timer(0.3, os.kill, (os.getpid(), signum)).start()

    assert main(["--ollama", ollama.url, "--ask", "hi"]) == 130
    assert "the request in flight was cancelled" in capsys.readouterr().err
    # Cancelling closed the connection, so Ollama would stop generating.
    assert ollama.wait_for_hangups(1)


def research_servers(ollama: FakeOllama, quantic_mcp: FakeMCP, answer: bytes | None = None) -> None:
    # A real exchange with qwen3.5:9b: it asks for the calendar, then answers,
    # which ends research (its answer is discarded). The writer then answers,
    # with answer if given, or the same real answer.
    writer = fixture("chat-tool-answer.json") if answer is None else answer
    ollama.replies["/api/chat"] = [
        Reply(fixture("chat-tool-call.json")),
        Reply(fixture("chat-tool-answer.json")),
        Reply(writer),
    ]
    quantic_mcp.tools["dividend_calendar"] = "call-dividend-calendar.sse"


def says(text: str) -> bytes:
    """A model reply with text as its answer."""
    message = {"role": "assistant", "content": text}
    return json.dumps({"model": "qwen3.5:9b", "message": message, "done": True}).encode()


def test_research(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    research_servers(ollama, quantic_mcp)

    code = main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "next 10 days?"])

    assert code == 0
    out, err = capsys.readouterr()
    assert "ex-dividend" in out
    # Each tool call is traced on stderr as it completes.
    assert re.search(r'tool dividend_calendar \{"days": 10\} → \d+ bytes \(\d+ms\)', err)
    assert quantic_mcp.calls() == [{"name": "dividend_calendar", "arguments": {"days": 10}}]
    # Two research turns, then the writer: offered no tools, told the date the
    # run started, and given the data.
    research, writer = ollama.bodies[:2], ollama.bodies[2]
    assert all("tools" in body for body in research)
    assert "tools" not in writer
    assert re.match(
        r"Today's date: \d{4}-\d{2}-\d{2}\n\nQuestion: next 10 days\?",
        writer["messages"][1]["content"],
    )


def test_research_without_quantic_exits_3(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--ollama", ollama.url, "--mcp", DEAD_URL + "/mcp", "--research", "q"])

    assert code == 3
    assert f"no MCP server answering at {DEAD_URL}/mcp" in capsys.readouterr().err


def test_research_reports_figures_no_tool_returned(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same exchange, but the answer claims a window the data doesn't cover.
    research_servers(
        ollama, quantic_mcp, says("Over the next 180 days, Microsoft goes ex-dividend on Oct 8.")
    )

    code = main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"])

    assert code == 4
    out, err = capsys.readouterr()
    # The answer is still shown, so a person can see what was claimed...
    assert "180 days" in out
    # ...and the figure with no source is named; the date traces to the data.
    assert "1 figure(s) in the answer came from no tool result" in err
    assert "'180' (number 180)" in err
    assert "Oct 8" not in err


def stored_runs(db_path: Path) -> list[store.Run]:
    with store.Store(db_path) as db:
        return [db.run(r.id) for r in db.runs(100)]


def test_research_records_the_run(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    research_servers(ollama, quantic_mcp)

    assert (
        main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "next 10 days?"]) == 0
    )
    assert "run 1 answered" in capsys.readouterr().err

    [run] = stored_runs(isolated_state)
    assert (run.input, run.model, run.state, run.phase) == (
        "next 10 days?",
        "qwen3.5:9b",
        store.State.ANSWERED,
        store.Phase.DONE,
    )
    # Every model turn's tokens, both phases: the fixtures' counts.
    assert run.tokens == (321 + 29) + (610 + 219) + (610 + 219)
    assert [(c.tool, c.arguments) for c in run.calls] == [("dividend_calendar", {"days": 10})]
    assert run.draft is not None
    assert run.draft.findings == []


def test_runs_and_run_read_the_history_back(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    research_servers(ollama, quantic_mcp)
    main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "next 10 days?"])
    capsys.readouterr()

    # Neither needs the model server or Quantic.
    assert main(["--runs"]) == 0
    listing = capsys.readouterr().out
    assert re.search(
        r"^1\s+\S+ \S+\s+answered\s+done\s+1\s+2008\s+next 10 days\?$", listing, re.MULTILINE
    )

    assert main(["--run", "1"]) == 0
    shown = capsys.readouterr().out
    assert 'call 0: dividend_calendar {"days": 10} →' in shown
    assert "every figure traces to a stored tool result" in shown


def test_run_rechecks_an_unverified_answer(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    research_servers(ollama, quantic_mcp, says("In 180 days."))
    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 4
    capsys.readouterr()

    # Re-checked against the stored results, not the tools as they are today.
    assert main(["--run", "1"]) == 4
    assert "'180' (number 180)" in capsys.readouterr().out


def test_a_missing_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--run", "7"]) == 1
    assert "there is no run 7" in capsys.readouterr().err


def test_a_timed_out_run_is_recorded_as_failed(
    ollama: FakeOllama, quantic_mcp: FakeMCP, isolated_state: Path
) -> None:
    research_servers(ollama, quantic_mcp)
    quantic_mcp.tools["dividend_calendar"] = "hang"

    args = ["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--timeout", "0.5", "--research", "q"]
    assert main(args) == 1

    [run] = stored_runs(isolated_state)
    assert (run.state, run.error) == (store.State.FAILED, "gave up after 0.5s")


def test_an_interrupted_run_is_recorded(
    ollama: FakeOllama, quantic_mcp: FakeMCP, isolated_state: Path
) -> None:
    research_servers(ollama, quantic_mcp)
    quantic_mcp.tools["dividend_calendar"] = "hang"
    threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 130

    # Saved even though the task was being cancelled: the save is synchronous.
    [run] = stored_runs(isolated_state)
    assert run.state is store.State.INTERRUPTED
    assert run.finished_at is not None


def test_research_with_no_data_writes_nothing(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The model answers from memory, calling no tool.
    ollama.replies["/api/chat"] = [Reply(says("Microsoft, I believe, on Oct 8."))]

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 5

    out, err = capsys.readouterr()
    assert out == ""
    assert "research gathered no data" in err
    assert "quantic-agent --resume 1" in err
    # The writer was never asked.
    assert len(ollama.bodies) == 1
    [run] = stored_runs(isolated_state)
    assert (run.state, run.phase, run.draft) == (store.State.NO_DATA, store.Phase.RESEARCH, None)


def stopped_run(
    db_path: Path,
    phase: store.Phase,
    question: str = "next 10 days?",
    started: datetime | None = None,
) -> int:
    """A run stopped in phase, with the real calendar call recorded."""
    sse = (Path(__file__).parent / "fixtures" / "mcp" / "call-dividend-calendar.sse").read_text()
    data = json.loads(next(line for line in sse.splitlines() if line.startswith("data: "))[6:])
    calendar = data["result"]["content"][0]["text"]
    clock = (lambda: started) if started else None
    with store.Store(db_path, now=clock) as db:
        run_id = db.start_run("research", question, "qwen3.5:9b")
        db.record_call(run_id, 0, Call("dividend_calendar", {"days": 10}, calendar))
        if phase is store.Phase.WRITE:
            db.checkpoint(run_id, phase, 1179, None)
        db.finish(run_id, store.State.INTERRUPTED)
    return run_id


def test_a_run_stopped_while_writing_resumes_without_tools(
    ollama: FakeOllama, isolated_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_id = stopped_run(isolated_state, store.Phase.WRITE)
    ollama.replies["/api/chat"] = [Reply(fixture("chat-tool-answer.json"))]

    # No MCP server at all: a run past research doesn't need one. And the
    # model is the run's own, whatever --model says.
    args = ["--ollama", ollama.url, "--mcp", DEAD_URL, "--model", "other", "--resume", str(run_id)]
    assert main(args) == 0

    assert (
        "resuming run 1 in its write phase, with 1 tool call(s) recorded" in capsys.readouterr().err
    )
    [writer] = ollama.bodies
    assert writer["model"] == "qwen3.5:9b"
    [run] = stored_runs(isolated_state)
    assert (run.state, run.phase, run.tokens) == (
        store.State.ANSWERED,
        store.Phase.DONE,
        1179 + 829,
    )


def test_a_run_stopped_while_researching_replays_its_calls(
    ollama: FakeOllama, quantic_mcp: FakeMCP, isolated_state: Path
) -> None:
    run_id = stopped_run(isolated_state, store.Phase.RESEARCH)
    ollama.replies["/api/chat"] = [Reply(fixture("chat-tool-answer.json"))]

    args = ["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--resume", str(run_id)]
    assert main(args) == 0

    # The model was shown the recorded call and its result; Quantic wasn't
    # asked again.
    roles = [m["role"] for m in ollama.bodies[0]["messages"]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert quantic_mcp.calls() == []
    [run] = stored_runs(isolated_state)
    assert run.state is store.State.ANSWERED


def test_an_answered_run_cant_be_resumed(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    research_servers(ollama, quantic_mcp)
    main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"])
    capsys.readouterr()

    assert main(["--ollama", ollama.url, "--resume", "1"]) == 1
    assert "run 1 can't be resumed" in capsys.readouterr().err


def test_a_rate_limit_that_doesnt_clear_exits_3(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    research_servers(ollama, quantic_mcp)
    quantic_mcp.rate_limited = 100
    monkeypatch.setattr(quantic, "DEFAULT_BACKOFF", quantic.Backoff(attempts=3, base=0.01))

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 3

    err = capsys.readouterr().err
    assert re.search(r"Quantic's rate limit; retry 1 of initialize in 0\.0s", err)
    assert "Quantic's rate limit didn't clear; resume the run later." in err
    [run] = stored_runs(isolated_state)
    assert run.state is store.State.FAILED


def test_the_question_and_the_date_are_sources(
    ollama: FakeOllama, isolated_state: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Repeating the question's "seven months", or the date the run started
    # (which the writer is told is today), invents nothing; "four" does. The
    # calendar has none of them: ten days, six stocks, other dates.
    question = "What goes ex-dividend in the next seven months?"
    started = datetime(2026, 11, 30, 12, tzinfo=UTC)
    run_id = stopped_run(isolated_state, store.Phase.WRITE, question, started)
    ollama.replies["/api/chat"] = [Reply(says("As of 2026-11-30, over seven months: four."))]

    assert main(["--ollama", ollama.url, "--mcp", DEAD_URL, "--resume", str(run_id)]) == 4

    err = capsys.readouterr().err
    assert "1 figure(s) in the answer came from no tool result" in err
    assert "'four' (number 4)" in err
    # The writer was told the day the run started, not the day it resumed.
    assert ollama.bodies[0]["messages"][1]["content"].startswith("Today's date: 2026-11-30")


def test_a_run_stopped_while_writing_is_checkpointed(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    research_servers(ollama, quantic_mcp)
    replies = ollama.replies["/api/chat"]
    assert isinstance(replies, list)
    replies[2] = Reply(b"", hang=True)  # the writer never answers
    threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 130

    assert "quantic-agent --resume 1" in capsys.readouterr().err
    # Research's work is kept: resuming starts at writing, calling no tool.
    [run] = stored_runs(isolated_state)
    assert (run.state, run.phase, run.tokens) == (
        store.State.INTERRUPTED,
        store.Phase.WRITE,
        (321 + 29) + (610 + 219),
    )


def test_research_asks_for_its_context_window(ollama: FakeOllama, quantic_mcp: FakeMCP) -> None:
    research_servers(ollama, quantic_mcp)

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 0
    # Every turn, research and writing, asks for the same window: a model
    # loaded with another size would be reloaded.
    assert {b["options"]["num_ctx"] for b in ollama.bodies} == {32768}


def test_the_context_window_can_be_chosen(
    ollama: FakeOllama, quantic_mcp: FakeMCP, monkeypatch: pytest.MonkeyPatch
) -> None:
    research_servers(ollama, quantic_mcp)
    monkeypatch.setenv("QUANTIC_NUM_CTX", "16384")

    args = ["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]
    assert main([*args, "--num-ctx", "8192"]) == 0
    research_servers(ollama, quantic_mcp)
    assert main(args) == 0

    sizes = [b["options"]["num_ctx"] for b in ollama.bodies]
    assert sizes == [8192] * 3 + [16384] * 3


def test_several_questions_take_turns_at_the_model(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Every model turn answers without a tool, so each run ends no_data. The
    # point is how they ran: at once, but one at a time at the model.
    ollama.replies["/api/chat"] = Reply(says("From memory."), delay=0.1)
    questions = ["--research", "first?", "--research", "second?", "--research", "third?"]

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, *questions]) == 5

    assert ollama.peak == 1
    err = capsys.readouterr().err
    for n in (1, 2, 3):
        assert f"run {n}: research gathered no data" in err
    runs = stored_runs(isolated_state)
    assert sorted(r.input for r in runs) == ["first?", "second?", "third?"]
    assert {r.state for r in runs} == {store.State.NO_DATA}


def test_a_stopped_batch_records_every_run(
    ollama: FakeOllama, quantic_mcp: FakeMCP, isolated_state: Path
) -> None:
    # The first run holds the GPU, the second waits for it; SIGTERM stops both.
    ollama.replies["/api/chat"] = Reply(b"", hang=True)
    threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()

    args = ["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "a", "--research", "b"]
    assert main(args) == 130

    runs = stored_runs(isolated_state)
    assert [r.state for r in runs] == [store.State.INTERRUPTED] * 2


# ---- reviews and style memory ------------------------------------------------


def embeds(vector: list[float]) -> Reply:
    """An /api/embed reply with one vector."""
    reply = {"model": "qwen3-embedding:0.6b", "embeddings": [vector]}
    return Reply(json.dumps(reply).encode())


def approved_run(ollama: FakeOllama, quantic_mcp: FakeMCP, answer: bytes | None = None) -> None:
    """Run 1: answered, then approved, its vector [1, 0]."""
    research_servers(ollama, quantic_mcp, answer)
    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 0
    ollama.replies["/api/embed"] = embeds([1.0, 0.0])
    assert main(["--ollama", ollama.url, "--approve", "1", "--note", "the house voice"]) == 0


def test_approving_embeds_the_answer(
    ollama: FakeOllama, quantic_mcp: FakeMCP, isolated_state: Path
) -> None:
    approved_run(ollama, quantic_mcp)

    embed = next(b for b, p in zip(ollama.bodies, ollama.paths, strict=True) if p == "/api/embed")
    [run] = stored_runs(isolated_state)
    assert run.draft is not None
    assert embed == {
        "model": "qwen3-embedding:0.6b",
        "input": [run.draft.content],
        "truncate": False,
    }
    assert run.review is not None
    assert (run.review.verdict, run.review.note) == ("approved", "the house voice")


def test_an_unverified_answer_cant_be_approved(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    research_servers(ollama, quantic_mcp, says("In 180 days."))
    main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"])
    ollama.replies["/api/embed"] = embeds([1.0, 0.0])
    capsys.readouterr()

    assert main(["--ollama", ollama.url, "--approve", "1"]) == 1
    assert "only an answer whose every figure traced can be approved" in capsys.readouterr().err


def test_the_writer_is_shown_approved_answers(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    approved_run(ollama, quantic_mcp)
    [example] = stored_runs(isolated_state)
    assert example.draft is not None
    research_servers(ollama, quantic_mcp)
    ollama.replies["/api/embed"] = embeds([0.9, 0.1])

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q2"]) == 0

    # The question was embedded as qwen3-embedding's documentation asks.
    embedded = [b for b, p in zip(ollama.bodies, ollama.paths, strict=True) if p == "/api/embed"]
    assert embedded[-1]["input"][0].startswith("Instruct: Given a question, retrieve answers")
    assert embedded[-1]["input"][0].endswith("Query: q2")
    writer = ollama.bodies[-1]["messages"][1]["content"]
    assert "Their facts, dates and figures are out of date: use none of them." in writer
    assert f"Example 1:\n{example.draft.content}" in writer
    # Recorded, and shown with the run.
    capsys.readouterr()
    assert main(["--run", "2"]) == 0
    assert "examples shown to its writer: run 1 (0.994)" in capsys.readouterr().out


def test_an_example_cant_vouch_for_a_figure(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # An approved answer whose 4.2% traced to its own run's data...
    with store.Store(isolated_state) as db:
        run_id = db.start_run("research", "KO's yield?", "qwen3.5:9b")
        db.record_call(run_id, 0, Call("get_stock", {"symbol": "KO"}, '{"yield": 4.2}'))
        db.finish(run_id, store.State.ANSWERED, draft=store.Draft("A yield of 4.2%.", False, []))
    ollama.replies["/api/embed"] = embeds([1.0, 0.0])
    assert main(["--ollama", ollama.url, "--approve", str(run_id)]) == 0
    # ...copied by a later writer into an answer about other data.
    research_servers(
        ollama, quantic_mcp, says("Microsoft goes ex-dividend on Oct 8, a yield of 4.2%.")
    )
    capsys.readouterr()

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q2"]) == 4

    # The example was shown, and its figure traced to nothing: examples are
    # language, not data, and never enter the manifest.
    assert "A yield of 4.2%." in ollama.bodies[-1]["messages"][1]["content"]
    assert "'4.2%' (number 4.2)" in capsys.readouterr().err


def test_with_nothing_approved_nothing_is_embedded(
    ollama: FakeOllama, quantic_mcp: FakeMCP
) -> None:
    research_servers(ollama, quantic_mcp)

    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 0
    assert "/api/embed" not in ollama.paths


def test_recall_and_reject(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    approved_run(ollama, quantic_mcp)
    capsys.readouterr()

    assert main(["--ollama", ollama.url, "--recall", "what goes ex-dividend?"]) == 0
    assert capsys.readouterr().out.startswith("run 1 · 1.000\n")

    assert main(["--reject", "1", "--note", "too long"]) == 0
    assert main(["--ollama", ollama.url, "--recall", "what goes ex-dividend?"]) == 0
    assert "no approved answers embedded with qwen3-embedding:0.6b" in capsys.readouterr().out


# ---- the Week Ahead ------------------------------------------------------------


def asks_for(*calls: tuple[str, Mapping[str, object]]) -> Reply:
    """A model reply asking for tools, each by name with its arguments."""
    requests = [{"function": {"name": name, "arguments": args}} for name, args in calls]
    message = {"role": "assistant", "content": "", "tool_calls": requests}
    reply = {"model": "qwen3.5:9b", "message": message, "done": True, "prompt_eval_count": 100}
    return Reply(json.dumps(reply).encode())


ENGLISH = {
    "summary": "Procter & Gamble and Coca-Cola go ex-dividend late in the week.",
    "watch": "Coca-Cola is rated safe, while Procter & Gamble is on watch for tight liquidity.",
}


def prose(sections: dict[str, str]) -> Reply:
    return Reply(says(json.dumps(sections)))


def translated(locale: str) -> Reply:
    """A translation that passes its checks: the English, marked with its locale."""
    return prose({key: f"[{locale}] {text}" for key, text in ENGLISH.items()})


LOOKUPS = (("get_stock", {"symbol": "PG"}), ("get_stock", {"symbol": "KO"}))


def week_ahead_servers(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    *,
    research: list[Reply] | None = None,
    writer: list[Reply] | None = None,
    translations: dict[str, Reply] | None = None,
) -> None:
    """Thursday 2026-10-08, when the fixtures were captured from Quantic:
    the week after has Procter & Gamble and Coca-Cola in it. The model asks
    for the calendar, then both companies at once, then stops; the writer
    and the six translators answer in turn."""
    monkeypatch.setattr(cli, "today", lambda: date(2026, 10, 8))
    quantic_mcp.tools.update(
        {
            "dividend_calendar": "call-calendar-45.sse",
            "get_stock:PG": "call-get-stock-pg.sse",
            "get_stock:KO": "call-get-stock-ko.sse",
        }
    )
    if research is None:
        research = [
            asks_for(("dividend_calendar", {"days": 45})),
            asks_for(*LOOKUPS),
            Reply(says("Done.")),
        ]
    locales = {loc: translated(loc) for loc in weekahead.TRANSLATED} | (translations or {})
    ollama.replies["/api/chat"] = [
        *research,
        *(writer or [prose(ENGLISH)]),
        *(locales[loc] for loc in weekahead.TRANSLATED),
    ]


def week_ahead(ollama: FakeOllama, quantic_mcp: FakeMCP, out: Path) -> int:
    return main(
        ["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--week-ahead", "--out", str(out)]
    )


def data_block(text: str) -> str:
    return text.split("\ndata:\n", 1)[1].split("\n---\n", 1)[0]


def test_week_ahead_writes_every_locale(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    week_ahead_servers(ollama, quantic_mcp, monkeypatch)

    assert week_ahead(ollama, quantic_mcp, tmp_path / "out") == 0

    folder = tmp_path / "out" / "week-ahead-2026-W42"
    files = {p.stem: p.read_text() for p in folder.iterdir()}
    assert sorted(files) == sorted(weekahead.LOCALES)
    # One data block, the same in every file; only the prose differs.
    assert len({data_block(text) for text in files.values()}) == 1
    assert "## Die kommende Woche\n\n[de] Procter & Gamble" in files["de"]
    out, err = capsys.readouterr()
    assert out == files["en"] + "\n"
    assert f"es: {folder / 'es.md'}" in err

    [run] = stored_runs(isolated_state)
    assert (run.kind, run.state, run.input) == (
        "week_ahead",
        store.State.ANSWERED,
        "Today is Thursday 2026-10-08. "
        "Gather the data for the Dividend Week Ahead, for the week from Monday 2026-10-12 "
        "to Sunday 2026-10-18: find every company that goes ex-dividend in that week, and "
        "look up each one. Sunday 2026-10-18 is 10 days from today.",
    )
    # The two lookups ran at once, recorded in the order they finished.
    calendar, *lookups = [(c.tool, c.arguments) for c in run.calls]
    assert calendar == ("dividend_calendar", {"days": 45})
    assert sorted(lookups, key=str) == [
        ("get_stock", {"symbol": "KO"}),
        ("get_stock", {"symbol": "PG"}),
    ]
    assert run.draft is not None
    assert run.draft.content == files["en"]
    assert [(p.locale, p.ready, p.content) for p in run.posts] == [
        (locale, True, files[locale]) for locale in weekahead.LOCALES
    ]


def test_the_writer_and_translators_are_asked_for_the_prose_format(
    ollama: FakeOllama, quantic_mcp: FakeMCP, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    week_ahead_servers(ollama, quantic_mcp, monkeypatch)
    assert week_ahead(ollama, quantic_mcp, tmp_path) == 0

    writer, *translators = ollama.bodies[3:]
    assert len(translators) == 6
    for body in [writer, *translators]:
        assert (body["format"], body["think"], body["options"]) == (
            weekahead.PROSE_FORMAT,
            False,
            {"num_ctx": 32768},
        )
        assert "tools" not in body
    languages = [
        t["messages"][0]["content"].split(" into ", 1)[1].split(",")[0] for t in translators
    ]
    assert languages == [
        "Spanish (Spain)",
        "Catalan",
        "French",
        "German",
        "Italian",
        "Brazilian Portuguese",
    ]


def test_a_held_translation_is_not_written(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    figure = prose({"summary": "[fr] 3 " + ENGLISH["summary"], "watch": "[fr] " + ENGLISH["watch"]})
    week_ahead_servers(ollama, quantic_mcp, monkeypatch, translations={"fr": figure})
    # An earlier run's French file, which this run's mustn't be mistaken for.
    folder = tmp_path / "week-ahead-2026-W42"
    folder.mkdir()
    (folder / "fr.md").write_text("an older post")

    assert week_ahead(ollama, quantic_mcp, tmp_path) == 6

    assert sorted(p.stem for p in folder.iterdir()) == sorted(
        loc for loc in weekahead.LOCALES if loc != "fr"
    )
    assert "fr: held: summary: figure '3'" in capsys.readouterr().err
    [run] = stored_runs(isolated_state)
    assert run.state is store.State.ANSWERED
    held = [p for p in run.posts if not p.ready]
    assert [(p.locale, p.problems) for p in held] == [("fr", ["summary: figure '3'"])]
    assert "[fr] 3 Procter" in held[0].content  # what was refused, kept for review


def test_prose_with_figures_publishes_nothing(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    counted = prose({"summary": "Two names go ex-dividend.", "watch": ENGLISH["watch"]})
    week_ahead_servers(ollama, quantic_mcp, monkeypatch, writer=[counted] * 3)

    assert week_ahead(ollama, quantic_mcp, tmp_path) == 4

    assert not (tmp_path / "week-ahead-2026-W42").exists()
    assert len(ollama.bodies) == 3 + 3  # research, then three writers; no translators
    assert "after 3 attempts the prose still has figures" in capsys.readouterr().err
    [run] = stored_runs(isolated_state)
    assert (run.state, run.posts) == (store.State.UNVERIFIED, [])
    assert run.draft is not None
    assert [str(f) for f in run.draft.findings] == ["'Two' (number 2)"]


def test_the_published_data_is_checked_against_the_tools(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    week_ahead_servers(ollama, quantic_mcp, monkeypatch)
    # Code that rounds a ratio on its way into the post.
    build = weekahead._row  # pyright: ignore[reportPrivateUsage]

    def rounding(*args: Any) -> weekahead.ExDividend:
        row = build(*args)
        return row.model_copy(update={"growth_ttm": round(row.growth_ttm or 0, 4)})

    monkeypatch.setattr(weekahead, "_row", rounding)

    assert week_ahead(ollama, quantic_mcp, tmp_path) == 1

    assert "data no tool returned: ex_dividends[0].growth_ttm = 0.0397" in capsys.readouterr().err
    assert not (tmp_path / "week-ahead-2026-W42").exists()


def test_a_week_not_fully_researched_fails_and_resumes(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The model reads the calendar and stops, without looking anyone up.
    research = [asks_for(("dividend_calendar", {"days": 45})), Reply(says("Done."))]
    week_ahead_servers(ollama, quantic_mcp, monkeypatch, research=research)

    assert week_ahead(ollama, quantic_mcp, tmp_path) == 1

    err = capsys.readouterr().err
    assert "research didn't gather the whole week: not looked up with get_stock: PG, KO" in err
    [run] = stored_runs(isolated_state)
    assert (run.state, run.phase) == (store.State.FAILED, store.Phase.RESEARCH)

    # Resumed, the calendar is replayed rather than called, and the model
    # looks the companies up. The week is the one after the day the run
    # started, which the store took from the real clock: set it to Thursday.
    with sqlite3.connect(isolated_state) as db:
        db.execute("UPDATE runs SET started_at = '2026-10-08T12:00:00+00:00'")
    week_ahead_servers(
        ollama, quantic_mcp, monkeypatch, research=[asks_for(*LOOKUPS), Reply(says("Done."))]
    )
    assert (
        main(
            [
                "--ollama",
                ollama.url,
                "--mcp",
                quantic_mcp.url,
                "--resume",
                "1",
                "--out",
                str(tmp_path),
            ]
        )
        == 0
    )

    assert [c["name"] for c in quantic_mcp.calls()] == [
        "dividend_calendar",
        "get_stock",
        "get_stock",
    ]
    [run] = stored_runs(isolated_state)
    assert (run.state, len(run.posts)) == (store.State.ANSWERED, 7)


def test_a_week_with_no_companies_writes_nothing(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    week_ahead_servers(ollama, quantic_mcp, monkeypatch)
    # Ten days later: the calendar captured on the 8th still covers the week
    # after, and nothing in it goes ex-dividend then.
    monkeypatch.setattr(cli, "today", lambda: date(2026, 10, 19))

    assert week_ahead(ollama, quantic_mcp, tmp_path / "out") == 5

    assert "no company goes ex-dividend from 2026-10-26 to 2026-11-01" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_a_week_ahead_run_is_shown_and_rechecked(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    week_ahead_servers(ollama, quantic_mcp, monkeypatch)
    assert week_ahead(ollama, quantic_mcp, tmp_path) == 0
    capsys.readouterr()

    assert main(["--run", "1"]) == 0
    shown = capsys.readouterr().out
    assert "post es: ready\n" in shown
    assert "streak_years: 28" in shown
    assert (
        "provenance, re-checked now: every value in the data traces to a stored tool "
        "result, and the prose has no figures"
    ) in shown

    # Its review is its pull request, not style memory for answering questions.
    assert main(["--ollama", ollama.url, "--approve", "1"]) == 1
    assert "run 1 is a week_ahead: only research answers can be approved" in (
        capsys.readouterr().err
    )


def test_a_post_is_recorded_before_its_files_are_written(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    week_ahead_servers(ollama, quantic_mcp, monkeypatch)
    blocked = tmp_path / "out"
    blocked.write_text("a file where the folder should be")

    assert week_ahead(ollama, quantic_mcp, blocked) == 1

    assert f"writing {blocked / 'week-ahead-2026-W42'}:" in capsys.readouterr().err
    # The files couldn't be written, but the run and its posts are on record.
    [run] = stored_runs(isolated_state)
    assert (run.state, len(run.posts)) == (store.State.ANSWERED, 7)


# ---- pull requests -------------------------------------------------------------


def as_the_app(
    monkeypatch: pytest.MonkeyPatch, github_api: FakeGitHub, key: str, tmp_path: Path
) -> Path:
    """The App's settings, as the environment gives them; returns its key file."""
    path = tmp_path / "github-app.pem"
    path.write_text(key)
    path.chmod(0o600)
    monkeypatch.setenv("QUANTIC_AGENT_GITHUB_APP_ID", "1")
    monkeypatch.setenv("QUANTIC_AGENT_GITHUB_KEY", str(path))
    monkeypatch.setenv("QUANTIC_AGENT_GITHUB_API", github_api.url)
    monkeypatch.setenv("QUANTIC_AGENT_REPO", github_api.repo)
    return path


def written_week(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    monkeypatch: pytest.MonkeyPatch,
    out: Path,
    translations: dict[str, Reply] | None = None,
) -> None:
    """A Week Ahead run, answered: run 1, unless runs came before it."""
    week_ahead_servers(ollama, quantic_mcp, monkeypatch, translations=translations)
    assert week_ahead(ollama, quantic_mcp, out) in (0, 6)


def test_a_week_ahead_run_becomes_a_pull_request(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    capsys.readouterr()

    assert main(["--pr", "1"]) == 0

    out, err = capsys.readouterr()
    assert out == "https://github.com/fleveque/quantic/pull/100\n"
    assert "run 1: pull request #100, 7 file(s), for review" in err
    bodies = {p.rsplit("/", 1)[1]: b for m, p, b, _ in github_api.requests if m == "POST"}
    [run] = stored_runs(isolated_state)
    # The files are the run's posts as recorded, under the repository path.
    assert {e["path"]: e["content"] for e in bodies["trees"]["tree"]} == {
        f"priv/insights/week-ahead-2026-W42/{p.locale}.md": p.content for p in run.posts
    }
    assert bodies["refs"]["ref"] == "refs/heads/agent/week-ahead-2026-W42-run-1"
    assert bodies["pulls"]["title"] == "Dividend Week Ahead, 2026-W42"
    body = bodies["pulls"]["body"]
    assert "**Merging publishes it.**" in body
    assert "These checks don't read the language" in body
    assert "- Procter & Gamble (PG), ex-dividend 2026-10-16" in body
    assert "Held back" not in body
    assert run.pull_request is not None
    assert (run.pull_request.number, run.pull_request.state, run.pull_request.period) == (
        100,
        "open",
        "2026-W42",
    )

    assert main(["--run", "1"]) == 0
    assert "pull request: https://github.com/fleveque/quantic/pull/100 (open)" in (
        capsys.readouterr().out
    )


def test_a_held_locale_stays_out_of_the_pull_request(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    figure = prose({"summary": "[fr] 3 " + ENGLISH["summary"], "watch": "[fr] " + ENGLISH["watch"]})
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out", {"fr": figure})
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)

    assert main(["--pr", "1"]) == 0

    bodies = {p.rsplit("/", 1)[1]: b for m, p, b, _ in github_api.requests if m == "POST"}
    paths = [e["path"] for e in bodies["trees"]["tree"]]
    assert "priv/insights/week-ahead-2026-W42/fr.md" not in paths
    assert len(paths) == 6
    assert "- **fr**: summary: figure '3'" in bodies["pulls"]["body"]


def test_only_an_answered_week_ahead_is_published(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    research_servers(ollama, quantic_mcp)
    assert main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"]) == 0
    counted = prose({"summary": "Two names go ex-dividend.", "watch": ENGLISH["watch"]})
    week_ahead_servers(ollama, quantic_mcp, monkeypatch, writer=[counted] * 3)
    assert week_ahead(ollama, quantic_mcp, tmp_path / "out") == 4
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    capsys.readouterr()

    assert main(["--pr", "1"]) == 1
    assert "run 1 is a research: only a Week Ahead is published" in capsys.readouterr().err
    assert main(["--pr", "2"]) == 1
    assert "run 2 is unverified: only a post that passed its checks" in capsys.readouterr().err
    assert github_api.requests == []


def test_one_pull_request_per_run_and_one_open_per_week(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    assert main(["--pr", "1"]) == 0
    capsys.readouterr()

    assert main(["--pr", "1"]) == 1
    assert "run 1 already has a pull request" in capsys.readouterr().err
    # Run 2 is the same week: it waits until #100 is merged or closed.
    assert main(["--pr", "2"]) == 1
    assert "2026-W42 already has an open pull request" in capsys.readouterr().err
    github_api.pulls[100] = "closed"
    assert main(["--sync"]) == 0
    assert main(["--pr", "2"]) == 0


@pytest.mark.parametrize(
    ("unset", "message"),
    [
        ("QUANTIC_AGENT_REPO", "no repository: give --repo OWNER/NAME"),
        ("QUANTIC_AGENT_GITHUB_APP_ID", "no GitHub App: set QUANTIC_AGENT_GITHUB_APP_ID"),
    ],
)
def test_a_missing_setting_is_named(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    unset: str,
    message: str,
) -> None:
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    monkeypatch.delenv(unset)

    assert main(["--pr", "1"]) == 1
    assert message in capsys.readouterr().err
    assert github_api.requests == []


def test_a_key_others_can_read_is_refused(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
    key = as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    key.chmod(0o644)

    assert main(["--pr", "1"]) == 1
    assert f"{key} is readable by others: chmod 600 {key}" in capsys.readouterr().err
    assert github_api.requests == []


def test_sync_records_merges_as_approvals_and_closes_as_rejections(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    for thursday in (date(2026, 10, 8), date(2026, 10, 1), date(2026, 9, 24)):
        written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
        # Each run its own week, so each can have a pull request open.
        with sqlite3.connect(isolated_state) as db:
            db.execute(
                "UPDATE runs SET started_at = ? WHERE id = (SELECT max(id) FROM runs)",
                (f"{thursday.isoformat()}T12:00:00+00:00",),
            )
    for run in ("1", "2", "3"):
        assert main(["--pr", run]) == 0
    github_api.pulls.update({100: "merged", 101: "closed", 102: "open"})
    capsys.readouterr()

    assert main(["--sync"]) == 0

    assert capsys.readouterr().out == (
        "run 1: https://github.com/fleveque/quantic/pull/100 merged: approved\n"
        "run 2: https://github.com/fleveque/quantic/pull/101 closed: rejected\n"
        "run 3: https://github.com/fleveque/quantic/pull/102 still open\n"
    )
    runs = {r.id: r for r in stored_runs(isolated_state)}
    assert runs[1].review is not None
    assert (runs[1].review.verdict, runs[1].review.note) == (
        "approved",
        "fleveque/quantic#100 merged",
    )
    assert runs[2].review is not None
    assert runs[2].review.verdict == "rejected"
    assert runs[3].review is None
    # Synced, a decided pull request isn't asked about again.
    asked = len(github_api.requests)
    assert main(["--sync"]) == 0
    assert [p for _, p, _, _ in github_api.requests[asked:] if "/pulls/" in p] == [
        "/repos/fleveque/quantic/pulls/102"
    ]


def test_github_not_answering_exits_3(
    ollama: FakeOllama,
    quantic_mcp: FakeMCP,
    github_api: FakeGitHub,
    app_key: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    isolated_state: Path,
) -> None:
    written_week(ollama, quantic_mcp, monkeypatch, tmp_path / "out")
    as_the_app(monkeypatch, github_api, app_key[0], tmp_path)
    monkeypatch.setenv("QUANTIC_AGENT_GITHUB_API", DEAD_URL)

    assert main(["--pr", "1"]) == 3
    [run] = stored_runs(isolated_state)
    assert run.pull_request is None
