import json
from argparse import ArgumentTypeError
from pathlib import Path

import pytest
from conftest import FakeOllama, Reply

from quantic_agent.bench import filler_prompt, main, parse_sizes

ROOT = Path(__file__).resolve().parent.parent


def bench_server(ollama: FakeOllama, *, on_gpu: bool) -> None:
    """The three endpoints a run touches, with numbers chosen so the rates are
    exact: 2000 prompt tokens in 0.5s is 4000 tok/s, 100 generated tokens in
    2s is 50 tok/s."""
    vram = 6222564555 if on_gpu else 0
    ollama.replies["/api/tags"] = Reply(
        b'{"models":[{"name":"qwen3.5:9b","size":6594474711,'
        b'"details":{"parameter_size":"9.7B","quantization_level":"Q4_K_M"},'
        b'"capabilities":["completion","tools"]}]}'
    )
    ollama.replies["/api/generate"] = Reply(
        b'{"model":"qwen3.5:9b","response":"done","done":true,'
        b'"done_reason":"stop","prompt_eval_count":2000,"prompt_eval_duration":500000000,'
        b'"eval_count":100,"eval_duration":2000000000,"total_duration":2500000000,'
        b'"load_duration":1000000000}'
    )
    ollama.replies["/api/ps"] = Reply(
        b'{"models":[{"name":"qwen3.5:9b","size":6222564555,'
        b'"size_vram":%d,"context_length":4096}]}' % vram
    )


def run(ollama: FakeOllama, *args: str) -> int:
    return main(["--ollama", ollama.url, "--contexts", "4096", *args])


def test_table(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    bench_server(ollama, on_gpu=True)

    assert run(ollama, "--models", "qwen3.5:9b", "--predict", "100") == 0
    out = capsys.readouterr().out
    for want in ["qwen3.5:9b", "4K", "4000", "50.0", "100%"]:
        assert want in out


def test_cpu_fallback_is_unmissable(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    bench_server(ollama, on_gpu=False)

    # A model that isn't on the GPU is the most important thing this tool can
    # tell you.
    assert run(ollama, "--models", "qwen3.5:9b") == 0
    assert "0% (CPU)" in capsys.readouterr().out


def test_json(ollama: FakeOllama, capsys: pytest.CaptureFixture[str]) -> None:
    bench_server(ollama, on_gpu=True)

    assert run(ollama, "--models", "qwen3.5:9b", "--json") == 0
    results = json.loads(capsys.readouterr().out)

    assert len(results) == 1
    got = results[0]
    assert got["prompt_tokens_per_second"] == 4000
    assert got["generated_tokens_per_second"] == 50
    assert got["fraction_on_gpu"] == 1
    assert got["load_seconds"] == 1


def test_json_keys_match_the_kept_benchmarks(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    bench_server(ollama, on_gpu=True)
    kept = json.loads((ROOT / "docs/benchmarks/2026-09-24-bench.json").read_text())

    assert run(ollama, "--models", "qwen3.5:9b", "--json") == 0
    new = json.loads(capsys.readouterr().out)

    # The Go version wrote these files; a new run must compare with them.
    assert list(new[0]) == list(kept[0])


def test_a_model_that_was_not_pulled_is_skipped(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    bench_server(ollama, on_gpu=True)

    assert run(ollama, "--models", "not-pulled:latest") == 1
    assert "not-pulled:latest is not on this server" in capsys.readouterr().err


def test_model_names_match_case_insensitively(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    bench_server(ollama, on_gpu=True)

    # A hand-typed hf.co/... name in the wrong case must still be found.
    # Residency is matched by name as well, so 100% proves both lookups.
    assert run(ollama, "--models", "QWEN3.5:9B", "--predict", "100") == 0
    assert "100%" in capsys.readouterr().out


def test_a_short_generation_sample_is_flagged(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    bench_server(ollama, on_gpu=True)  # the fake server always generates 100 tokens

    assert run(ollama, "--models", "qwen3.5:9b", "--predict", "128") == 0
    assert "stopped after 100 of 128 tokens" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "want"),
    [
        pytest.param("4096", [4096], id="one"),
        pytest.param("4096, 32768", [4096, 32768], id="several with spaces"),
    ],
)
def test_parse_sizes(text: str, want: list[int]) -> None:
    assert parse_sizes(text) == want


@pytest.mark.parametrize("text", ["4096,big", "0", "-5", ""])
def test_parse_sizes_refuses(text: str) -> None:
    with pytest.raises(ArgumentTypeError):
        parse_sizes(text)


def test_a_bad_size_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--contexts", "4096,big"])
    assert exit_.value.code == 2
    assert "context size 'big' is not a positive number of tokens" in capsys.readouterr().err


def test_every_filler_prompt_is_unique() -> None:
    # Ollama's prefix cache would otherwise answer a repeated prompt for free.
    assert filler_prompt(100) != filler_prompt(100)


def test_filler_prompt_is_about_the_size_asked() -> None:
    assert 4000 <= len(filler_prompt(1000)) < 4000 + 100
