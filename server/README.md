# AFFINE interviewer server

One FastAPI process that serves the whole thing:

- **`/`** — landing (sibling doors: browse the wiki / start an interview)
- **`/wiki`, `/wiki/{path}`** — the wiki, server-rendered from `../wiki/*.md`
- **`/interview`** — the two-phase interview (optional intake form → streamed conversation → editable notes)

No build step, no Node. The frontend is hand-written HTML/CSS/JS in `static/`, the wiki is rendered with python-markdown, the conversation streams over SSE.

## Run

```bash
cd /root/affine-interviewer/server
uv sync
cp .env.example .env   # then put your real key in it
# or: export ANTHROPIC_API_KEY=sk-ant-...
uv run uvicorn app:app --reload --port 8000
```

Open http://127.0.0.1:8000 .

## Layout

```
app.py           FastAPI: landing, wiki routes, interview API, static mount, idle sweeper
loop.py          conversation loop + tool dispatch + two-phase opening
tools.py         AFFINE wiki tools (participant/search/open/open_many/follow + end/time)
wiki_render.py   markdown → HTML with internal-link rewriting + frontmatter split
transcripts.py   transcript saving + the reflector notes pass
config.py        paths, model (claude-opus-4-7), env
prompts/
  system.md      the interviewer system prompt (three-question frame, anti-hallucination)
  notes.md       the reflector prompt (notes the participant edits)
static/
  app.css        the "Atelier Garden" theme
  interview.html the interview body (phase-1 form + chat + notes)
  interview.js   SSE chat client + form + notes editing
transcripts/     auto-saved JSON, one per session (overwritten each turn)
notes/           reflector output; first participant edit preserves a .draft.md
```

## The two phases

1. **Intake form** (`/interview`) — seven optional fields. Posted to
   `POST /api/sessions/start-stream`; injected into the model's opening as a
   `<phase1>` block so it opens from substance instead of cold. "Time available"
   pre-sets the budget so the interviewer doesn't re-ask it.
2. **Conversation** — open-ended, streamed, wiki-grounded. The model can call
   `participant() / search() / open() / open_many() / follow()` (surfaced to the
   UI as quiet "❧ looking up …" traces) plus `end_interview()` and
   `update_time_budget()`.

When the interview ends (model calls `end_interview`, or the participant clicks
"end & write the notes", or idle-timeout), a reflector pass writes structured
notes; the participant reads and edits them in-place before they're filed. The
auto-generated original is preserved as `<basename>.draft.md` on first edit.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/sessions/start-stream` | create session from phase-1 form, stream opening (SSE) |
| POST | `/api/sessions/{id}/turn-stream` | send a message, stream the reply (SSE) |
| POST | `/api/sessions/{id}/end` | end manually; returns notes content |
| GET | `/api/sessions/{id}/notes` | fetch current notes |
| PUT | `/api/sessions/{id}/notes` | save participant-edited notes |
| GET | `/api/health` | key present? active sessions? |

SSE event types: `session_created`, `text_delta`, `tool_use`, `tool_done`,
`turn_done`, `transcript_saved`, `notes_writing`, `notes_written`, `error`.

Sessions are in-memory; idle sessions are swept after 1h (transcript + notes
saved). For production scale, back the session store with Redis/Postgres.
