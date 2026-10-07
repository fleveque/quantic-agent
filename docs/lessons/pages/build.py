"""Builds a walkthrough page from a template, pulling every code excerpt
verbatim from the repository so the page can't drift from the source.

Usage: python3 build.py <dir> <output-name> <template-file>
  reads <dir>/<template-file>, writes <dir>/<output-name>.html

Marker: [[path|start|end]] — the excerpt runs from the first line containing
`start` to the first line at or after it containing `end`. Paths are relative
to the repository root. Build from a clean checkout of the commit the page
names, so the excerpts are that commit's.

End forms:
  ^    the end of the top-level block that starts there: the last non-blank
       line before the next unindented one (Python has no closing brace).
       A closing bracket at the start of a line doesn't count, so a
       signature wrapped over several lines stays in one block.
  $    the end of the file
  }    the next line that is exactly "}" (the end of a top-level Go declaration)
  A>B  the next line containing A, then the next line whose stripped text is B
  else the next line containing it
"""

import html
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
MARKER = re.compile(r"\[\[([^|\]]+)\|([^|\]]+)\|([^\]]+)\]\]")
LANGUAGES = {"go": "go", "sql": "sql", "py": "python", "toml": "toml", "sh": "bash"}


def _starts_a_block(line: str) -> bool:
    return bool(line) and not line[0].isspace() and line[0] not in ")]}"


def span(lines: list[str], start: str, end: str) -> tuple[int, int]:
    a = next(i for i, line in enumerate(lines) if start in line)
    if end == "^":
        after = range(a + 1, len(lines))
        nxt = next((i for i in after if _starts_a_block(lines[i])), len(lines))
        return a, max(i for i in range(a, nxt) if lines[i].strip())
    if end == "$":
        return a, max(i for i in range(a, len(lines)) if lines[i].strip())
    if end == "}":
        return a, next(i for i in range(a, len(lines)) if lines[i] == "}")
    if ">" in end:
        first, closer = end.split(">", 1)
        f = next(i for i in range(a, len(lines)) if first in lines[i])
        return a, next(i for i in range(f + 1, len(lines)) if lines[i].strip() == closer)
    return a, next(i for i in range(a, len(lines)) if end in lines[i])


def excerpt(m: re.Match[str]) -> str:
    path, start, end = m.group(1), m.group(2), m.group(3)
    lines = (REPO / path).read_text().split("\n")
    try:
        a, b = span(lines, start, end)
    except StopIteration, ValueError:
        sys.exit(f"marker not found: {m.group(0)}")
    code = html.escape("\n".join(lines[a : b + 1]), quote=False)
    lang = LANGUAGES.get(path.rsplit(".", 1)[-1], "plaintext")
    return (
        f'<figure class="code"><figcaption><span class="file">{path}</span>'
        f'<span class="lines">lines {a + 1}&ndash;{b + 1}</span></figcaption>'
        f'<pre><code class="language-{lang}">{code}</code></pre></figure>'
    )


def main() -> None:
    here = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else "walkthrough"
    template = sys.argv[3] if len(sys.argv) > 3 else "template.html"
    out, n = MARKER.subn(excerpt, (here / template).read_text())
    (here / f"{name}.html").write_text(out)
    print(f"{n} excerpts, {len(out) // 1024} KB")


if __name__ == "__main__":
    main()
