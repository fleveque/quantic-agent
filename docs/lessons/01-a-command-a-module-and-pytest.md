# Lesson 01 — A command, a module, and pytest

**Milestone 1** — the first code: a `quantic-agent` command with nothing to do yet, and the three
calculators from [design §3.3](../design.md#33-provenance) that the research loop will call when a
draft needs a derived figure. The same milestone as Go's, ported. Most of what Go made me write
down, Python either does for me or does differently, and two of the differences change results.

*Also readable as a [formatted page](https://claude.ai/artifact/PNf2nngL7T3FPAaPquhEcv), with a [code walkthrough](https://claude.ai/artifact/QvzKAQqd5Jee9C4Q5LUCBJ) of every file the
milestone added or changed.*

---

## What landed

```
src/quantic_agent/cli.py     the command: argparse, --version
src/quantic_agent/tools.py   pct_change, diff, total
tests/test_cli.py            4 tests
tests/test_tools.py          13 tests, from 4 parametrized functions
```

`pyproject.toml` gained one table, and the command exists:

```toml
[project.scripts]
quantic-agent = "quantic_agent.cli:main"
```

```
$ uv run quantic-agent
quantic-agent: no tasks defined yet
$ uv run quantic-agent --version
quantic-agent 0.0.0
$ uv run quantic-agent --publish
usage: quantic-agent [-h] [--version]
quantic-agent: error: unrecognized arguments: --publish
$ echo $?
2
```

## A command is a line of configuration, not a directory

Go needed `cmd/agent/main.go`: a directory per binary, a `package main`, a `func main()`. Here a
command is one line naming a function, and `uv sync` writes a small script into `.venv/bin`:

```
#!/home/fleveque/Projects/quantic/quantic-agent/.venv/bin/python
import sys
from quantic_agent.cli import main
if __name__ == "__main__":
    ...
    sys.exit(main())
```

So `main()` returns the exit status and the script exits with it. A second command later is a second
line in `[project.scripts]`, pointing at another function.

## The Go reason for `run()` doesn't apply

In Go, `main` was one line, `os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))`, because `os.Exit`
ends the process at once, skipping deferred calls, and a test can't survive it. So `run` took its
whole world as arguments and *returned* the code.

Python's `sys.exit` doesn't end the process. It raises an exception, `SystemExit`, which unwinds the
stack like any other:

```
def f():
    try:
        sys.exit(3)
    finally:
        print("finally ran")

try:
    f()
except SystemExit as e:
    print("caught SystemExit, code", e.code)
```

```
finally ran
caught SystemExit, code 3
```

Cleanup runs, and a test can catch it. (`os._exit` is Go's `os.Exit`: it skips the `finally`. Nobody
calls it.) That changes the design:

- **argparse may exit.** Go's global flag set uses `ExitOnError`, which kills the test runner, so Go
  used a local `FlagSet` with `ContinueOnError`. argparse's default is the same "exit on error", but
  its exit is an exception, so I kept the default. `--help`, `--version` and a bad option each raise
  `SystemExit` (0, 0, 2), the same codes Go returned by hand.
- **No writers passed in.** Go's `run` took `io.Writer`s so the test could hand it buffers. pytest
  captures the real `stdout` and `stderr` instead, through the `capsys` fixture:

```python
def test_unknown_option(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--publish"])
    assert exit_.value.code == 2
    out, err = capsys.readouterr()
    assert out == ""
    assert "unrecognized arguments: --publish" in err
```

`main(argv=None)` still takes its arguments, because that's cheap: `None` means "the process's own".

A *fixture* is pytest's dependency injection. The test names a parameter `capsys`, and pytest sees
the name and passes in the object. Nothing in Go's `testing` package works by parameter name.

**Options are spelled `--version`.** Go's `flag` takes `-version`; argparse follows the GNU style,
with two dashes for long names. CLAUDE.md already wrote `--model` and `--ollama` for the flags to
come.

## The version comes from the project

Go's version was a package variable, `var version = "dev"`, to be overwritten at build time with
`-ldflags` in milestone 13. Here it's read from the installed project's metadata, which comes from
`pyproject.toml`:

```python
parser.add_argument(
    "--version",
    action="version",
    version=f"%(prog)s {version('quantic-agent')}",
)
```

`importlib.metadata.version` takes the *distribution* name, with the hyphen (lesson 00). One place to
change, and no build step.

`%(prog)s` is the program name, which I set explicitly with `prog="quantic-agent"`. Without it,
argparse uses the name of whatever script is running, and under the tests that's pytest:

```
E       AssertionError: assert 'pytest 0.0.0\n' == 'quantic-agent 0.0.0\n'
```

## Table-driven tests are a decorator

Go's tests were a slice of structs and a `t.Run` loop. pytest's version is `parametrize`:

```python
@pytest.mark.parametrize(
    ("previous", "current", "want"),
    [
        pytest.param(1.50, 1.55, 10 / 3, id="raise"),
        pytest.param(0.80, 0.40, -50, id="cut in half"),
        # ...
    ],
)
def test_pct_change(previous: float, current: float, want: float) -> None:
    assert tools.pct_change(previous, current) == approx(want)
```

pytest generates one test per row, named from the `id`
(`test_pct_change[cut in half]`), and passes each row's values in by parameter name. The test body
is the loop body. There's no `tt := tt` question and no closure: each case is a separate call.

**Coming from Elixir:** this is closer to ExUnit than Go was. A decorator is a function applied to
the function below it, at import time, so this is plain code generating tests, much like a
comprehension generating `test` blocks in Elixir, minus the macros.

## The float that isn't 0.05, again, and sooner

Go hid it from me first. `fmt.Println(1.55 - 1.50)` printed `0.05`, because Go evaluates constant
expressions exactly at compile time. Python has no untyped constants, so it shows the problem straight
away, the way Ruby and Elixir do:

```
>>> 1.55 - 1.50
0.050000000000000044
```

The tests compare within a tolerance, with `pytest.approx`:

```python
def approx(want: float) -> object:
    return pytest.approx(want, abs=1e-9)
```

The `abs=` matters. pytest's default tolerance is *relative*: a millionth of the expected value. For
a dividend yield of 3.33 that's 0.0000033, three thousand times looser than the billionth Go's tests
used. Given `abs` alone, pytest uses only that. Breaking the helper to compare with `==` shows what
the tolerance absorbs:

```
E       assert 0.050000000000000044 == 0.05
E       assert 3.333333333333336 == 3.3333333333333335
```

The second is new to me: the calculator divides `0.050000000000000044` by 1.5, and the test's own
`10 / 3` divides differently. Neither is wrong.

## A tool that refuses, and a division that refuses first

```python
def pct_change(previous: float, current: float) -> float:
    if previous <= 0:
        raise ValueError(f"pct_change needs a positive previous value, got {previous}")
    return (current - previous) / previous * 100
```

In Go the guard was needed for zero: float division by zero is silent there, `1.25 / 0.0` is `+Inf`,
and the first thing to object was `encoding/json`, much later. **Python's float division by zero
raises**:

```
>>> 1.25 / 0.0
ZeroDivisionError: division by zero
```

So without the guard, a zero base still fails at once. I could watch it: removing the check makes the
"zero base" test fail with `ZeroDivisionError`, not with a wrong number. But it fails with the wrong
error, and a negative base still goes straight through:

```
E       Failed: DID NOT RAISE ValueError
FAILED tests/test_tools.py::test_pct_change_refuses_a_base_that_is_not_positive[negative base]
```

−2 → −1 is a rise, and the formula calls it −50%. That's the case the guard is really for, in both
languages.

**Infinity hasn't gone away, though.** Overflow still makes one (`1e308 * 10` is `inf`), and Python's
`json` writes it without complaint, as something that isn't JSON:

```
>>> json.dumps({"x": float("inf")})
'{"x": Infinity}'
>>> json.loads('{"x": Infinity, "y": NaN}')
{'x': inf, 'y': nan}
```

Go's encoder refused (`json: unsupported value: +Inf`). Python's accepts both ways unless told
`allow_nan=False`. Milestone 5 reads tool arguments from the model as JSON, so that's where this
matters next.

**Errors are raised, not returned.** Go's `PctChange` returned `(float64, error)`, and the caller
checked. Here the happy path just returns a float, and a refusal is an exception, which the test
expects with `pytest.raises(ValueError, match=...)`. Which exceptions the agent defines, and how a
caller tells them apart, is milestone 3.

## `sum` changed the result

Go's `Sum` was a loop: `total += v`. Python's built-in `sum`, since 3.12, compensates for the rounding
error of each addition as it goes. I asked both for ten 0.1s:

```
$ go run ./cmd/zzsum                     # a scratch program calling quantic-agent-go's tools.Sum
0.9999999999999999
$ uv run python -c 'print(sum([0.1] * 10))'
1.0
```

The Python answer is closer to the truth, and it's a different number. The tests don't see it,
because both are within a billionth of 1. The provenance check would: it compares a figure in a draft
with the figure the tool returned, exactly. That's fine as long as the same code produces both, and
it does, but it means a manifest recorded by the Go version and one recorded by this one can disagree
in the last digit for the same inputs. Noted in design §3.3.

The function is called `total`, not `sum`: a `sum` in the module would hide the built-in, inside the
module and for anyone doing `from quantic_agent.tools import *`.

## Types: an `int` is a `float`

The calculators are annotated `float`, and the tests call `tools.pct_change(0, 1.25)` with an `int`.
Strict pyright accepts it: the typing rules treat `int` as acceptable wherever `float` is expected.
Go would refuse `PctChange(0, 1.25)` with a typed `int` variable (an untyped constant `0` converts),
so Go code says `float64(n)`. Python's arithmetic mixes them anyway: `3 / 2` is `1.5`.

## A trap when breaking code on purpose

Every guarantee a test claims gets checked by breaking the code and watching it fail. Doing that, one
test kept failing *after* I'd restored the file. I had changed `<= 0` to `== 0`, run the tests,
copied the original back, and run them again, all within one second. Python caches compiled modules
in `__pycache__`, and decides whether a cache is stale by the source file's modification time, in
whole seconds, and its size. Same second, same size: it ran the broken version.

```
$ uv run pytest -q tests/test_tools.py      # after restoring tools.py
1 failed, 12 passed in 0.01s
$ find . -name __pycache__ -not -path './.venv/*' -exec rm -r {} +
$ uv run pytest -q tests/test_tools.py
13 passed in 0.01s
```

An editor saving by hand never hits this; a script that edits and reruns can. For experiments:
`PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider`.

## CI stops excusing itself, again

Milestone 0 added the Python steps behind `if: hashFiles('pyproject.toml') != ''`, so CI could pass
before there was a project. The project exists, so the guard is gone, as Go's was at its milestone 1.
A green tick now always means all five checks ran.

## What I'm taking into milestone 2

- A command is a `[project.scripts]` line pointing at a function that returns the exit code.
- `SystemExit` is an exception. Let argparse raise it; catch it in tests with `pytest.raises`.
- `capsys` instead of passing writers. Fixtures arrive by parameter name.
- `pytest.approx` with `abs=`, never the default, for figures that matter.
- Float division by zero raises, but infinity and NaN still exist, and `json` will write them.
- The standard library may be more careful than my Go code was. Check the result, not just the shape.

---

**Previous:** [Lesson 00 — Layout, packages, and privacy by convention](00-layout-packages-and-privacy-by-convention.md)
