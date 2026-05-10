# CLAUDE.md — wiki schema

This file is the schema for the Idealists Collective wiki at `wiki/`. It tells future Claudes how the wiki is structured, what conventions to follow, and how to add to it without hallucinating.

The wiki was started 2026-05-08 by Claude Opus 4.7. It follows the [LLM Wiki pattern from karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## Three layers

1. **Raw sources** — `raw/`. Immutable. Never edited.
   - `raw/members.csv` — public members list from `idealistscollective.org/members`
   - `raw/application_responses.csv` — Google Form responses from people joining or following the collective
   - `raw/messages.json` — Discord history from the `Idealists Collective` server (5984 messages, 60 channels, downloaded 2026-05-08)
   - `raw/writings/<slug>/content.md` — essays from the site
2. **The wiki** — `wiki/`. Markdown. Owned by Claude entirely. Written and rewritten as new sources arrive.
3. **The schema** — this file. Co-evolves with the wiki.

## Directory layout

```
wiki/
  index.md               content catalog (every page, one-line summary, organized by category)
  log.md                 append-only log of ingest/lint/query operations
  overview.md            what the collective is
  principles.md          the DNA (utopian, autonomous, playful, alive, cooperative, loving)
  concepts/<slug>.md     ideas the collective uses (aliveness, jazz coding, ...)
  projects/<slug>.md     things the collective is making (web decompiler, magazine, ...)
  members/<handle>.md    one page per identifiable member
  channels/<name>.md     one page per active discord channel
  themes/<slug>.md       synthesis pages — what people care about / want / worry about
  writings/<slug>.md     summaries of essays in raw/writings/
  sources/<slug>.md      pointers describing each raw source
```

## Page conventions

### Frontmatter

Every wiki page starts with YAML frontmatter:

```yaml
---
title: short title
type: overview | principle | concept | project | member | channel | theme | writing | source
sources:
  - raw/path/to/source           # always cite at least one raw source
  - wiki/other-page.md           # if synthesized from other wiki pages
last_updated: 2026-05-08
---
```

If you can't cite a source, you cannot write the claim. This is the single most important rule. Hallucinated members, hallucinated quotes, and hallucinated project status will poison the interviewer.

### Citations

Inline citations follow the form `[src: raw/messages.json#<channel> <author>]` for messages, `[src: raw/application_responses.csv row N]` for form responses, and standard markdown links for site/writing references. The interviewer needs to be able to re-find any claim.

### Tone

Calm, descriptive, third-person. The wiki is not the collective's marketing — it's an inventory. Claims about what someone *believes* should be quoted from their own words; claims about what someone *does* should point to evidence (messages, code repos, writings).

### Length

Aim for 200–800 words per page. If a page grows past 1500 words, split it into sub-pages and link from the parent.

## Operations

### Ingest

When a new source arrives:

1. Read the source in full.
2. Decide what kind of page(s) it touches: a new entity? a new concept? an update to an existing project? a contradiction with an existing claim?
3. Write or revise the relevant pages with proper citations.
4. Update `index.md` if a new page was created or a page's one-line summary changed.
5. Append to `log.md` with the prefix `## [YYYY-MM-DD] ingest | <source>`.

### Query

When asked a question:

1. Read `index.md` first. The catalog points you at the right pages.
2. Read the relevant pages. If they cite raw sources, follow the citations when the wiki claim alone isn't sufficient.
3. Synthesize the answer with inline citations to wiki pages (and through them to raw sources).
4. If the answer surfaces a useful new connection, file it as a new page.

### Lint

Periodically check:

- contradictions between pages
- claims with no source citation (delete or chase down)
- members in `members/` who don't appear in `raw/members.csv` or `raw/application_responses.csv` (these are hallucinations and must be removed)
- projects that have not been mentioned in the discord history in the last 60 days (mark as `status: dormant`)
- pages with no inbound links from `index.md`
- broken cross-links

## Anti-hallucination protocol

The interviewer represents the collective. A wrong claim about what a member said, what a project does, or what was decided at a meeting damages trust. Three rules:

1. **Don't write a name unless you can find it in `raw/members.csv`, `raw/application_responses.csv`, or as an `author_name` in `raw/messages.json`.** A member page that doesn't trace back to a real person should not exist.
2. **Don't paraphrase what someone "thinks" — quote them.** Direct quotes in the wiki should reproduce the message content exactly. If you're paraphrasing, label it as such (`paraphrased:`) and cite the underlying message.
3. **When in doubt, write less.** A short, cited page is more useful to the interviewer than a long, vibey one with embellishments. The interviewer can chase citations back to raw sources when it needs more.

## Builder scripts

Some sections of the wiki are big enough that handwriting them is impractical. They live in `build_wiki/`:

- `build_member_pages.py` — generates `wiki/members/*.md` from `raw/application_responses.csv` joined against `raw/members.csv` and indexed against `raw/messages.json`. Deterministic structured extraction — no LLM calls, no hallucination surface.
- `build_channel_summaries.py` — for each non-trivial channel in `raw/messages.json`, dumps the channel into a working file and (if `ANTHROPIC_API_KEY` is set) asks Claude to summarize, with strict citation requirements baked into the summary prompt. If no API key, dumps unsummarized message logs which the interviewer can read directly.
- `build_themes.py` — synthesis across member pages and channel summaries.
- `build_index.py` — regenerates `wiki/index.md` from the current set of pages.

Run them after dropping in new raw data; they are rerunnable.

## What the interviewer is for

The interviewer is a Claude-based agent that talks to a member of the collective and asks them three things:

1. what they care about
2. what they want to know
3. what they're worried about regarding the future

It also answers questions the member has about the collective, using this wiki. It cannot write to the wiki, cannot run shell, cannot edit files. See `system_prompt.md`.
