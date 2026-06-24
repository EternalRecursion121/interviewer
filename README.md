# AFFINE interviewer

A Claude-based interviewer + navigable wiki for the [AFFINE Network](https://affi.ne)
seminar — a one-month residential program on AI superintelligence alignment
(Hostačov, Czechia, 28 April – 28 May 2026, ~30 participants).

A 25-person event has bandwidth for only a fraction of all possible
conversations. This project helps close that gap. It:

1. Runs a ~15-minute opt-in structured conversation with each participant about
   what they're working on, curious about, and worried about.
2. Surfaces relevant ideas, projects, and people from the wiki during the
   conversation ("you should talk to X about Y").
3. Folds what it learns back into the wiki.
4. Answers questions participants ask about the collective, grounded in the wiki.

The value isn't analytical depth — it's fast retrieval across ~25 people's notes
plus the shared alignment-concept backbone. The output is the participants' own
thinking, made navigable.

## Repository layout

```
server/          FastAPI app: landing page, server-rendered wiki, the interview
build_wiki/      deterministic generators (concepts, participants, backlinks)
raw/             immutable source data (tech-tree CSVs, intros) — gitignored
wiki/            generated/ingested markdown wiki — gitignored
unprocessed/     interview transcripts/notes/uploads awaiting an integrate pass
processed/       frozen archive of consumed inputs
CLAUDE.md        the wiki schema + conventions (read this before editing the wiki)
```

`raw/`, `wiki/`, `unprocessed/`, and `processed/` contents are **not tracked**
(generated data and potentially sensitive interview material — see
[`.gitignore`](.gitignore)). Only the structure and contract READMEs are kept.

## The three data layers

1. **Raw sources** (`raw/`) — immutable, never edited. The AFFINE tech tree
   (115 alignment topics), the resource list, and participant intros.
2. **The wiki** (`wiki/`) — markdown, owned entirely by Claude. One page per
   concept, per person (split across `participants/`, `mentors/`, `team/` by
   role), per theme. Written and rewritten as new sources arrive.
3. **The schema** ([`CLAUDE.md`](CLAUDE.md)) — how the wiki is structured and
   the anti-hallucination rules. Co-evolves with the wiki.

## Quick start

Run the server (serves the landing page, the wiki, and the interview):

```bash
cd server
uv sync
cp .env.example .env          # then put your real ANTHROPIC_API_KEY in it
uv run uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000 . See [`server/README.md`](server/README.md) for the
API, the two-phase interview flow, and the server internals.

## Rebuilding the wiki from raw data

The concept and participant pages are deterministically generated — never
hand-edit `wiki/concepts/*.md`. After dropping in new raw data:

```bash
bash raw/fetch_sheet.sh                    # refresh the tech tree from Google Sheets
python3 build_wiki/build_concepts.py       # rebuild concepts, tags, tree
python3 build_wiki/build_participants.py   # rebuild person pages
python3 build_wiki/build_backlinks.py      # rebuild concept ← person backlinks
```

## Adding interview material

The server drops transcripts, reflector notes, and uploads into `unprocessed/`.
They are **not** in the wiki until an operator-triggered *integrate pass* folds
them in (a deliberate Claude pass, never auto-run from the server). See the
"Integrate" and "Ingest" sections of [`CLAUDE.md`](CLAUDE.md) and
[`unprocessed/README.md`](unprocessed/README.md) for the contract.

## Anti-hallucination

The interviewer represents the seminar to its own participants, so a wrong claim
damages trust. The core rule: **if you can't cite a raw source, you can't write
the claim.** Quote participants rather than paraphrasing what they "think", and
don't elaborate concept pages beyond what the tech-tree sheet says. Full
protocol in [`CLAUDE.md`](CLAUDE.md).
