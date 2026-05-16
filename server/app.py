"""FastAPI service for the AFFINE interviewer.

Serves three things from one process:
- the landing page (sibling doors: browse the wiki / start an interview)
- the wiki browser (server-rendered markdown)
- the two-phase interview (optional intake form → streamed conversation → notes)
"""
from __future__ import annotations

import asyncio
import html
import json
import time
import uuid
from pathlib import Path
from typing import Optional

import re
from datetime import datetime, timezone

from anthropic import Anthropic
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import ANTHROPIC_API_KEY, MODEL_DEFAULT, MODEL_FAST, STATIC_DIR, UPLOADS_DIR
from loop import Session, step_stream
from transcripts import (
    find_notes_path_for_session,
    save_edited_notes,
    save_transcript,
    write_notes,
)
from wiki_render import list_dir, render_page

SESSIONS: dict[str, Session] = {}
CLIENT = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

IDLE_TIMEOUT_SECONDS = 60 * 60
SWEEP_INTERVAL_SECONDS = 5 * 60

app = FastAPI(title="AFFINE interviewer", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---- shared HTML shell ----------------------------------------------------

_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght,SOFT,WONK@0,9..144,300..900,0..100,0..1;1,9..144,300..900,0..100,0..1&family=Inter+Tight:ital,wght@0,400..600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/static/app.css">
</head>
<body class="{body_class}">
"""

_NAV = """<header class="topbar">
  <a class="wordmark" href="/">AFFINE<span class="wordmark-sub">·2026</span></a>
  <nav class="topnav">
    <a href="/wiki">the wiki</a>
    <a href="/interview">the interview</a>
    <a href="/contribute">contribute</a>
  </nav>
</header>
"""

_FOOT = """<footer class="sitefoot">
  <span>AFFINE 2026 · a living wiki + a two-way interview</span>
  <span class="foot-mark">— Hostačov</span>
</footer>
</body></html>"""


def shell(title: str, body: str, *, body_class: str = "", nav: bool = True,
          extra_head: str = "", extra_body: str = "") -> str:
    head = _HEAD.format(title=html.escape(title), body_class=body_class)
    if extra_head:
        head = head.replace("</head>", extra_head + "\n</head>")
    chrome = _NAV if nav else ""
    return head + chrome + body + extra_body + _FOOT


# ---- landing --------------------------------------------------------------

_LANDING = """
<div class="landing-glow glow-a"></div>
<div class="landing-glow glow-b"></div>
<div class="landing-glow glow-c"></div>
<main class="landing">
  <section class="landing-hero">
    <p class="landing-greeting">welcome, friend —</p>
    <h1 class="landing-title">a garden of<br><em>alignment</em> ideas.</h1>
    <p class="landing-lede">A living wiki for the AFFINE 2026 seminar — the
    concept tree, the people, the talks, the threads — and a two-way conversation
    about what you care about, what you want to know, and what you're worried
    about regarding the future. Wander it, or sit and talk.</p>
  </section>
  <section class="doors">
    <a class="door" href="/wiki">
      <span class="door-k">I.</span>
      <span class="door-h">Wander the wiki</span>
      <span class="door-d">Seventy-five concepts, fifty-seven people, the talks,
      the themes — cross-linked and citation-grounded. Follow whatever pulls you.</span>
      <span class="door-go">enter the garden →</span>
    </a>
    <a class="door door-alt" href="/interview">
      <span class="door-k">II.</span>
      <span class="door-h">Sit with the interviewer</span>
      <span class="door-d">A conversation grounded in everything above. It has
      read the whole wiki, so it can talk specifics — people, concepts, talks.</span>
      <span class="door-go">begin the conversation →</span>
    </a>
  </section>
  <p class="landing-foot-line">built citation-first · every claim traces to a
  raw source · the interviewer can't make things up</p>
</main>
"""


@app.get("/", response_class=HTMLResponse)
def landing():
    return shell("AFFINE 2026", _LANDING, body_class="page-landing")


# ---- wiki browser ---------------------------------------------------------


# (label, href, kind) — the persistent "where can I wander" rail.
_WIKI_START = [
    ("The index", "/wiki", "index"),
    ("What AFFINE is", "/wiki/overview", "overview"),
    ("Cohort portrait", "/wiki/cohort-portrait", "overview"),
    ("The concept tree", "/wiki/tree", "tree"),
    ("Pods", "/wiki/pods", "pods"),
]
_WIKI_LAYERS = [
    ("Concepts", "/wiki/concepts/", "75"),
    ("Participants", "/wiki/participants/", "57"),
    ("Themes", "/wiki/themes/", "14"),
    ("Talks", "/wiki/talks/", "27"),
    ("Tags", "/wiki/tags/", "5"),
    ("Mentors", "/wiki/mentors/", ""),
    ("Sources", "/wiki/sources/", ""),
]


def _wiki_sidebar(active: str) -> str:
    act = "/wiki/" + active.strip("/").removesuffix(".md")
    if active.strip("/").removesuffix(".md") in ("index", ""):
        act = "/wiki"

    def _link(label, href, extra="", *, prefix=False):
        h = href.rstrip("/")
        if prefix:
            is_cur = act == h or act.startswith(h + "/")
        else:
            is_cur = act.rstrip("/") == h
        cur = ' class="cur"' if is_cur else ""
        tail = f' <span class="s-count">{extra}</span>' if extra else ""
        return f'<li><a href="{href}"{cur}>{html.escape(label)}{tail}</a></li>'

    start = "".join(_link(l, h) for l, h, _ in _WIKI_START)
    layers = "".join(_link(l, h, c, prefix=True) for l, h, c in _WIKI_LAYERS)
    return f"""
<aside class="wiki-side">
  <div class="side-sticky">
    <p class="side-cap">start here</p>
    <ul class="side-list">{start}</ul>
    <p class="side-cap">wander a layer</p>
    <ul class="side-list">{layers}</ul>
    <a class="side-talk" href="/interview">↳ or talk to the interviewer</a>
  </div>
</aside>
"""


def _wiki_frame(active: str, title: str, kicker: str, meta: str,
                home: str, content_html: str) -> str:
    return f"""
<div class="wiki-wrap">
  {_wiki_sidebar(active)}
  <main class="wiki-main">
    <article class="wiki-article">
      <div class="wiki-head">
        <p class="wiki-kicker">{html.escape(kicker)}</p>
        {home}
      </div>
      <div class="wiki-title-row">
        <h1>{html.escape(title)}</h1>
        {meta}
      </div>
      <div class="wiki-body">
        {content_html}
      </div>
    </article>
  </main>
</div>
"""


def _wiki_view(page_rel: str) -> HTMLResponse:
    rendered = render_page(page_rel)
    if rendered is None:
        # Fall back to an auto-generated directory listing (so layer folders
        # like /wiki/concepts/ are browsable without an index.md).
        rendered = list_dir(page_rel)
    if rendered is None:
        body = _wiki_frame(
            page_rel, "Nothing here", "not found", "",
            '<a class="wiki-home" href="/wiki">← wiki index</a>',
            f"<p>There's no wiki page or layer at <code>{html.escape(page_rel)}</code>. "
            'Wander back to the <a href="/wiki">index</a>, or pick a layer on the left.</p>',
        )
        return HTMLResponse(
            shell("Not found · AFFINE wiki", body, body_class="page-wiki"),
            status_code=404,
        )

    fm, content_html = rendered
    title = str(fm.get("title") or page_rel)
    ptype = str(fm.get("type") or "")
    updated = str(fm.get("last_updated") or "")
    is_index = page_rel.strip("/").rstrip(".md") in ("index", "")

    kicker = "the wiki" if is_index else (ptype or "page")
    meta = f'<span class="wiki-updated">updated {html.escape(updated)}</span>' if updated else ""
    home = "" if is_index else '<a class="wiki-home" href="/wiki">← wiki index</a>'

    body = _wiki_frame(page_rel, title, kicker, meta, home, content_html)
    return HTMLResponse(shell(f"{title} · AFFINE wiki", body, body_class="page-wiki"))


@app.get("/wiki", response_class=HTMLResponse)
def wiki_index():
    return _wiki_view("index.md")


@app.get("/wiki/{page_path:path}", response_class=HTMLResponse)
def wiki_page(page_path: str):
    return _wiki_view(page_path)


# ---- interview page -------------------------------------------------------


@app.get("/interview", response_class=HTMLResponse)
def interview_page():
    body = (STATIC_DIR / "interview.html").read_text(encoding="utf-8")
    return shell(
        "The interview · AFFINE 2026",
        body,
        body_class="page-interview",
        extra_body='<script src="/static/interview.js"></script>',
    )


@app.get("/contribute", response_class=HTMLResponse)
def contribute_page():
    body = (STATIC_DIR / "contribute.html").read_text(encoding="utf-8")
    return shell(
        "Contribute · AFFINE 2026",
        body,
        body_class="page-interview",
        extra_body='<script src="/static/contribute.js"></script>',
    )


# ---- upload (→ unprocessed/uploads) ---------------------------------------

_SAFE_SEG = re.compile(r"[^A-Za-z0-9._ -]")


def _safe_segment(seg: str) -> str:
    seg = seg.strip().replace("\x00", "")
    if seg in ("", ".", ".."):
        return ""
    return _SAFE_SEG.sub("_", seg)[:120]


def _safe_relpath(rel: str) -> str:
    parts = [_safe_segment(p) for p in str(rel).replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    return "/".join(parts[-12:])  # cap depth, drop empties/..


@app.post("/api/upload")
async def upload(
    files: list[UploadFile] = File(...),
    rel_paths: list[str] = Form(default=[]),
    label: str = Form(default=""),
):
    """Accept file(s) or a whole folder; land them in unprocessed/uploads/<batch>/.

    The browser sends one `files` part per file and (for folder uploads) a
    parallel `rel_paths` part per file carrying webkitRelativePath so the tree
    is preserved. Everything is path-sanitized — nothing escapes the batch dir.
    """
    if not files:
        raise HTTPException(400, "no files")
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    lbl = _safe_segment(label) or "upload"
    batch = UPLOADS_DIR / f"{ts}__{lbl}"
    batch.mkdir(parents=True, exist_ok=True)

    written = []
    for i, f in enumerate(files):
        rel = rel_paths[i] if i < len(rel_paths) and rel_paths[i] else (f.filename or f"file-{i}")
        safe = _safe_relpath(rel) or f"file-{i}"
        dest = (batch / safe).resolve()
        try:
            dest.relative_to(batch.resolve())
        except ValueError:
            continue  # path escaped the batch dir — skip
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = await f.read()
        dest.write_bytes(data)
        written.append({"path": safe, "bytes": len(data)})

    # Drop a manifest so the integrate pass has provenance.
    (batch / "_manifest.json").write_text(
        json.dumps({
            "received_at": ts,
            "label": label or None,
            "file_count": len(written),
            "files": written,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "batch": batch.name,
        "file_count": len(written),
        "files": written,
    }


# ---- interview API --------------------------------------------------------


class StartRequest(BaseModel):
    # Phase-1 intake form. Every field optional.
    name: Optional[str] = None
    working_on: Optional[str] = None
    time_available_minutes: Optional[float] = None
    stuck_on: Optional[str] = None
    want_to_know: Optional[str] = None
    fast: bool = False
    model: Optional[str] = None


class TurnRequest(BaseModel):
    text: str


class NotesUpdateRequest(BaseModel):
    content: str


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _phase1_from(req: StartRequest) -> dict:
    return {
        "name": req.name,
        "working_on": req.working_on,
        "stuck_on": req.stuck_on,
        "want_to_know": req.want_to_know,
    }


@app.post("/api/sessions/start-stream")
def start_stream(req: StartRequest):
    """Create a session from the phase-1 form and stream the opening turn."""
    if CLIENT is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set")
    sid = uuid.uuid4().hex
    chosen_model = req.model or (MODEL_FAST if req.fast else MODEL_DEFAULT)
    phase1 = _phase1_from(req)
    session = Session(
        session_id=sid,
        participant_hint=(req.name or "").strip() or None,
        phase1=phase1,
        model=chosen_model,
    )
    if req.time_available_minutes and req.time_available_minutes > 0:
        session.time_budget_seconds = int(req.time_available_minutes * 60)
    SESSIONS[sid] = session

    def gen():
        yield _sse({"type": "session_created", "session_id": sid})
        try:
            for evt in step_stream(session, None, CLIENT, opening=True):
                yield _sse(evt)
            tpath = save_transcript(sid, session.participant_hint,
                                    session.started_at, session.messages, session.phase1)
            yield _sse({"type": "transcript_saved", "path": str(tpath)})
        except Exception as e:
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform",
                 "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/sessions/{session_id}/turn-stream")
def turn_stream(session_id: str, req: TurnRequest):
    if CLIENT is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set")
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.ended:
        raise HTTPException(410, "session has already ended")

    def gen():
        try:
            for evt in step_stream(session, req.text, CLIENT, opening=False):
                yield _sse(evt)
            tpath = save_transcript(session_id, session.participant_hint,
                                    session.started_at, session.messages, session.phase1)
            yield _sse({"type": "transcript_saved", "path": str(tpath)})
            if session.ended:
                SESSIONS.pop(session_id, None)
                yield _sse({"type": "notes_writing"})
                npath = write_notes(session_id, session.participant_hint,
                                    session.messages, tpath, session.phase1)
                yield _sse({"type": "notes_written", "path": str(npath)})
        except Exception as e:
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform",
                 "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.post("/api/sessions/{session_id}/end")
async def end_session(session_id: str):
    session = SESSIONS.pop(session_id, None)
    if not session:
        raise HTTPException(404, "session not found")
    session.ended = True
    session.end_reason = session.end_reason or "participant ended on their side"
    tpath = save_transcript(session_id, session.participant_hint,
                            session.started_at, session.messages, session.phase1)
    npath = await asyncio.to_thread(
        write_notes, session_id, session.participant_hint,
        session.messages, tpath, session.phase1,
    )
    content = ""
    try:
        content = Path(npath).read_text(encoding="utf-8")
    except Exception:
        pass
    return {
        "transcript_path": str(tpath),
        "notes_path": str(npath),
        "notes_content": content,
        "duration_seconds": session.elapsed(),
    }


@app.get("/api/sessions/{session_id}/notes")
def get_notes(session_id: str):
    npath = find_notes_path_for_session(session_id)
    if not npath:
        raise HTTPException(404, "no notes found for that session_id")
    return {
        "notes_path": str(npath),
        "notes_content": npath.read_text(encoding="utf-8"),
        "has_been_edited": npath.with_suffix(".draft.md").exists(),
    }


@app.put("/api/sessions/{session_id}/notes")
def put_notes(session_id: str, req: NotesUpdateRequest):
    npath = find_notes_path_for_session(session_id)
    if not npath:
        raise HTTPException(404, "no notes found for that session_id")
    save_edited_notes(npath, req.content)
    return {
        "notes_path": str(npath),
        "notes_content": npath.read_text(encoding="utf-8"),
        "has_been_edited": npath.with_suffix(".draft.md").exists(),
    }


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "anthropic_api_key": bool(ANTHROPIC_API_KEY),
        "active_sessions": len(SESSIONS),
    }


# ---- idle-session sweeper -------------------------------------------------


async def _sweep_idle_sessions():
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            stale = [sid for sid, s in SESSIONS.items()
                     if s.idle_seconds() > IDLE_TIMEOUT_SECONDS]
            for sid in stale:
                session = SESSIONS.pop(sid, None)
                if not session or not session.messages:
                    continue
                session.ended = True
                session.end_reason = session.end_reason or "idle timeout"
                try:
                    tpath = save_transcript(sid, session.participant_hint,
                                            session.started_at, session.messages,
                                            session.phase1)
                    await asyncio.to_thread(
                        write_notes, sid, session.participant_hint,
                        session.messages, tpath, session.phase1,
                    )
                except Exception:
                    pass
        except Exception:
            pass


@app.on_event("startup")
async def _start_sweeper():
    asyncio.create_task(_sweep_idle_sessions())
