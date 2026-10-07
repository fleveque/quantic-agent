import os
import re
import signal
import threading

import pytest
from conftest import DEAD_URL, FakeMCP, FakeOllama, Reply, fixture

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


def research_servers(ollama: FakeOllama, quantic_mcp: FakeMCP) -> None:
    # A real exchange with qwen3.5:9b: it asks for the calendar, then answers.
    ollama.replies["/api/chat"] = [
        Reply(fixture("chat-tool-call.json")),
        Reply(fixture("chat-tool-answer.json")),
    ]
    quantic_mcp.tools["dividend_calendar"] = "call-dividend-calendar.sse"


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


def test_research_without_quantic_exits_3(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["--ollama", ollama.url, "--mcp", DEAD_URL + "/mcp", "--research", "q"])

    assert code == 3
    assert f"no MCP server answering at {DEAD_URL}/mcp" in capsys.readouterr().err


def test_research_reports_figures_no_tool_returned(
    ollama: FakeOllama, quantic_mcp: FakeMCP, capsys: pytest.CaptureFixture[str]
) -> None:
    research_servers(ollama, quantic_mcp)
    # The same exchange, but the answer claims a window the data doesn't cover.
    ollama.replies["/api/chat"] = [
        Reply(fixture("chat-tool-call.json")),
        Reply(
            b'{"model":"qwen3.5:9b","message":{"role":"assistant","content":'
            b'"Over the next 180 days, Microsoft goes ex-dividend on Oct 8."},"done":true}'
        ),
    ]

    code = main(["--ollama", ollama.url, "--mcp", quantic_mcp.url, "--research", "q"])

    assert code == 4
    out, err = capsys.readouterr()
    # The answer is still shown, so a person can see what was claimed...
    assert "180 days" in out
    # ...and the figure with no source is named; the date traces to the data.
    assert "1 figure(s) in the answer came from no tool result" in err
    assert "'180' (number 180)" in err
    assert "Oct 8" not in err
