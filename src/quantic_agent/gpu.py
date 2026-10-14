"""Whether the GPU is free enough for a scheduled run to take it.

The GPU is the author's too (design §3.6): a run started while they play a
game or train a model makes both slow. Before a scheduled run starts a
model, it asks nvidia-smi how much video memory other programs hold. Too
much, and it steps aside: exit 3, which systemd retries later.

"Other programs" is everything on the card but Ollama's model runners.
Graphics-only processes (the compositor, a browser's GPU process) aren't in
nvidia-smi's list of compute processes, but their memory is in the card's
total, so others are the total less Ollama's share, not a sum of the list
(measured 2026-10-14, with a game running: tests/fixtures/nvidia-smi/).
"""

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

# How much video memory, in MiB, others may hold for a run to start. The
# desktop alone held about 1.2 to 2.2GB; the 27B wants about 14GB of 16.
DEFAULT_MAX_OTHERS = 4096

_GPUS = ["--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"]
_APPS = ["--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"]


@dataclass(frozen=True)
class Usage:
    """Video memory in MiB, over every GPU: in use, in all, and Ollama's."""

    used: int
    total: int
    ollama: int

    @property
    def others(self) -> int:
        """What programs other than Ollama hold."""
        return self.used - self.ollama


def parse(gpus: str, apps: str) -> Usage:
    """nvidia-smi's two answers as a Usage. A process name can hold a comma
    (a Windows path through Proton can), so a line is split at its first
    comma and its last. Memory it can't report ("[N/A]") counts as none."""
    used = total = 0
    for line in gpus.strip().splitlines():
        u, t = (part.strip() for part in line.split(","))
        used, total = used + int(u), total + int(t)
    ollama = 0
    for line in apps.strip().splitlines():
        _, rest = line.split(",", 1)
        name, memory = rest.rsplit(",", 1)
        if "ollama" in name.lower() and memory.strip().isdigit():
            ollama += int(memory.strip())
    return Usage(used=used, total=total, ollama=ollama)


type Runner = Callable[[Sequence[str]], str]


def _nvidia_smi(args: Sequence[str]) -> str:
    return subprocess.run(
        ["nvidia-smi", *args], capture_output=True, text=True, check=True, timeout=10
    ).stdout


def usage(run: Runner = _nvidia_smi) -> Usage | None:
    """The card's memory now, or None when there's no nvidia-smi to ask, or
    it fails: a machine without an NVIDIA card has nothing to share."""
    try:
        return parse(run(_GPUS), run(_APPS))
    except OSError, subprocess.SubprocessError, ValueError:
        return None
