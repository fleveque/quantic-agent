# Lesson 00 — Project layout, modules, and the `internal` rule

**Milestone 0** — repo, design, README. No Go code yet, but the layout decision comes first, and it
turns out to be enforced by the compiler rather than by convention. That's the surprise.

Coming from Elixir and Ruby, where project structure is convention plus a linter's opinion.

---

## The module is the unit, not the directory

In Ruby, `require` walks a load path. In Elixir, Mix knows your app and `deps/` holds the rest.
In Go, one file at the root declares everything:

```go
// go.mod
module github.com/fleveque/quantic-agent

go 1.24
```

That `module` line is the **import path prefix for every package in the repo**. A package in
`internal/llm/` is imported as `github.com/fleveque/quantic-agent/internal/llm` — from anywhere,
including from the file next door. There are no relative imports in Go. None. `import "./llm"` is not
a thing.

This felt heavy at first — the full path, every time. Then the payoff: an import line tells you
exactly which module a package comes from, with no load-path resolution in your head. `alias` in
Elixir does the ergonomic part when the path gets long:

```go
import "github.com/fleveque/quantic-agent/internal/provenance"
// referred to as provenance.Validate(...)
```

The last path segment is the package name by default, so you rarely alias. When you do:

```go
import prov "github.com/fleveque/quantic-agent/internal/provenance"
```

**Coming from Elixir:** `go.mod` ≈ `mix.exs`, but with a crucial difference — the module path is
usually the repo URL, because that *is* how Go fetches dependencies. There is no central package
registry like Hex or RubyGems. `go get github.com/google/go-github/v66` fetches from GitHub directly.
The proxy at `proxy.golang.org` caches it, but the identity of a package is its URL.

## Package ≠ directory name, but keep them the same

A directory contains one package. The package name is declared per-file:

```go
package llm
```

It *can* differ from the directory name. It shouldn't. The one common exception is `main`.

Coming from Ruby, the mental adjustment is that **Go packages are flat namespaces, not nested ones**.
`internal/llm` and `internal/tools` are siblings with no relationship — `llm` is not "inside" anything
from the compiler's perspective. The directory nesting is organisational for humans; it creates no
scoping. There's no `Quantic::Agent::LLM` chain, just `llm`.

## Exported means capitalised. That's the whole access control.

```go
func Validate(draft string) error { ... }   // exported — visible outside the package
func normalise(tok string) string { ... }   // unexported — package-private
type Manifest struct {
    Calls   []Call  // exported field
    started time.Time  // unexported field
}
```

No `public`/`private` keywords, no `defp`. The first letter of the identifier decides.

This is Go's most-mocked design choice and I've come around to it fast: **you can see a symbol's
visibility at the call site**, not just at the definition. `provenance.Validate` is obviously part of
the API. `provenance.normalise` wouldn't compile from outside. In Ruby I have to go find the
`private` keyword's position in the file to know.

The gotcha for me: this applies to **struct fields too**, and `encoding/json` can only marshal
exported fields. An unexported field silently vanishes from JSON output. Given this project is mostly
JSON at the LLM and MCP boundaries, that's a mistake I'm going to make at least once.

## `cmd/` and `internal/` — one is convention, one is law

The layout in the README:

```
cmd/agent/main.go      # entrypoint
internal/llm/          # local model client
internal/tools/        # tool registry
internal/provenance/   # the validator
internal/store/        # SQLite
```

**`cmd/` is pure convention.** Go doesn't know the name. It's the community's answer to "where do
binaries live", and it exists because a module can produce several. Each subdirectory of `cmd/` is a
`package main` with a `func main()`, and `go build ./cmd/agent` produces a binary named `agent`.
If this project later grows a `cmd/review` for the queue viewer, it slots in beside it with no
restructuring. That's the whole reason for the extra directory level.

**`internal/` is enforced by the compiler.** This is the part I didn't expect. A package under
`internal/` can only be imported by code rooted in the parent of that `internal/` directory. So
`github.com/fleveque/quantic-agent/internal/llm` is importable by anything inside `quantic-agent`,
and importing it from any other module is a **compile error**, not a lint warning:

```
use of internal package github.com/fleveque/quantic-agent/internal/llm not allowed
```

For a public repo this matters more than it looks. The repo is public, so anyone can `go get` it —
and without `internal/`, every package I write becomes a public API I've implicitly promised not to
break. Putting everything under `internal/` says: *this is a binary, not a library; the code is here
to read, not to import.* If I later want to publish a genuinely reusable piece, I move it up out of
`internal/` as a deliberate act.

There's no equivalent in Elixir or Ruby. `@moduledoc false` is a hint. `private_constant` is
per-constant and rarely used. Go makes it structural and mechanical.

## `go.sum` is a lockfile, but not the lockfile you expect

`go.mod` lists direct dependencies with minimum versions. `go.sum` records cryptographic hashes of
every module in the graph.

The difference from `mix.lock` or `Gemfile.lock`: Go doesn't resolve to "newest compatible version".
It uses **Minimal Version Selection** — given the constraints, it picks the *lowest* version that
satisfies everything. Builds are reproducible without a lockfile pinning exact versions, because the
algorithm is deterministic. `go.sum` is about *integrity* (this is the code I saw before), not
*resolution* (this is which version to use).

Practical consequence: dependencies don't drift under me. Nothing upgrades unless I run `go get -u`.
After Bundler and Mix, that's an adjustment — a good one for a daemon that's supposed to run
unattended.

## What I'm taking into milestone 1

- Module path is `github.com/fleveque/quantic-agent`, matching the repo. Not optional in practice.
- Everything goes under `internal/` unless there's a deliberate reason to expose it.
- `cmd/agent` for the daemon; leave room for a second binary.
- Watch for unexported struct fields silently disappearing in JSON. This project is *all* JSON
  boundaries.
- Stop reaching for nested namespaces. Package names are short, flat, and lowercase: `llm`, `store`,
  `tools` — not `LLMClient` or `agent_store`.

## Open question I haven't resolved

Where do the deterministic calculator tools from [the design](../design.md#32-provenance) live —
`internal/tools/calc` as a subpackage, or plain functions in `internal/tools`? Go's style guidance
pushes against small packages ("a little copying is better than a little dependency", and packages
are cheap for humans but not free for the compiler's dependency graph). Leaning towards keeping
`internal/tools` flat until it hurts.

---

**Next:** [Lesson 01 — structs, JSON tags, and the LLM boundary](01-structs-and-json.md) *(not written yet)*
