# Lesson 01 — A binary, a package, and `go test`

**Milestone 1** — the first Go code. A binary that does nothing yet, one real package, and tests for
both. Lesson 00 was the layout on paper; this is what happened when it met the compiler — and a
decimal that doesn't exist.

*Also readable as a [formatted page](https://claude.ai/artifact/PuuxbeGuttxWhboXDxbZMi).*

---

## What landed

```
cmd/agent/
  main.go          package main        a one-line main and a testable run()
  main_test.go     package main        white-box: tests the unexported run()
internal/tools/
  calc.go          package tools       PctChange, Diff, Sum
  calc_test.go     package tools_test  black-box: sees only what's exported
```

The first real package is the deterministic calculators from [design §3.3](../design.md#33-provenance).
When a draft needs a derived figure, the model calls `pct_change` instead of doing arithmetic, so the
result lands in the provenance manifest like any other tool response. Pure functions with no
dependencies: the right shape for a first test.

That also settles lesson 00's open question. The calculators are plain functions in a flat
`internal/tools`. Three functions don't earn a subpackage, and a directory created now is a directory
I'd have to justify later.

## Tests live beside the code

No `test/` directory, no `test_helper.exs`, no `spec_helper.rb`. A test is any file ending in
`_test.go`, sitting next to the code it tests. `go build` ignores those files; `go test` compiles them
in.

A test is a function named `TestXxx` that takes a `*testing.T`. There is no `assert`:

```go
if code != tt.wantCode {
	t.Errorf("exit code = %d, want %d", code, tt.wantCode)
}
```

The standard library has no assertion helpers at all. You write the `if`, and you write the failure
message. After ExUnit's `assert` with its automatic diffs, that felt like a step backwards for about
an hour. Then the upside showed: every failure reads *got X, want Y* in words I chose, and there's no
assertion DSL to learn. The convention is `got` first, then `want`.

`t.Errorf` marks the test failed and **keeps going**, so one run reports every broken case. `t.Fatalf`
marks it failed and stops that test — for when carrying on makes no sense, like inspecting a result
after the call already returned an error.

## Two packages in one directory

Lesson 00 said one directory holds one package. Tests are the exception, and a useful one. A
`_test.go` file may declare the package it sits in, or that name with `_test` appended:

| File | Declares | Can see | Style |
|---|---|---|---|
| `calc_test.go` | `package tools_test` | Only exported names, through an import | Black-box |
| `main_test.go` | `package main` | Everything, including the unexported `run` | White-box |

`tools_test` is compiled as a *separate package* that imports `tools` like any outsider, so it calls
`tools.PctChange` exactly the way the tool registry will from another package. Rename an exported
function and the test breaks the way a caller would.

`main_test.go` has to be white-box. `run` is unexported on purpose, and a `package main` can't be
imported by anything, so an external test package couldn't reach it anyway.

This is also where Go's two visibility layers stop being abstract. `PctChange` is capitalised, so
every package in this module can call it. It lives under `internal/`, so no other module can.
**Capitalisation controls access between packages; `internal/` controls access between modules.**

## Table-driven tests

The idiomatic Go test is a slice of cases and a loop:

```go
tests := []struct {
	name              string
	previous, current float64
	want              float64
}{
	{name: "raise", previous: 1.50, current: 1.55, want: 10.0 / 3},
	{name: "cut in half", previous: 0.80, current: 0.40, want: -50},
	{name: "suspended", previous: 0.25, current: 0, want: -100},
}

for _, tt := range tests {
	t.Run(tt.name, func(t *testing.T) {
		got, err := tools.PctChange(tt.previous, tt.current)
		if err != nil {
			t.Fatalf("PctChange(%v, %v) returned error: %v", tt.previous, tt.current, err)
		}
		if !approxEqual(got, tt.want) {
			t.Errorf("PctChange(%v, %v) = %v, want %v", tt.previous, tt.current, got, tt.want)
		}
	})
}
```

The struct type has no name. It's declared and used in one expression because nothing else needs it.

`t.Run` makes each case a named subtest. They're reported individually, with spaces turned into
underscores, and one can be run on its own:

```
$ go test -run '^TestPctChange$/^cut_in_half$' -v ./internal/tools
=== RUN   TestPctChange
=== RUN   TestPctChange/cut_in_half
--- PASS: TestPctChange (0.00s)
    --- PASS: TestPctChange/cut_in_half (0.00s)
PASS
```

The anchors matter. `-run` takes an unanchored regular expression per level, so without `^…$` the
pattern `TestPctChange` also matches `TestPctChangeRefusesNonPositiveBase` — which duly ran, found no
subtest called `cut_in_half`, and reported a pass for doing nothing.

**Coming from Elixir:** the nearest thing is a comprehension generating `test` blocks at compile time.
In Go it isn't metaprogramming at all — a slice of data and a closure, at runtime. Adding a case is
adding a line.

**A line I didn't have to write.** Older Go code starts that loop body with `tt := tt`. Before Go 1.22
the loop reused one `tt` variable across iterations, and a closure that outlived its iteration saw
whichever case came last. Since 1.22 every iteration gets its own variable, and because this module
declares `go 1.27` in `go.mod`, the new behaviour applies.

## The float that isn't 0.05

Compare floats with `==` and correct arithmetic fails:

```go
{name: "raise", previous: 1.50, current: 1.55, want: 0.05},
// ...
if got := tools.Diff(tt.previous, tt.current); got != tt.want {
```

```
--- FAIL: TestDiffExactTable/raise (0.00s)
    calc_test.go:17: Diff(1.5, 1.55) = 0.050000000000000044, want 0.05
```

The subtraction is right; the decimal isn't representable. 1.55 has no exact `float64` form — the
nearest one is a hair above, `1.55000000000000004440…` — and subtracting 1.5 exposes the hair. The
result sits six representable values above the `float64` nearest to 0.05. So the tests compare within
a tolerance:

```go
const epsilon = 1e-9

func approxEqual(a, b float64) bool {
	return math.Abs(a-b) <= epsilon
}
```

A billionth is loose by floating-point standards and far below anything the agent reports.

### The part that's specific to Go

A scratch program made this more confusing, not less:

```go
fmt.Println(1.55 - 1.50) // 0.05
```

Exactly `0.05`. The same subtraction on variables:

```go
a, b := 1.55, 1.50
fmt.Println(a - b) // 0.050000000000000044
```

The difference is **untyped constants**. `1.55 - 1.50` written with literals is a constant expression,
and Go evaluates constant expressions at compile time with arbitrary precision — it genuinely is 0.05,
converted to the nearest `float64` only when used. A value becomes a `float64` when it lands in a
variable, a struct field or a function parameter, and only from there does float arithmetic apply.
Even `Diff(1.50, 1.55)` with literal arguments fails an `==` check, because the conversion happens at
the call.

Ruby and Elixir both print `0.050000000000000044` for `1.55 - 1.50` straight away. Go is the one that
hides it — so a quick `fmt.Println` of literal arithmetic can't tell you what your code will compute.

### So should the calculators round?

No, and that's a design decision rather than a test convenience. `PctChange(1.50, 1.55)` returns
`3.333333333333336`, and that exact value is what the manifest records and what the post's data block
carries. Rounding is presentation, so the Phoenix template does it. Round in Go as well and there are
two rounding rules to keep in step, one here and one in Elixir, and the figure the validator compares
stops being the figure the tool returned. Recorded in [design §3.3](../design.md#33-provenance).

## A tool that refuses

```go
func PctChange(previous, current float64) (float64, error) {
	if previous <= 0 {
		return 0, errors.New("tools: pct_change needs a positive previous value")
	}
	return (current - previous) / previous * 100, nil
}
```

The guard isn't about crashes. **Float division by zero doesn't panic in Go.** Integer division by
zero does, but at runtime `1.25 / 0.0` is `+Inf` and `0.0 / 0.0` is `NaN`, and nothing stops. The
first thing to object would be `encoding/json`, much later, when the manifest is serialised:

```
json: unsupported value: +Inf
```

An error about JSON, far from its cause. Checking the input moves the failure to where it happens.

A negative base is refused for a different reason: it produces a real number with a misleading sign.
−2 → −1 is a rise, and the formula calls it −50%. A calculator that declines leaves the draft without
that figure, which is safe. One that returns a misleading figure is how a wrong number gets past a
provenance check — after all, it *did* come from a tool.

The error is a plain `errors.New`, and the test only asserts that one came back. Sentinel errors,
wrapping and `errors.Is` are milestone 3; this is the before picture.

## A main you can test

```go
func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(args []string, stdout, stderr io.Writer) int {
```

`main` is awkward to test. It reads the real process arguments, writes to the real terminal, and ends
with `os.Exit` — which exits immediately, skipping every deferred call. So `main` is one line, and
`run` takes its whole world as arguments and *returns* the exit code instead of exiting.

Flags go through `flag.NewFlagSet` with `ContinueOnError`, not the package-level `flag.Parse()`. The
global flag set uses `ExitOnError`: a bad flag ends the process from inside the flag package, test
runner included. The local one hands the error back and lets `run` choose the code — `2` for a usage
mistake, `0` for `-h`, the same codes `ExitOnError` would have used.

```
$ agent
quantic-agent: no tasks defined yet
$ agent -version
quantic-agent dev
$ agent -publish
flag provided but not defined: -publish
Usage of agent:
  -version
    	print the version and exit
$ echo $?
2
```

The test hands `run` two buffers:

```go
var stdout, stderr bytes.Buffer
code := run(tt.args, &stdout, &stderr)
```

`run` asks for an `io.Writer` — anything with a `Write([]byte) (int, error)` method. `*bytes.Buffer`
has one. Nowhere does `bytes.Buffer` declare that it implements `io.Writer`, and nowhere does my code
say so either; it satisfies the interface by having the method. Structural typing, one of the README's
reasons for picking Go, turned up first in a test. Milestone 2 leans on it hard to fake the Ollama
client.

`version` is a package-level `var` set to `"dev"`. Milestone 13 overwrites it at build time with
`-ldflags`, and nothing else has to change.

## CI stops excusing itself

Milestone 0's CI skipped the Go steps when there were no `.go` files, because a green tick that
checked nothing is worse than no tick. That guard is gone. Green now means `gofmt`, `go vet`,
`go build` and `go test -race` all ran against real code.

The same milestone bumps `go.mod` from `go 1.24` to `go 1.27`. Go supports each major release only
until there are two newer ones, so by the time the first code landed, 1.24 had stopped receiving
security fixes. CI reads its version from `go.mod`, so the bump is one line —
`go mod edit -go=1.27` — and nothing else in the workflow changes.

## What I'm taking into milestone 2

- Tests sit beside the code. `package x_test` when the API is exported and should be used like a
  caller would; `package x` when the thing under test is deliberately unexported.
- No `==` on computed floats in tests. And no trusting `fmt.Println(1.55 - 1.50)` in a scratch file:
  a constant isn't a `float64` until it's used.
- Float division by zero is silent. Guard inputs whose answer would be `Inf` or `NaN` before the value
  travels.
- `main` is one line; `run` takes its world as arguments.
- Interfaces are satisfied, not declared. Accepting an `io.Writer` cost nothing and made `run`
  testable.

---

**Previous:** [Lesson 00 — Project layout, modules, and the `internal` rule](00-project-layout-and-modules.md) ·
**Next:** [Lesson 02 — Structs, tags, and one HTTP call](02-structs-tags-and-one-http-call.md)
