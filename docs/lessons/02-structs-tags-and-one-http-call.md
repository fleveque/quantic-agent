# Lesson 02 — Structs, tags, and one HTTP call

**Milestone 2** — the agent can now reach the model on this machine. Getting there meant a struct per
wire message, a tag per field, and four decisions about JSON that the compiler is perfectly happy to
let you get wrong.

*Also readable as a [formatted page](https://claude.ai/artifact/4QGaudzoGjNAPto7ZcxgpD).*

---

## One call, two structs

`POST /api/generate` takes JSON and returns JSON, so the obvious move is one struct per direction. I
ended up with three, and the extra one earns its place: the caller says what varies per generation,
and the client fills in what belongs to the connection.

```go
// what the caller varies
type GenerateRequest struct {
	Prompt  string
	Think   *bool
	Options *Options
}

// what goes on the wire
type generateBody struct {
	Model   string   `json:"model"`
	Prompt  string   `json:"prompt"`
	Stream  bool     `json:"stream"`
	Think   *bool    `json:"think,omitempty"`
	Options *Options `json:"options,omitempty"`
}
```

The model name isn't a property of a call, it's a property of the client, and neither is the decision
never to stream. Leaving both out of the exported struct means a caller can't set something the
client will silently overwrite.

**Lesson 00 called this one.** I predicted the mistake I'd make: `encoding/json` marshals only
*exported* fields, and an unexported one vanishes with no error. Every field in every wire struct is
capitalised for that reason. The lowercase name is the *type* — `generateBody` — unexported so
nothing outside the package can depend on the wire shape.

## `omitempty` is a lie detector for your defaults

`Stream` is a `bool` that is always `false`, which makes `json:"stream,omitempty"` look like
tidiness. It would have been a bug:

| Tag | Sends when false | Ollama then |
|---|---|---|
| `json:"stream"` | `"stream": false` | Answers with one JSON object |
| `json:"stream,omitempty"` | Nothing at all | Streams: a JSON object per token |

`omitempty` drops a field whose value is the zero value, and for a `bool` that means every `false`.
The server's default for `stream` is `true`, so omitting the field asks for the opposite of what the
struct says. `json.Decoder.Decode` would then read the first object of the stream — one token,
`done: false` — and the client would cheerfully return it.

**The rule I took from it:** `omitempty` is only safe where the receiver's default and Go's zero value
are the same thing. Any field where they differ has to be sent explicitly, or made a pointer.

## Zero is not unset

`Temperature: 0` is a real instruction — sample deterministically — and so is `Seed: 0`. With
`omitempty` on a plain `float64`, neither can ever be sent. Without it, every request pins a
temperature I never chose. A pointer separates the two states, because `nil` is not `0`:

```go
type Options struct {
	NumPredict  int      `json:"num_predict,omitempty"`
	Temperature *float64 `json:"temperature,omitempty"`
	Seed        *int     `json:"seed,omitempty"`
}

// tiny helpers, because &0 isn't legal Go
func Float64(v float64) *float64 { return &v }
```

`NumPredict` keeps the plain `int` on purpose: a token limit of zero isn't a setting anyone means, so
zero and unset genuinely are the same request.

`Think` is the same shape for a different reason. `nil` leaves the model's own default alone;
`Bool(false)` actively suppresses the reasoning pass. Those are different requests, and a plain
`bool` can only express one of them.

## What decodes for free

Ollama reports timings as integer nanoseconds, and `time.Duration` *is* an `int64` count of
nanoseconds. `encoding/json` decodes a number into any named integer type, so the field just works —
and prints as `205.098ms` rather than as 205098000:

```go
EvalDuration time.Duration `json:"eval_duration"`   // 205098000 → 205.098ms
CreatedAt    time.Time     `json:"created_at"`      // RFC 3339 → a real timestamp
```

`time.Time` comes free too, because it implements `json.Unmarshaler` and Ollama's timestamps are
RFC 3339. Neither is magic in the framework sense: both are the standard library's interfaces doing
what the type system promised.

The other half of the deal: fields I don't declare are **ignored**. The real reply carries a
`context` array of several hundred token ids this client has no use for, and leaving it out of the
struct is all it takes. Coming from Ruby, where a stray key lands in the hash whether you want it or
not, having the struct define the contract is what I like most about this boundary.

## One HTTP call, carefully

```go
resp, err := c.http.Do(req)
if err != nil {
	return fmt.Errorf("llm: %s %s: %w", req.Method, req.URL.Path, err)
}
defer resp.Body.Close()

if resp.StatusCode != http.StatusOK {
	return fmt.Errorf("llm: %s %s: %s", req.Method, req.URL.Path, serverError(resp))
}
return json.NewDecoder(resp.Body).Decode(out)
```

- **Close every body**, including ones you never read. An unclosed body keeps its connection out of
  the pool until the garbage collector gets to it.
- **Check the status before decoding.** A 404 body is still valid JSON: it decodes into the response
  struct as all zero values and looks like a reply that said nothing.
- **Decode from the stream** rather than `ReadAll` then `Unmarshal` — `json.NewDecoder` takes an
  `io.Reader`, and the body is one.
- **Wrap with `%w`** so the cause survives. Milestone 3 is where that starts paying.

Error bodies needed one concession to reality. Ollama reports failures as `{"error": "..."}`, but a
mistyped *path* never reaches its handlers and comes back as plain text from the HTTP mux:

```
$ curl -s localhost:11434/api/generate -d '{"model":"no-such-model:latest"}'
{"error":"model 'no-such-model:latest' not found"}      http 404
$ curl -s localhost:11434/api/nope -d '{}'
404 page not found                                      http 404
```

So the client tries JSON and falls back to raw text, capped with an `io.LimitReader` — an error
message is not a reason to read an unbounded body into memory.

## The interface I didn't write

Milestone 2's Go topic was interfaces. The lesson turned out to be where *not* to put one.

The reflex from Ruby and Elixir is to inject a collaborator so tests can fake it: define a `Doer`
interface with a `Do` method, store it in the client, pass a fake in tests. It works, and here it
buys nothing, because the standard library ships a real HTTP server for exactly this:

```go
srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
	w.Write(fixture(t, "generate.json"))
}))
c := llm.New(srv.URL, "quantic-9b:latest")
```

That exercises the real transport, the real status handling and the real decoder. A `Doer` fake would
have skipped all three and tested my own indirection.

**Accept interfaces, return structs.** The Go convention is that an interface belongs to the
*consumer*, not the producer. So `llm` exports a concrete `*Client`, and whichever package later
wants to swap the model out declares its own one-method interface and accepts that. Writing a
`Generator` interface here, before a second implementation exists, would be guessing at a shape the
caller hasn't needed yet.

Interfaces did all the real work in this milestone, just not mine: `io.Reader` into the decoder,
`io.Writer` out of the command, `http.Handler` in the tests, `error` everywhere.

## Tests against real payloads

Both fixtures under `internal/llm/testdata/` are captured from this machine's Ollama — one ordinary
reply, one truncated thinking reply. A directory named `testdata` is invisible to the go tool, so
nothing there is ever compiled or imported.

Hand-written fixtures would have been wrong in the two ways that mattered most: I would not have
invented a `thinking` field, and I would have written the durations as seconds.

**`t.Fatalf` in the wrong goroutine.** Inside an `httptest` handler, use `t.Errorf`, never
`t.Fatalf`. `Fatalf` ends *the goroutine it runs in*, and that goroutine is the server's, not the
test's — the handler dies mid-reply and the test hangs waiting for a response that never comes.

## What the model taught me about the API

The first generation against `quantic-9b` asked for at most 16 tokens. It returned an empty
`response` and a full `thinking` field:

```json
{
  "response": "",
  "thinking": "Thinking Process:\n\n1.  **Analyze the Request:** The user wants",
  "done_reason": "length",
  "eval_count": 16, "total_duration": 56312501902
}
```

Qwen3.5-era models reason before answering, and the reasoning comes back separately. The token budget
is spent on thinking *first*, so a truncated reply can carry a paragraph of reasoning and no answer
at all. The same prompt with `think:false`:

```
$ go run ./cmd/agent -ask "Reply with exactly: ok"
ok
quantic-9b:latest · 2 tokens · 208ms
```

56 seconds to 1.8. Two consequences landed in the [design](../design.md#4-stack). The agent always
sends `think:false`, because reasoning text is not a source — it can't feed a draft, and provenance
couldn't validate it if it did. And `done_reason` earns a method of its own, because a truncated
draft is a broken one:

```go
func (r GenerateResponse) Truncated() bool { return r.DoneReason == "length" }
```

A model with no thinking mode accepts `think:false` and ignores it, so the field can always be sent.
I checked rather than assuming.

## What I'm taking into milestone 3

- `omitempty` only where the receiver's default matches Go's zero value. `stream: false` has to be on
  the wire.
- A pointer when zero and unset are different requests — temperature, seed, think. A plain value when
  they aren't.
- Check the status before decoding: an error body is valid JSON and decodes to a struct full of zero
  values.
- An interface belongs to the consumer. `httptest` beats a transport fake, and the client stays
  concrete.
- Capture fixtures from the real server. I'd have invented neither `thinking` nor nanoseconds.

---

**Previous:** [Lesson 01 — A binary, a package, and `go test`](01-a-binary-a-package-and-go-test.md) ·
**Next:** Lesson 03 — errors across the LLM boundary *(not written yet)*
