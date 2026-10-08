import json

import pytest
from conftest import FakeOllama, Reply

from quantic_agent import evalrecall


def embeds(vectors: list[list[float]]) -> Reply:
    return Reply(json.dumps({"model": "m", "embeddings": vectors}).encode())


def one_hot(i: int, n: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(n)]


def test_the_cases_are_well_formed() -> None:
    # The cases are data a person edits, so they're checked like code.
    cases = evalrecall.load_cases()
    ids = [a.id for a in cases.answers]
    assert len(ids) == len(set(ids)) == 6
    for q in cases.queries:
        assert q.want, q.query
        assert set(q.want) <= set(ids), q.query
        assert q.language in ("en", "es"), q.query
    assert {q.language for q in cases.queries} == {"en", "es"}


def test_a_question_scores_when_its_nearest_answer_is_a_label(
    ollama: FakeOllama, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = evalrecall.load_cases()
    n = len(cases.answers)
    ids = [a.id for a in cases.answers]
    # Each answer points its own way; every question points at the first
    # answer, "this-week", which is a fair example for the first three
    # questions only.
    ollama.replies["/api/embed"] = [
        embeds([one_hot(i, n) for i in range(n)]),
        embeds([one_hot(0, n) for _ in cases.queries]),
    ]

    args = ["--ollama", ollama.url, "--models", "some-embedder", "--json"]
    assert evalrecall.main(args) == 0

    [score] = json.loads(capsys.readouterr().out)
    want = sum(ids[0] in q.want for q in cases.queries)
    assert (score["usage"], score["dims"], score["hits"], score["runs"]) == ("plain", n, want, 12)
    # The texts went in as they are, all in two requests.
    assert ollama.bodies[0]["input"] == [a.text for a in cases.answers]
    assert ollama.bodies[1]["input"] == [q.query for q in cases.queries]


def test_a_model_is_also_measured_as_documented(ollama: FakeOllama) -> None:
    cases = evalrecall.load_cases()
    n = len(cases.answers)
    ollama.replies["/api/embed"] = [
        embeds([one_hot(i, n) for i in range(n)]),
        embeds([one_hot(0, n) for _ in cases.queries]),
    ] * 2

    assert evalrecall.main(["--ollama", ollama.url, "--models", "nomic-embed-text"]) == 0

    # Plain first, then nomic's own task prefixes.
    assert len(ollama.bodies) == 4
    assert ollama.bodies[2]["input"][0].startswith("search_document: ")
    assert ollama.bodies[3]["input"][0] == "search_query: " + cases.queries[0].query
