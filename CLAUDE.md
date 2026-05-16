# CLAUDE.md — wiki schema for the AFFINE interviewer

This file is the schema for the AFFINE Network wiki at `wiki/`. It tells future Claudes how the wiki is structured, what conventions to follow, and how to add to it without hallucinating.

The wiki was started 2026-05-14 by Claude Opus 4.7. It follows the [LLM Wiki pattern from karpathy](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f).

## What the interviewer is for

AFFINE is a one-month residential seminar on AI superintelligence alignment held at Hostačov, Czechia (28 April – 28 May 2026, ~30 participants). Not everyone can talk to everyone else; a 25-person event has bandwidth for a fraction of all possible conversations. The interviewer is a Claude-based agent that:

1. Conducts a ~15 minute opt-in structured conversation with each participant about what they're working on, what they're curious about, and what they're worried about.
2. During the conversation, surfaces ideas, projects, and people from elsewhere in the wiki ("you should talk to X about Y").
3. After the conversation, updates the wiki with what it learned.
4. Answers questions other participants ask about the collective via a chatbot interface backed by this wiki.

The LLM's value is not analytical depth — it's speed of retrieval across 25 people's notes plus the shared alignment-concept backbone. The output is the participants' own thinking, made navigable.

## Three layers

1. **Raw sources** — `raw/`. Immutable. Never edited.
   - `raw/sheet/Topics.csv` — the AFFINE tech tree (115 alignment topics, with descriptions, guidance, resources, tags, prerequisites). Synced from [this public Google Sheet](https://docs.google.com/spreadsheets/d/13o-_6jETt-qq8gShKqbSicyvxdwjP2CXCZBxZWjN3Ks/) (the same one the live app at learn.affi.ne reads from).
   - `raw/sheet/Resources.csv` — readings paired with URLs and authors (~350 entries).
   - `raw/sheet/Topic_tags.csv` — the five top-level groupings (Basics, Foundations, Meta, Outer Alignment, Obstruction).
   - `raw/affine-tech-tree/` — the full Next.js source of learn.affi.ne, for reference.
   - `raw/site/index.html` — affi.ne homepage as of 2026-05-14.
   - `raw/participants/` — TBD. Participant intros, interview transcripts, anything else gathered during the seminar.
2. **The wiki** — `wiki/`. Markdown. Owned by Claude entirely. Written and rewritten as new sources arrive.
3. **The schema** — this file. Co-evolves with the wiki.

## Directory layout

```
wiki/
  index.md                            content catalog (every page, one-line summary, organized by category)
  log.md                              append-only log of ingest/lint/query operations
  overview.md                         what AFFINE is and what this wiki is
  tree.md                             the alignment-concept tree as a nested bullet list, grouped by tag
  concepts/<slug>.md                  one page per topic in the tech tree (generated)
  tags/<slug>.md                      one page per top-level grouping (generated)
  participants/index.md               groups people by role: Participants / Mentors / Event Team / Visitors
  participants/<slug>.md              one page per person — generated from intros
  participants/enrichment/<slug>.md   web-fetched summaries of public artifacts; never overwritten by builder
  themes/<slug>.md                    synthesis pages — shared interests, open questions, worries, reading pointers
  sources/<slug>.md                   pointers describing each raw source
```

## Participant roles — important

People in the wiki play four distinct roles. The interviewer MUST honor this distinction:

- **participant** — a seminar fellow. The primary audience of the interviewer. ~23 people.
- **mentor** — invited alignment researchers (e.g. Linda Linsefors, Kaarel Hänni, Ouro). Don't treat them as "fellow learners" — they're the people fellows go to for technical feedback. ~5 people.
- **event-team** — organizers and operations staff (Sofie, Philip, Pauliina, etc.). Don't suggest these people as research collaborators; instead surface them when a participant raises a logistics, well-being, or community-design question.
- **visitor** — short-term drop-ins, including the founder of Lens Academy (Luc Brinkman) who makes the tech-tree app. Treat as participants but flag the limited time window.

The `role:` field in each participant page's frontmatter is canonical. When the interviewer points one person at another, it MUST surface the role.

## Page conventions

### Frontmatter

Every wiki page starts with YAML frontmatter:

```yaml
---
title: short title
type: overview | concept | tag | participant | theme | source
sources:
  - raw/path/to/source           # always cite at least one raw source
  - wiki/other-page.md           # if synthesized from other wiki pages
last_updated: 2026-05-14
---
```

If you can't cite a source, you cannot write the claim. This is the most important rule. Hallucinated participants, hallucinated quotes, and hallucinated concept descriptions will poison the interviewer.

### Citations

- For concept content drawn from the sheet: `[src: raw/sheet/Topics.csv row N]` or `[src: raw/sheet/Resources.csv row N]`.
- For interview content: `[src: raw/participants/<handle>.md]` plus a date or line reference.
- For affi.ne site content: standard markdown links.
- For tech-tree app source: `[src: raw/affine-tech-tree/<path>]`.

The interviewer needs to be able to re-find any claim.

### Cross-links

Internal links use relative markdown paths, e.g. `[Agency](../concepts/agency.md)`. Concept slugs are lowercase-kebab from the topic Name (e.g. "AGI/ASI's various meanings" → `agi-asis-various-meanings`).

### Tone

Calm, descriptive, third-person. Concept pages mostly reproduce the sheet's framing — they exist to be linked into, not to editorialize. Participant pages should quote the participant's own words; paraphrases must be labelled (`paraphrased:`) and cite the underlying interview turn.

### Length

200–800 words per page. If a page grows past 1500 words, split it and link from the parent.

## Operations

### Ingest

When a new source arrives (e.g. an interview transcript):

1. Read the source in full.
2. Decide what kind of page(s) it touches: a new participant page? updates to existing participants? a new theme that connects several participants? a concept that needs participant cross-links added?
3. Write or revise the relevant pages with proper citations.
4. Update `index.md` if a new page was created or a page's one-line summary changed.
5. Append to `log.md` with the prefix `## [YYYY-MM-DD] ingest | <source>`.

### Integrate (unprocessed/ → processed/)

The server drops interview transcripts, reflector notes, and uploaded files
into `unprocessed/` (subdirs `transcripts/`, `notes/`, `uploads/`). They are
**not** in the wiki until an operator-triggered *integrate pass* folds them in.

When the operator says **"integrate the unprocessed stuff"** (or similar):

1. Read everything under `unprocessed/` — every `uploads/<batch>/` (check its
   `_manifest.json`), every transcript, every note.
2. For each item, apply the **Ingest** steps above (decide what pages it
   touches; write/revise with citations; obey the anti-hallucination protocol).
   Cite the source as `[src: unprocessed/<…>]` while working; after step 4
   rewrite those citations to `[src: processed/<…>]` so links stay valid.
3. Append a `## [YYYY-MM-DD] integrate | <summary>` entry to `log.md`.
4. **Move** each fully-consumed input from `unprocessed/<stream>/<item>` to
   `processed/<stream>/<item>` (same relative path). Partially-usable items
   stay in `unprocessed/` with a log note explaining why.
5. Update `index.md` if a page was created.

Constraints: never auto-run this from the server — it is a deliberate Claude
pass. Never edit `processed/` (frozen archive). Transcripts/notes may contain
non-public remarks: integrate the *signal* into synthesis pages, not verbatim
private content; when unsure, leave it in `unprocessed/` and flag it in the
log. Full contract: [`unprocessed/README.md`](unprocessed/README.md).

### Re-syncing the tech tree

The tech-tree sheet is the live source-of-truth for the seminar's reading list. To refresh:

```sh
cd raw && ./fetch_sheet.sh         # re-downloads the three CSVs
python3 build_wiki/build_concepts.py   # regenerates wiki/concepts/, wiki/tags/, wiki/tree.md
```

Concept pages are deterministically generated — never hand-edit `wiki/concepts/*.md`. If you need to add commentary, link from a separate `wiki/themes/<slug>.md` page.

### Query

When asked a question:

1. Read `index.md` first.
2. Read the relevant pages. Follow citations to raw sources when the wiki claim alone isn't sufficient.
3. Synthesize the answer with inline citations to wiki pages.
4. If the answer surfaces a useful new connection, file it as a new theme page.

### Lint

Periodically check:

- contradictions between pages
- claims with no source citation (delete or chase down)
- participant pages with no underlying interview transcript in `raw/participants/` (hallucination — remove)
- broken cross-links
- pages with no inbound links from `index.md`

## Anti-hallucination protocol

The interviewer represents the AFFINE seminar to its own participants. A wrong claim about what someone said, what someone is working on, or what a concept means damages trust. Three rules:

1. **Don't write a participant's name unless you can trace it to a real source in `raw/participants/`.** A participant page that doesn't trace back should not exist.
2. **Don't paraphrase what someone "thinks" — quote them.** Direct quotes should reproduce the message exactly. If you're paraphrasing, label it as such and cite the underlying turn.
3. **Don't add gloss to concept pages beyond what the sheet says.** The tech-tree sheet is curated by the AFFINE organizers; if a concept's description is terse, leave it terse. Adding plausible-sounding elaboration is hallucination.

## Builder scripts

- `build_wiki/build_concepts.py` — generates `wiki/concepts/*.md`, `wiki/tags/*.md`, and `wiki/tree.md` from `raw/sheet/*.csv`. Deterministic; rerunnable.
- `build_wiki/build_participants.py` — generates `wiki/participants/*.md` and `wiki/participants/index.md` from `raw/AFFINE Seminar - Names & Faces.txt`. Also auto-links each participant to tech-tree concepts via a fuzzy match (the `CONCEPT_ALIASES` map at the top of the script). The `enrichment/` subdirectory is preserved across rebuilds.
- `build_wiki/build_index.py` — TBD. Regenerates `wiki/index.md` from the current set of pages.

Run them after dropping in new raw data:

```sh
cd /root/affine-interviewer
bash raw/fetch_sheet.sh                    # refresh the tech tree from Google Sheets
python3 build_wiki/build_concepts.py       # rebuild concepts, tags, tree
python3 build_wiki/build_participants.py   # rebuild participant pages
```
