"""Text as vectors, and the nearest ones to a question (design §3.4).

An embedding model turns text into a fixed-length list of floats, trained so
that texts meaning similar things point in similar directions. Similarity is
the cosine of the angle between two vectors: 1 for the same direction, 0 for
unrelated. Search is brute force: every stored vector against the query. At
this corpus's size, hundreds to thousands of texts, that's exact and fast
enough, and no vector database is needed.

Vectors are stored at unit length, so a cosine is one dot product. Measured
in plain Python (lesson 10): 500 stored vectors take about 10ms, 20,000 about
0.4s; numpy would be about a hundred times faster, and isn't needed until the
corpus is thousands of texts.

The hard line: retrieved text is language, never a source of figures. It
reaches the writer's prompt and never the provenance manifest.
"""

import heapq
import math
import sys
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Usage:
    """How texts are given to a model: as they are, or with the prefixes its
    documentation asks for on questions and on the texts searched."""

    name: str
    query: str = ""
    document: str = ""


PLAIN = Usage("plain")

# The prefixes each model family documents, by the start of its name.
DOCUMENTED: dict[str, Usage] = {
    # nomic-embed-text's model card: a task prefix on every text.
    "nomic-embed-text": Usage("documented", query="search_query: ", document="search_document: "),
    # Qwen3-Embedding's model card: an instruction on queries, none on documents.
    "qwen3-embedding": Usage(
        "documented",
        query="Instruct: Given a question, retrieve answers written for similar questions\nQuery: ",
    ),
}


def documented(model: str) -> Usage | None:
    """The documented usage for model, if its family has one. Style memory
    uses it whenever there is one: measured, it found the right example more
    often for both models tried (lesson 10)."""
    return next((u for name, u in DOCUMENTED.items() if model.startswith(name)), None)


def encode(vector: Sequence[float]) -> bytes:
    """A vector as stored: 4-byte floats, little-endian whatever the
    machine. array("f") holds C floats, float32, half a Python float's size."""
    packed = array("f", vector)
    if sys.byteorder != "little":
        packed.byteswap()
    return packed.tobytes()


def decode(blob: bytes) -> array[float]:
    """The vector encode stored."""
    packed = array("f")
    packed.frombytes(blob)
    if sys.byteorder != "little":
        packed.byteswap()
    return packed


def unit(vector: Sequence[float]) -> list[float]:
    """vector scaled to length 1, pointing the same way."""
    length = math.sqrt(math.sumprod(vector, vector))
    if not length:
        raise ValueError("a zero vector has no direction")
    return [x / length for x in vector]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """The cosine of the angle between a and b. math.sumprod (Python 3.12)
    is the dot product, computed in C, with extended precision."""
    if len(a) != len(b):
        raise ValueError(f"vectors of {len(a)} and {len(b)} dimensions")
    norms = math.sqrt(math.sumprod(a, a) * math.sumprod(b, b))
    return math.sumprod(a, b) / norms if norms else 0.0


@dataclass(frozen=True)
class Memory:
    """A stored text and its unit vector: for now, an approved answer and its
    run."""

    run_id: int
    text: str
    vector: Sequence[float]


@dataclass(frozen=True)
class Match:
    memory: Memory
    score: float  # cosine similarity to the query


def nearest(query: Sequence[float], memories: Iterable[Memory], k: int) -> list[Match]:
    """The k memories most similar to query, most similar first. Both are unit
    vectors, so the cosine is their dot product. heapq.nlargest keeps only k
    at a time instead of sorting everything."""
    q = unit(query)
    scored = (Match(m, math.sumprod(q, m.vector)) for m in memories)
    return heapq.nlargest(k, scored, key=lambda match: match.score)
