# Lesson 00 — Layout, packages, and privacy by convention

**Milestone 0** — the design carried over from the Go version, and an empty Python project that
passes every check CI runs. In Go, milestone 0's surprise was that the layout is enforced by the
compiler: `internal/` is law. In Python the surprise runs the other way. Almost nothing about the
layout is enforced by the language, and the checks that make it hold are tools I chose.

Coming from Elixir and Ruby daily, and from Go, which I learned building
[the first version of this agent](https://github.com/fleveque/quantic-agent-go).

---

## `pyproject.toml` is `go.mod`, but the project has two names

```toml
[project]
name = "quantic-agent"
requires-python = ">=3.14"
dependencies = []
```

`pyproject.toml` does the job of `go.mod` and `mix.exs`: the project's name, the language version,
its dependencies, and how to build it. `uv` reads it, creates `.venv/`, installs Python 3.14 if the
machine doesn't have it (`.python-version` says which), and installs the project into that
environment.

The surprise is the name. In Go, the module path *is* the import path: `go.mod` says
`github.com/fleveque/quantic-agent-go`, and every import starts with exactly that. In Python there
are two names that only happen to match:

- **`quantic-agent`** is the *distribution*: what `uv` installs and what PyPI would list. Hyphens
  are fine.
- **`quantic_agent`** is the *import package*: the directory `src/quantic_agent/`, which is what
  `import quantic_agent` finds. Hyphens aren't allowed in an identifier, so it's an underscore.

Nothing requires them to match. The classic example is `pip install pyyaml` followed by `import yaml`.
Elixir has a milder version (the `:quantic` app, the `Quantic` module), Ruby has gems whose require
name differs from the gem name, and Go has none of it.

## There's no module path: imports search `sys.path`, like Ruby's load path

A Go import names a module path and the compiler knows exactly where it is. A Python import names
only a top-level package, and the interpreter looks for it in each directory of `sys.path`, in order,
and takes the first match. That's Ruby's `$LOAD_PATH`, not Go and not Mix.

```
$ uv run python -c 'import sys; print(sys.path[:3])'
['', '/usr/lib/python314.zip', '/usr/lib/python3.14']
```

The `''` at the front is the current directory. So how does `import quantic_agent` find
`src/quantic_agent/`? `uv sync` installs the project in *editable* mode, and the editable install is
a one-line file in the environment's `site-packages`:

```
$ cat .venv/lib/python3.14/site-packages/quantic_agent.pth
/home/fleveque/Projects/quantic/quantic-agent/src
```

Python reads every `.pth` file at start-up and appends each line to `sys.path`. Edit a file under
`src/` and the next run sees it, with no reinstall. That's the whole trick.

## Why the code lives in `src/`

First match wins, and the current directory comes first when you run `python -m something`. So a
`quantic_agent/` directory in the repository root would shadow the installed package whenever
anything runs from the root, and tests would pass against code no installed program runs. Putting
the package under `src/` means the only way to import it is to install it.

Milestone 0's only test checks exactly that. I put a stray copy in the root to watch it fail:

```
$ mkdir quantic_agent && echo '"""A stray copy."""' > quantic_agent/__init__.py
$ uv run pytest -q
.                                                                        [100%]
1 passed in 0.00s
$ uv run python -m pytest -q
...
E       AssertionError: assert PosixPath('/home/fleveque/Projects/quantic/quantic-agent/quantic_agent') == ((PosixPath('/home/fleveque/Projects/quantic/quantic-agent') / 'src') / 'quantic_agent')
FAILED tests/test_layout.py::test_the_package_under_test_is_the_one_in_src - ...
1 failed in 0.01s
```

Same tests, same code. `pytest` is a script and doesn't put the current directory on `sys.path`;
`python -m pytest` does. With a flat layout, the second command would have been testing the stray
copy and passing. Go can't have this problem: there's one place a package can be.

## Privacy is a naming convention, and only a checker enforces it

Go: a capital letter exports, a lowercase one doesn't, and `internal/` can't be imported from
another module. The compiler refuses. Python: a leading underscore *means* private, and nothing at
run time cares. I wrote a `_calc.py` module with a `_round_half_even` helper, imported it from a test,
and it ran:

```
$ uv run python -c 'from quantic_agent._calc import _round_half_even; print(_round_half_even(2.675))'
2.67
$ uv run pytest -q
2 passed in 0.00s
```

What refuses is pyright, in strict mode:

```
$ uv run pyright
  src/quantic_agent/_calc.py:1:5 - error: Function "_round_half_even" is not accessed (reportUnusedFunction)
  tests/test_private.py:1:33 - error: "_round_half_even" is private and used outside of the module in which it is declared (reportPrivateUsage)
2 errors, 0 warnings, 0 informations
```

Two things I didn't expect. Pyright checks private *names*, not private *modules*: importing
`pct_change` from `quantic_agent._calc` raised nothing. (Ruff has a rule for that, `PLC2701`, still in
preview.) And it called the helper dead code, because nothing inside its own module used it. Go's
compiler only refuses unused imports and variables; an unused unexported function compiles fine.

The consequence for tests is the opposite of Go's. A Go test in `package llm` sees every unexported
name. Here a test is just another module, so under strict pyright it can only use the public names.
Tests go through the front door, or say why they don't with a `# pyright: ignore[reportPrivateUsage]`.

**There is no `internal/`.** Anyone who installs a package can import all of it. Python's answer is
not to offer it: this project isn't published to PyPI, and its docstring says it's an application.
In Go, `internal/` was how I said "this is a binary, not a library". Here I say it by not shipping
one.

## Types are optional; strict mode makes them not

The same idea at a larger scale. Python runs code with no type annotations at all, so an
unannotated function passes every default check:

```python
def double(x):
    return x * 2
```

With `typeCheckingMode = "standard"`, pyright reports `0 errors`. With `"strict"`, four: the
parameter's type is missing and unknown, and so is the return type. Strict mode in CI is the closest
thing this project has to Go's compiler: a function whose types aren't known doesn't get merged.

Strict is a habit across the tools, not only pyright's. Pytest's `strict = true` turns a mistyped
marker from a warning into an error (`'slwo' not found in markers configuration`). Without it the
run passes with `1 warning`, and the test I meant to mark slow silently isn't.

## `uv.lock` is `go.sum` plus `mix.lock`, because resolution goes the other way

Go chooses dependency versions by **Minimal Version Selection**: the lowest version that satisfies
every `go.mod`. That works because every Go module declares the versions it was built against, so
the minimum is a version someone actually tested. `go.sum` is only about integrity.

`uv`, like Mix and Bundler, picks the *highest* versions the constraints allow, and the lockfile pins
the result. I asked `uv` to resolve Go's way instead, with this project's real constraints:

```
$ uv lock --resolution lowest
Updated colorama v0.4.6 -> v0.4.0
Updated iniconfig v2.3.1 -> v1.0.1
Updated nodeenv v1.11.0 -> v1.6.0
Updated packaging v26.3 -> v22.0
Updated pluggy v1.6.0 -> v1.5.0
Updated pygments v2.21.0 -> v2.7.2
Updated typing-extensions v4.16.0 -> v4.1.0
```

Every one of those is a floor some package's author wrote by hand (pytest says `packaging>=22`), and
nothing checks that the floor still works. In Go the floor is written by the tools: `go get` and
`go mod tidy` record the version the build actually used, so the minimum is a version someone built
with. Where a floor is missing altogether, lowest means *lowest*. With pytest loosened to `>=8`, whose
8.0.0 states none for `packaging`, the same command picked `packaging` 14.0, uploaded in 2014.
Minimal selection only works in an ecosystem that writes its minimums down. So Python resolves high
and locks: `uv.lock` records the exact version of all 11 packages and a `sha256` hash for each file,
36 in all, which is the part `go.sum` does.

CI installs with `uv sync --locked`, which refuses a lockfile that doesn't match `pyproject.toml`:

```
$ uv sync --locked      # after adding httpx to pyproject.toml and not running uv lock
error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
```

Nothing upgrades until I run `uv lock --upgrade` and commit the result. Same property as Go, reached
the other way round.

## What changed from the Go version

- **The layout.** `cmd/` and `internal/` become one package under `src/`. Go needed `cmd/` because one
  module can build several binaries; Python's equivalent is a `[project.scripts]` entry per command
  in `pyproject.toml`, which arrives with the first command in milestone 1.
- **Milestone 0 has a test.** Go's milestone 0 had no code at all. Here CI runs pytest from the first
  commit, and pytest exits with status 5 when it finds no tests, which fails the build. So the one
  thing milestone 0 does build, the layout, gets the test.
- **The design came over whole.** Its "As built" notes describe Go code, so they're now "As built in
  Go", linked to quantic-agent-go. Each one becomes this repository's as its milestone is ported. The
  decisions keep their text: they're records of what was decided, at the time
  ([decisions/README](../decisions/README.md)).
- **The page builder is part of the gate.** `docs/lessons/pages/build.py` was a loose script in the Go
  repository. In a Python repository it's Python like any other, so ruff and strict pyright check it
  too.

## What I'm taking into milestone 1

- `src/quantic_agent/`, installed by `uv sync`. Run things with `uv run`, never with a bare `python`.
- `_name` for anything private, and trust pyright, not the interpreter, to hold the line.
- Test through the public names. A test that needs a private helper is telling me something.
- Every check strict from the start: pyright, pytest, `uv sync --locked`. Relaxing later is easy;
  tightening a codebase that grew up loose isn't.

## Open question I haven't resolved

Modules or subpackages? `quantic_agent/llm.py` is a module; `quantic_agent/llm/` with an
`__init__.py` is a package of them. Go only has the second kind (a package is a directory). Python
style leans flat, the same way Go's does. Leaning towards one module per Go package (`llm.py`,
`mcp.py`, `provenance.py`) until one grows too big for a file.

---

**Next:** Lesson 01, with milestone 1.
