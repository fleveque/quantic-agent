# Lesson pages

How the formatted pages are made, so every lesson and walkthrough looks the same. The style is
quantic-agent-go's, carried over unchanged.

- `lesson-head.html`: the stylesheet and fonts of a lesson page.
- `walkthrough-head.html`: the same for a walkthrough (code excerpts with file and line captions,
  numbered steps, "try it" boxes, a reading map).
- `build.py`: fills `[[path|start|end]]` markers in a walkthrough template with code copied verbatim
  from the repository.

A page is `<title>…</title>` + the head + a body. The head starts after the title, so the title
goes first:

```sh
{ echo '<title>The Layout, Line by Line</title>'; cat walkthrough-head.html; cat body00.html; } > template00.html
python3 build.py . walkthrough00 template00.html   # writes walkthrough00.html
```

Build from a checkout of the commit the walkthrough names, so the excerpts are that commit's.
Templates and built pages are working files, not committed; the published page is the record.
