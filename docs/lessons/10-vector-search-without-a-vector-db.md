# Lesson 10 — Vector search without a vector database

**Milestone 10** — retrieval. Written ahead of its milestone, because the question came up: what is a
vector database, and why isn't this project using one?

*Also readable as a [formatted page](https://claude.ai/code/artifact/4cf71989-6588-4864-b3bc-314781a156b1).*

---

## What an embedding actually is

An embedding model takes text and returns a fixed-length list of floats. `nomic-embed-text` returns
768 of them:

```
"MSFT raised its dividend 10.7%"  →  [0.021, -0.184, 0.093, ... ]   // 768 floats
"Microsoft increased its payout"  →  [0.019, -0.177, 0.101, ... ]   // very close
"REIT FFO payout ratios in 2026"  →  [-0.142, 0.208, -0.031, ... ]  // far away
```

The model is trained so that **text meaning similar things lands in similar directions**. That's the
whole trick. Once text is a vector, "find me related text" becomes "find me nearby vectors", which is
arithmetic rather than language.

Note *directions*, not positions. What matters is the angle between two vectors, not how long they
are — a short document and a long one about the same topic should match.

## Cosine similarity

The angle between two vectors, as a number from -1 to 1:

$$\text{cos}(a,b) = \frac{a \cdot b}{\|a\| \|b\|}$$

The dot product on top, divided by both magnitudes to cancel out length. 1 means identical direction,
0 means unrelated, -1 means opposite. In Go:

```go
func cosine(a, b []float32) float32 {
	b = b[:len(a)] // hint the compiler: one bounds check, not len(a) of them
	var dot, na, nb float32
	for i, av := range a {
		bv := b[i]
		dot += av * bv
		na += av * av
		nb += bv * bv
	}
	return dot / float32(math.Sqrt(float64(na))*math.Sqrt(float64(nb)))
}
```

That's the entire similarity engine. Everything a vector database does is built on this.

**A Go detail worth knowing:** `b = b[:len(a)]` is not cosmetic. Without it the compiler must
bounds-check `b[i]` on every iteration because it can't prove `b` is long enough. Re-slicing proves it
once. This is *bounds-check elimination*, and it's a recurring Go performance idiom — `go build
-gcflags="-d=ssa/check_bce/debug=1"` will show you which checks survive.

## So what is a vector database?

A database specialised for one query: *given this vector, return the k nearest.* Pinecone, Weaviate,
Qdrant, Chroma, Milvus, and `pgvector` as a Postgres extension.

They exist because the obvious approach — compare the query against every stored vector — is O(n), and
at tens of millions of vectors that's too slow. So they build an index, usually **HNSW**
(*Hierarchical Navigable Small World*): a layered graph where each vector links to near neighbours,
and search walks the graph greedily from a coarse layer down to a fine one. Instead of touching all
n vectors it touches roughly log(n) of them.

**The catch is in the name.** These are *approximate* nearest neighbour indexes. The graph walk can
get stuck in a local minimum and return the 2nd-best match instead of the best. That trade is
absolutely worth it at 50 million vectors. It's a pure loss at 5,000.

## The arithmetic for this project

Style memory is approved posts: ~52 a year, chunked, call it 500 chunks. Add filings text later and
be generous — say **20,000 chunks** at full stretch.

**Memory:** 20,000 × 768 dims × 4 bytes = **61 MB**. Fits in RAM with room to spare, on a machine with
64 GB.

**Time per query:** 20,000 × 768 = 15.4M multiply-adds. Go does that single-threaded in **a few
milliseconds** — and this is trivially parallel across goroutines if it ever matters.

Now the number that settles it: **a single LLM generation on this hardware takes 5–30 seconds.**
A 5ms search is under 0.1% of the run. Optimising it would be optimising the wrong thing by three
orders of magnitude.

| | Brute force | HNSW index |
|---|---|---|
| Results | **Exact** | Approximate |
| Dependencies | None | A service or an extension |
| Code | ~40 lines | A client library |
| Wins when | n ≲ 10⁵ | n ≳ 10⁶ |
| Cost here | ~5ms, 0.1% of a run | Same, plus operational overhead |

Brute force isn't the beginner option here. It's the correct one — **and it returns better results**,
because exact beats approximate.

## Storage

Embeddings go in the same SQLite the rest of the agent uses, as `BLOB`:

```go
// float32 slice → bytes, little-endian, 4 bytes each
func encode(v []float32) []byte {
	b := make([]byte, len(v)*4)
	for i, f := range v {
		binary.LittleEndian.PutUint32(b[i*4:], math.Float32bits(f))
	}
	return b
}
```

`math.Float32bits` reinterprets the float's bits as a `uint32` — no conversion, no precision loss.
Decoding is the mirror image with `math.Float32frombits`.

On startup, load them all into memory once and search the in-memory slice. SQLite is durable storage
here, not the query engine.

## When to graduate, and to what

The trigger is roughly **10⁵ vectors**, or brute-force search becoming a measurable fraction of a run.
Neither is close.

When it happens, the answer probably isn't a vector database as a new service. **Quantic already runs
Postgres**, so `pgvector` is an extension away — one less thing to operate, and it'd let retrieval move
server-side if that ever made sense.

The other candidate is `sqlite-vec`, which adds ANN indexing to SQLite. It's good, but it's a C
extension, and that costs the pure-Go/no-cgo property that keeps this project a single static binary.
Worth it only for a real problem, not a hypothetical one.

## Why this is worth writing by hand

Calling a vector database API teaches you an API. Writing cosine similarity, encoding float32 to
bytes, and benchmarking a linear scan teaches you what an embedding *is* — that it's just a direction
in a high-dimensional space, that "semantic search" is a dot product, and that the magic is entirely
in the embedding model rather than in the storage.

Given the point of this project is learning, paying 40 lines for that is a bargain.

## The rule that survives all of this

**Never retrieve a number.** Retrieved chunks enter the prompt as *language* and never enter the
provenance manifest, so they can't authorise a figure. A vector store has no freshness guarantee — the
embedded text was true when it was written, and a dividend gets cut. Every number still comes from a
live tool call. See [design §3.4](../design.md#34-retrieval-rag).

---

**Previous:** [Lesson 00 — Project layout, modules, and the `internal` rule](00-project-layout-and-modules.md)
