import subprocess
from collections.abc import Sequence

from conftest import nvidia_smi

from quantic_agent import gpu


def test_others_are_the_total_not_the_list() -> None:
    # 2026-10-14, GTA V running. The list's processes hold 7.5GB; the card,
    # 9.5GB: the rest is graphics-only processes the list leaves out (the
    # compositor, a browser). The total less Ollama counts them.
    usage = gpu.parse(nvidia_smi("game-gpu.csv"), nvidia_smi("game-apps.csv"))
    assert usage == gpu.Usage(used=9518, total=16376, ollama=0)
    assert usage.others == 9518


def test_ollamas_own_runner_isnt_another_program() -> None:
    # The same minute, with the 27B loaded: llama-server, under Ollama's path.
    usage = gpu.parse(nvidia_smi("game-and-model-gpu.csv"), nvidia_smi("game-and-model-apps.csv"))
    assert (usage.used, usage.ollama, usage.others) == (14955, 5432, 9523)


def test_a_name_with_a_comma_and_memory_it_cant_report() -> None:
    apps = "1, /usr/local/lib/ollama/llama-server, 5000\n2, C:\\Games, Inc\\game.exe, [N/A]\n"
    assert gpu.parse("6000, 16376\n", apps) == gpu.Usage(used=6000, total=16376, ollama=5000)


def test_every_card_counts() -> None:
    assert gpu.parse("1000, 8192\n2000, 8192\n", "").used == 3000


def test_no_nvidia_smi_is_no_answer() -> None:
    def missing(args: Sequence[str]) -> str:
        raise FileNotFoundError("nvidia-smi")

    def failing(args: Sequence[str]) -> str:
        raise subprocess.CalledProcessError(9, "nvidia-smi")

    assert gpu.usage(missing) is None
    assert gpu.usage(failing) is None


def test_usage_asks_nvidia_smi_for_both() -> None:
    asked: list[Sequence[str]] = []

    def answer(args: Sequence[str]) -> str:
        asked.append(args)
        return nvidia_smi("game-gpu.csv" if "--query-gpu" in args[0] else "game-apps.csv")

    assert gpu.usage(answer) == gpu.Usage(used=9518, total=16376, ollama=0)
    assert [a[0].split("=")[0] for a in asked] == ["--query-gpu", "--query-compute-apps"]
