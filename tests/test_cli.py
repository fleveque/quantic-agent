import json
import os
import re
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import DEAD_URL, FakeMCP, FakeOllama, Reply, fixture

from quantic_agent import quantic, store
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
