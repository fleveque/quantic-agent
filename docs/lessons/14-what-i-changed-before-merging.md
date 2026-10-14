# Lesson 14 — What I changed before merging

**Milestone 14** — the agent finds out what I corrected. A merge used to mean only "approved".
On quantic#492, the first Week Ahead I published, a review corrected six of the seven locales on
the branch before I merged, and the agent kept its own drafts. Now `--sync` reads the published files back and stores
every section I changed, next to what it wrote.

*Also readable as a [formatted page](https://claude.ai/artifact/4cqkDMqeD5yZVVBpcWP6NR), with a [code walkthrough](https://claude.ai/artifact/7Vk6EXjDr8NE7Ac6Q14UJs) of every
change the milestone made.*

---

## What I chose

Three uses of my corrections were on the table ([decision 0016](../decisions/0016-corrections-captured.md)):
**capture** them; a **per-locale glossary** with a check that holds a known-wrong term, so that
Catalan "divisió" for dividend can't come back; and **retrieval**, past corrections shown to the
translator as examples, as approved answers are shown to the writer since milestone 10. I chose
capture only, for now. The other two are built on it.

## Read it where it was merged

A merged pull request has a `merge_commit_sha`. Quantic squash-merges, so that's the one commit
`main` gained, and its files are exactly what the merge published. Reading `main` instead would be
right on the day of the merge and wrong the next time anyone touched those files.

The App reads files through GitHub's contents API: `GET /repos/{repo}/contents/{path}?ref={sha}`.
The reply is JSON with the file in base64, wrapped in lines of 60 characters.
`base64.b64decode` skips the line breaks, and so does Go's `base64.StdEncoding` (I checked:
`"aGVsbG8g\nd29ybGQ=\n"` decodes to `"hello world"`). It's a GET. The client still has no method
that writes a file, moves a ref or merges, and the module's docstring says so.

The path goes through `urllib.parse.quote` before it's put in the URL. It leaves `/` alone by
default (its `safe` argument), so a whole path can go through it at once. Go's `url.PathEscape`
escapes `/` too, so Go code escapes each segment. A post's path has nothing to escape. A file name
with a space would.

## Sections, not lines

A prose section is one paragraph on one line. A line diff of the Catalan correction says "line 456
changed", which is true and tells you nothing. The unit is the one the writer and the translator
produce: a section. `weekahead.read_back` already turned a file into its frontmatter and its
sections by key, to check every file before it's written. Now it reads the published file too.

Each section that differs is stored with both texts. The data block is compared as data, and the
rest of the frontmatter together. A file I left out, or one that no longer reads back as a post, is
stored whole. Unchanged sections aren't stored at all.

One idiom: the sections of both files, in order, without repeats:

```python
for key in dict.fromkeys([*draft_sections, *sections]):
    ...
```

A dict keeps insertion order (guaranteed since Python 3.7), and `fromkeys` drops repeats, so this
is an ordered set. Python has no ordered set type of its own. A `set` would lose the order, and the
output would come out in a different order from one run to the next.

## A word diff in thirty lines

`--run N` shows each correction the way `git diff --word-diff` would:

```
ca watch: ... alhora que [-informa dels beneficis durant la-]{+presenta resultats aquella+} mateixa setmana.
```

That's `difflib.SequenceMatcher` from the standard library: give it two lists, ask for
`get_opcodes()`, and it says which runs are equal, replaced, deleted or inserted. The lists are
words. The first version kept each word's trailing space as part of the word, so that a change of
three words came out as one mark, not three. A test I wrote for adding a sentence at the end failed
on it: `"termini."` and `"termini. "` aren't equal, so the last word showed as changed. Now the words
are compared without their space and shown with it.

Go has nothing like `difflib` in its standard library. Elixir does, and it's a different algorithm:

```
List.myers_difference(a, b)
eq: ["que", "reflecteix", "el", "creixement"]
del: ["de", "la", "seva", "divisió."]
ins: ["del", "seu", "dividend."]
eq: ["Iberdrola"]
ins: ["la"]
eq: ["segueix", "amb", "un", "pagament"]
```

On the same Catalan sentence, `difflib` says:

```
que reflecteix el creixement [-de-]{+del seu dividend. Iberdrola+} la [-seva divisió. Iberdrola-] segueix
```

Both are correct: apply either and you get my sentence. Myers, which git uses too, finds the
fewest edits, 8 here. `difflib` matches the longest common runs first, and lines up the
"la" of "de la seva" with the "la" of "la segueix", 9 edits. Its documentation says it aims for
diffs that "look right" to people, not minimal ones. It only changes how a diff is shown. What's
stored is the two texts, and any diff can be computed again from them.

## Read once, retried until it is

The pull request records the merge commit only once its files have been read, in the same
transaction as the corrections. So "merged, no merge commit" means "not read yet", and every sync
reads those, however old. That's how quantic#492, merged this morning by the version before this
one, was read the first time I ran this one. It's also how a read that fails halfway is retried:
nothing of it was kept.

A store test checks that by making the insert fail with two corrections for the same section. The
merge stays unread and no correction is kept. Without the transaction, that test fails: the merge
commit is recorded and the next sync wouldn't try again.

## quantic#492, read back

The real App, a copy of my database (the installed agent, the one the timer runs, doesn't know
migration 0007 yet):

```
$ quantic-agent --sync
run 3: corrected before merging: es (watch), ca (summary, watch), fr (watch), de (watch), it (summary, watch), pt (watch)
```

Four seconds. Again, 0.6 seconds and nothing asked of GitHub. `--run 3` shows the diffs, every
correction from the review, "per [-davant-]{+darrere+}" included:

```
ca watch: ... manté una {+sòlida+} classificació de [-seguretat sòlida-]{+segura+} amb un creixement recent que ha quedat lleugerament per [-davant-]{+darrere+} de la seva tendència de llarg termini.
pt watch: ... enquanto também [-relata lucros-]{+divulga seus resultados+} na mesma semana.
```

English is untouched: no correction for it. That's design open question 12's measure, counted from
real reviews: which locales get corrected, and how much.

## What I'm taking on

- Approval isn't approval of what was written. Store what was published.
- Compare in the unit the work is done in. Here that's a section, not a line or a file.
- "Not done yet" can be a column that's still empty. Fill it in the same transaction as the work,
  and a failure is retried for free.
- `difflib` isn't git's diff. Store the texts, not a diff.
- A dict is Python's ordered set.

---

**Previous:** [Lesson 13 — Sunday, without me](13-sunday-without-me.md)
