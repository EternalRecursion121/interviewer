# Interviewer server

Python + FastAPI service that runs the interview. Hooks the wiki up to the Anthropic API with five read-only tools, a time-aware system prompt, transcript saving, and a post-interview reflection pass that auto-writes wiki notes.

## Layout

```
server/
  app.py            FastAPI endpoints
  loop.py           conversation loop + tool dispatch + time-tag injection
  tools.py          5 wiki tools: member, search, open, open_many, follow
  transcripts.py    save transcripts; run reflector pass to write wiki notes
  config.py         paths, model selection, env vars
  prompts/
    system.md       interviewer system prompt
    notes.md        post-interview reflection prompt
  transcripts/      auto-saved JSON transcripts
  notes/            auto-written wiki entries (review before copying to wiki/interviews/)
  pyproject.toml
```

## Run

```bash
cd /root/interviewer/server
uv sync
export ANTHROPIC_API_KEY=...
uv run uvicorn app:app --reload --port 8000
```

## API

### `POST /sessions`

Create a new interview session.

```json
{
  "member_hint": "lou",
  "deep": false
}
```

Both fields optional. Returns:

```json
{
  "session_id": "abc123…",
  "opening_turn": "hi — quick: how long do you have, and how familiar are you with the collective?"
}
```

### `POST /sessions/{id}/turn`

Send a participant message.

```json
{
  "text": "i've got about 30 minutes",
  "time_budget_seconds": 1800
}
```

`time_budget_seconds` is optional — pass it the first time the participant tells the interviewer how long they have. The interviewer's time-tag will then update on each subsequent turn.

### `POST /sessions/{id}/end`

End the session. Saves the transcript and runs the reflector pass to generate notes.

```json
{
  "transcript_path": "server/transcripts/2026-05-10T13-45-22Z_lou_abc12345.json",
  "notes_path": "server/notes/2026-05-10_lou.md",
  "duration_seconds": 1834
}
```

### `GET /sessions/{id}`

Session metadata for debugging.

### `GET /health`

Liveness check.

## How it works

**System prompt is two cached blocks:**
1. The handcrafted interviewer prompt (`prompts/system.md`)
2. A blob of always-loaded wiki context — `index.md`, `overview.md`, `principles.md`, `themes/identification-gaps.md`, `themes/social-topology.md`, `concepts/glossary.md`. Marked with `cache_control: ephemeral` so it's a single cache write per session.

**Tools** are explicitly designed for fluid wiki navigation:
- `member(name_or_handle)` — bundles member page + their box channel in one call
- `search(query, type?)` — ripgrep with snippets
- `open(path)` — single page
- `open_many(paths[])` — batch read
- `follow(reference)` — resolve a wikilink slug

**Time awareness** is injected per turn as a `<time>` tag inside the user message. The model sees elapsed seconds, the budget the participant set (if any), and a flag when ≥80% through or past time. There's no scheduled wrap — the model decides what to do with the signal.

**Sanitization:** participant text has `<participant>` tags stripped before being re-wrapped, so the model can trust the tag boundary.

**Two-step ending:** when the session ends, transcripts are saved synchronously and the reflector pass runs off-thread so the API response is fast.

## Notes for the wiki

The reflector writes a structured markdown file per interview into `server/notes/`. The intent is that someone reviews it and decides whether to copy it into `wiki/interviews/<date>-<slug>.md`. The reflector prompt (`prompts/notes.md`) instructs it to surface:

- Who the person is (with citation)
- What they care about (verbatim quotes with turn numbers)
- What they want to know
- What they're worried about
- What they want from the collective
- What they're making
- Surprises (the most valuable section)
- Suggested wiki updates as a bulleted list

## Frontend

This service is frontend-agnostic. The existing SvelteKit frontend at `/root/interviewer/src/` can be pointed at this service by changing its `/api/interview` calls to hit `POST /sessions/{id}/turn`. Or build a new frontend; the JSON contract is small.
