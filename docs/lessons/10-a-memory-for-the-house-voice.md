# Lesson 10 — A memory for the house voice

**Milestone 10** — retrieval, the design's style memory. A reviewer approves an answer; the agent
turns it into a vector; a later writer is shown the approved answers most similar to its question,
as examples of how the house writes. No vector database: floats in a SQLite BLOB, and a loop. The Go
version wrote a lesson about this before it got here, so its arithmetic is the starting point. Then
I measured, chose an embedding model by measuring, and watched what an example actually does to a
writer.

*Also readable as a [formatted page](https://claude.ai/artifact/X7S4oMKwVZt3gSCJGnox6V), with a [code walkthrough](https://claude.ai/artifact/6SFcTdLKojwjeAts7cf1np) of every change the
milestone made.*

---

## What there was to search

The design wants approved drafts as the corpus, and nothing had ever been approved: there was no
review step. So the milestone starts with one:

```
$ quantic-agent --approve 4 --note "clear, cites the field"
quantic-agent: run 4 approved: style memory now
```

Only an `answered` run can be approved, one whose every figure traced. An answer with invented
figures is not an example to follow, and the store refuses it. `--reject` takes an answer out again,
and `--recall QUESTION` shows which approved answers a writer would be shown.

## A vector, stored

An embedding model turns text into a fixed-length list of floats, trained so that texts meaning
similar things point in similar directions. Ollama's `/api/embed` returns them. Two things about
that call. Ollama returns unit vectors, length 1, already. And its default *truncates* an input
longer than the model's context, silently, so the vector stands for text it never saw. After
milestone 9's silent prompt truncation, the client sends `truncate: false`, and an overlong input is
refused instead.

Go's lesson stored float32 with `math.Float32bits` and `binary.LittleEndian`. Python's standard
library has a typed array:

```python
def encode(vector: Sequence[float]) -> bytes:
    packed = array("f", vector)
    if sys.byteorder != "little":
        packed.byteswap()
    return packed.tobytes()
```

`array("f")` holds C floats, 4 bytes each, half a Python float. `tobytes` writes them in the machine's
order, so on a big-endian machine they're swapped first: the file means the same thing everywhere.

## Brute force, measured

Go's lesson worked it out on paper: 20,000 vectors of 768 dimensions is 15 million multiply-adds,
milliseconds in Go. Python is not Go, so I measured, with numpy beside it for scale:

```
  768 dims    500 vectors  zip+sum     46.5ms  sumprod     23.7ms  numpy      0.8ms
  768 dims  20000 vectors  zip+sum   1831.0ms  sumprod    950.7ms  numpy     11.2ms
```

`math.sumprod` (Python 3.12) is a dot product computed in C, twice as fast as `sum` over a `zip`.
numpy is a hundred times faster again. But the cosine above computes both vectors' lengths every
time. Stored at unit length, the cosine *is* the dot product, one `sumprod`:

```
  768 dims    500 unit vectors  one sumprod each     9.2ms
  768 dims  20000 unit vectors  one sumprod each   318.9ms
```

Style memory grows by about one approved answer a week, and a generation takes 5 to 30 seconds. Ten
milliseconds doesn't need numpy, so it isn't a dependency. `heapq.nlargest(k, ...)` keeps only the
best k while scanning, instead of sorting everything.

## Choosing the embedding model

The design named `nomic-embed-text` "or a Qwen3 embedding model". I wrote a small evaluation,
`quantic-evalrecall`: six real answers from this project's runs, and twelve questions labelled with
the answers that would be fair examples for them, four of them in Spanish since posts will be written
in seven languages. Each model ran as published, plain, and with the prefixes its documentation asks
for:

```
MODEL                 USAGE       DIMS  EN   ES   TOTAL  MS/TEXT
nomic-embed-text      plain       768   5/8  3/4  8/12   2.8
nomic-embed-text      documented  768   5/8  3/4  8/12   3.0
qwen3-embedding:0.6b  plain       1024  6/8  3/4  9/12   10.0
qwen3-embedding:0.6b  documented  1024  7/8  3/4  10/12  9.9
```

`nomic-embed-text` kept sending "When is Johnson & Johnson's next ex-dividend date?" to the 10-day
list instead of the one-company answer. Twelve questions are too few to rank close models, and the
labels are my judgement, but Qwen's was ahead both ways, and its 2.4GB fits beside the 9B. So
`qwen3-embedding:0.6b`, with its instruction on questions:

```
Instruct: Given a question, retrieve answers written for similar questions
Query: How many years has Johnson & Johnson raised its dividend?
```

I first wrote that embeddings are deterministic and repeat exactly. Run three times, the *choices*
did; the scores moved by up to 0.0012. The same question scored 0.560 from `--recall` and 0.558 a
minute later in a run.

## What an example does

Two real answers approved, then a new question:

```
$ quantic-agent --recall "How many years has Johnson & Johnson raised its dividend?" | grep ^run
run 4 · 0.560
run 2 · 0.374
```

Run 4 was Coca-Cola's streak. The writer got it as an example, told its facts and figures were out of
date, and wrote:

```
According to the data provided, Johnson & Johnson has raised its dividend for 28 consecutive years.
This information is indicated by the "streak_years" field within the "dividend_profile" section ...
```

The approved answer had said: "According to the data provided, Coca-Cola has raised its dividend for
28 consecutive years. This information is indicated by the "streak_years" field ...". Sentence for
sentence, quirk for quirk: naming the JSON field isn't great writing, and the example taught it. Every
figure traced to Johnson & Johnson's own data. Style memory works, and what it does is imitate. The
review queue decides the voice, so approving is writing.

## The hard line, tested

"Never retrieve a number" is the design's rule for retrieval. An example enters the writer's prompt
and never the provenance manifest. The test approves an answer whose "4.2%" traced to its own run's
data, then has a later writer copy it:

```
'4.2%' (number 4.2)
```

Reported, as an invented figure would be. Breaking it (adding the examples' text to the manifest)
makes the run pass, and the test fail. Which examples a run's writer saw is recorded too, and
`--run N` shows them: everything that reaches the model is on record.

## A check that was only half a check

Rejecting an answer deletes its vector, and my first query for the memories also joined on the
review's verdict. Breaking either one alone failed nothing, because the other covered it. As with the
resume claim in lesson 08: two guards for one rule means neither can be shown to work. The delete
stayed; the join went; now the test fails when the delete is removed.

## What I'm taking into milestone 11

- The standard library goes far: `array`, `math.sumprod` and `heapq` are a vector search.
- Store vectors at unit length, and a cosine is one dot product.
- Measure retrieval like tool calls: a labelled set, models as published, documented usage too.
- "Deterministic" is a claim like any other. Check it.
- Examples are imitated closely. Approve what you want more of.
- Retrieved text is language. It never vouches for a figure, and a test says so.

---

**Previous:** [Lesson 09 — One GPU, many calls](09-one-gpu-many-calls.md) ·
**Next:** [Lesson 11 — Seven files, one set of figures](11-seven-files-one-set-of-figures.md)
