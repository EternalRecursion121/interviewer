# Interviewer server

Python + FastAPI service that runs the interview. Hooks the wiki up to the Anthropic API with five read-only tools, a time-aware system prompt, transcript saving, and a post-interview reflection pass that auto-writes notes for the wiki.

## Layout

```
server/
  app.py            FastAPI endpoints (sync + streaming SSE)
  loop.py           conversation loop + tool dispatch + time-tag injection
  tools.py          5 wiki tools (member, search, open, open_many, follow)
                    + 3 operational tools (end_interview, update_time_budget,
                                           capture_newsletter_preference)
  transcripts.py    save transcripts; run reflector pass to write wiki notes
  config.py         paths, model selection, env vars
  prompts/
    system.md       interviewer system prompt
    notes.md        post-interview reflector prompt
  scripts/
    sync-ngrok-url.sh   write the current ngrok URL into /root/idealists-site/.env
  smoke_test.py     end-to-end CLI sanity check (uses the non-streaming path)
  SYSTEMD.md        systemd setup for production
  transcripts/              auto-saved JSON transcripts (one per session, overwritten on every turn)
  notes/                    auto-written reflector notes (review before copying to wiki/interviews/)
  human_requests/           "talk to a human" handoff requests, one JSON per request
  newsletter_subscriptions/ captured newsletter signups, one JSON per signup
  pyproject.toml
```

## Run

```bash
cd /root/interviewer/server
uv sync
export ANTHROPIC_API_KEY=...
uv run uvicorn app:app --reload --port 8000
```

In production this runs as `interviewer.service` (and is exposed via `interviewer-ngrok.service`). See `SYSTEMD.md`.

## API

Sessions are held in-memory. The streaming endpoints (`*-stream`) are what the production frontend uses; the non-streaming endpoints exist for the smoke test and as a debugging fallback.

### `POST /sessions/start-stream` (SSE)

Create a new session AND stream the opening turn in a single request.

```json
{ "member_hint": "lou", "fast": false, "model": null }
```

Emits `session_created` first, then `text_delta` / `tool_use` / `tool_done` / `turn_done`, then `transcript_saved`.

### `POST /sessions/{id}/turn-stream` (SSE)

Send a participant message; stream the assistant turn.

```json
{ "text": "i've got about 30 minutes" }
```

Same event types as above. After `turn_done`, the transcript is overwritten with the latest state and a `transcript_saved` event is emitted. If the model called `end_interview`, a `notes_writing` event is sent, the reflector runs, then `notes_written` is sent with the path.

### `POST /sessions` and `POST /sessions/{id}/turn`

Non-streaming equivalents. Same shapes; everything happens in one synchronous call. Used by `smoke_test.py`.

### `POST /sessions/{id}/end`

End the session manually. Saves the transcript and runs the reflector. Returns the notes content for the participant to review.

### `GET /sessions/{id}/notes` and `PUT /sessions/{id}/notes`

Fetch the current notes file for a session, or replace its content with a participant-edited version. The first edit preserves the auto-generated original as `<basename>.draft.md`.

### `POST /human-requests`

Capture a "talk to a human" handoff request from the frontend modal. Writes one JSON file per request into `human_requests/`.

```json
{ "name": "lou", "contact": "lou@example.com", "note": "..." }
```

### `GET /sessions/{id}` and `GET /health`

Session metadata for debugging, and a liveness check.

## How it works

**System prompt is two cached blocks:**
1. The handcrafted interviewer prompt (`prompts/system.md`)
2. A blob of always-loaded wiki context — `index.md`, `overview.md`, `principles.md`, `themes/identification-gaps.md`, `themes/social-topology.md`, `concepts/glossary.md`, `open-questions.md`. Marked with `cache_control: ephemeral` so it's a single cache write per session.

**Tools** are designed for fluid wiki navigation:
- `member(name_or_handle)` — bundles member page + their box channel in one call
- `search(query, type?)` — keyword grep with snippets
- `open(path)` — single page
- `open_many(paths[])` — batch read
- `follow(reference)` — resolve a wikilink slug

Plus three operational tools the model uses to drive the conversation:
- `update_time_budget(minutes_remaining)` — set or extend the budget
- `capture_newsletter_preference(...)` — record a personalised-newsletter signup
- `end_interview(reason)` — close the session

The first five are surfaced to the frontend as humanized "looking up X" / "searching the wiki for Y" indicators while the model is mid-reasoning. The three operational tools are not surfaced.

**Time awareness** is injected per turn as a `<time>` tag inside the user message. The model sees elapsed seconds, the budget the participant set (if any), and a flag when ≥80% through or past time. There's no scheduled wrap — the model decides what to do with the signal.

**Sanitization:** participant text has `<participant>` tags stripped before being re-wrapped, so the model can trust the tag boundary.

**Continuous transcript saving:** every turn overwrites a deterministic per-session JSON file. Cheap insurance against process loss mid-conversation.

**Stale-session sweeper:** a background task runs every 5 minutes and finalizes any session that has been idle for more than 1 hour (writes notes, drops it from memory).

**Two-step ending:** when the session ends, the transcript saves synchronously and the reflector pass runs off-thread so the API response is fast.

## Notes for the wiki

The reflector writes a structured markdown file per interview into `notes/`. The intent is that someone reviews it and decides whether to copy it into `wiki/interviews/<date>-<slug>.md`. The reflector prompt (`prompts/notes.md`) instructs it to surface:

- Who the person is (with citation)
- What they care about (verbatim quotes with turn numbers)
- What they want to know
- What they're worried about
- What they want from the collective
- What they're making
- Surprises (the most valuable section)
- Suggested wiki updates as a bulleted list

## Frontend

This service is frontend-agnostic. The production frontend lives at `/root/idealists-site/` (SvelteKit, deployed to Vercel). It reads `PUBLIC_INTERVIEWER_API` at runtime and points its `/interview` page at this server (via ngrok in production).
