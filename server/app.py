"""FastAPI service for the Idealists Collective interviewer.

Endpoints:
- POST /sessions             create a new session, return its id + opening turn
- POST /sessions/{id}/turn   send a participant message, return the assistant turn
- POST /sessions/{id}/end    end the session (saves transcript + writes notes)
- GET  /sessions/{id}        fetch metadata for the session (debugging)
- POST /human-requests       capture a "talk to a human" handoff request

Sessions are held in-memory. For production-scale you'd back this with Redis
or postgres, but for the interview use case (tens of concurrent sessions, max)
in-memory is fine.
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Optional

from anthropic import Anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from config import ANTHROPIC_API_KEY, ANTHROPIC_MAX_RETRIES, MODEL_DEFAULT, MODEL_FAST
from loop import Session, opening_turn, step, step_stream, save_newsletter_subscription
from stage1 import normalize_stage1, time_choice_to_budget_seconds, newsletter_payload
from transcripts import (
    find_notes_path_for_session,
    save_edited_notes,
    save_transcript,
    write_notes,
)


SESSIONS: dict[str, Session] = {}
CLIENT = (
    Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=ANTHROPIC_MAX_RETRIES)
    if ANTHROPIC_API_KEY
    else None
)

# How long a session can sit idle (no /turn-stream activity) before we give
# up on it, save the transcript, write notes, and drop it from memory.
IDLE_TIMEOUT_SECONDS = 60 * 60  # 1 hour
SWEEP_INTERVAL_SECONDS = 5 * 60  # check every 5 minutes


app = FastAPI(title="Interviewer", version="0.1.0")

# CORS — open for now; tighten when frontend is hosted somewhere specific.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- request / response models -------------------------------------------


class Stage1Newsletter(BaseModel):
    email: Optional[str] = None
    frequency: Optional[str] = None
    interested_in: Optional[str] = None


class Stage1OpenQuestions(BaseModel):
    membership: Optional[str] = None
    growth: Optional[str] = None
    roles: Optional[str] = None
    action: Optional[str] = None


class Stage1Payload(BaseModel):
    value: Optional[str] = None
    falling_short: Optional[str] = None
    ideas: Optional[str] = None
    involvement: Optional[str] = None
    time_minutes: Optional[int] = None
    no_time_limit: bool = False
    newsletter: Optional[Stage1Newsletter] = None
    open_questions: Optional[Stage1OpenQuestions] = None


class CreateSessionRequest(BaseModel):
    member_hint: Optional[str] = Field(
        default=None,
        description="Optional name or handle the participant gave on the frontend, used for member() lookup.",
    )
    fast: bool = Field(
        default=False,
        description="Use the faster/cheaper Sonnet fallback instead of the default Opus model.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override the interviewer model. Takes precedence over `fast` if set.",
    )
    stage1: Optional[Stage1Payload] = Field(
        default=None,
        description="Answers from the stage-1 pre-interview form, if the participant filled it out.",
    )


class CreateSessionResponse(BaseModel):
    session_id: str
    opening_turn: str


class TurnRequest(BaseModel):
    text: str
    time_budget_seconds: Optional[int] = Field(
        default=None,
        description="If the participant just told the interviewer how long they have, pass that number here so the time-tag can update.",
    )


class TurnResponse(BaseModel):
    text: str
    elapsed_seconds: int
    time_budget_seconds: Optional[int]
    interview_ended: bool = False
    end_reason: Optional[str] = None
    transcript_path: Optional[str] = None
    notes_path: Optional[str] = None


class EndSessionResponse(BaseModel):
    transcript_path: str
    notes_path: str
    notes_content: str  # full markdown — show to participant for review/edit
    duration_seconds: int


class NotesResponse(BaseModel):
    notes_path: str
    notes_content: str
    has_been_edited: bool  # True if a `.draft.md` sibling exists (i.e., participant has edited)


class NotesUpdateRequest(BaseModel):
    content: str


class HumanRequest(BaseModel):
    name: Optional[str] = None
    contact: str
    note: Optional[str] = None


HUMAN_REQUESTS_DIR = Path(__file__).parent / "human_requests"


# ---- endpoints ------------------------------------------------------------


def _save_transcript_quietly(session: Session) -> None:
    """Best-effort transcript save for the disconnect/abort path — never raises.

    Used in the streaming generators' `finally` so a client that drops the SSE
    connection mid-turn (GeneratorExit) still gets its conversation persisted.
    """
    try:
        save_transcript(
            session.session_id,
            session.member_hint,
            session.started_at,
            session.messages,
            stage1=session.stage1,
        )
    except Exception:
        pass


def _apply_stage1(session: Session, req: CreateSessionRequest) -> None:
    """Normalize stage-1 answers onto the session: store them, set the time
    budget, and persist a newsletter subscription if one was given."""
    raw = req.stage1.model_dump() if req.stage1 else None
    s1 = normalize_stage1(raw)
    session.stage1 = s1
    budget = time_choice_to_budget_seconds(s1)
    if budget is not None:
        session.time_budget_seconds = budget
    np = newsletter_payload(s1)
    if np is not None:
        try:
            save_newsletter_subscription(
                session.session_id, {**np, "member_hint": session.member_hint}
            )
        except Exception:
            # A failed newsletter write must never abort session creation.
            pass


@app.post("/sessions", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest):
    if CLIENT is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set")
    sid = uuid.uuid4().hex
    chosen_model = req.model or (MODEL_FAST if req.fast else MODEL_DEFAULT)
    session = Session(
        session_id=sid,
        member_hint=req.member_hint,
        model=chosen_model,
    )
    SESSIONS[sid] = session
    _apply_stage1(session, req)
    text = opening_turn(session, client=CLIENT)
    return CreateSessionResponse(session_id=sid, opening_turn=text)


@app.post("/sessions/{session_id}/turn", response_model=TurnResponse)
async def turn(session_id: str, req: TurnRequest):
    if CLIENT is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set")
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.ended:
        raise HTTPException(410, "session has already ended")

    if req.time_budget_seconds is not None:
        session.time_budget_seconds = req.time_budget_seconds

    text = step(session, req.text, client=CLIENT)
    response = TurnResponse(
        text=text,
        elapsed_seconds=session.elapsed(),
        time_budget_seconds=session.time_budget_seconds,
        interview_ended=session.ended,
        end_reason=session.end_reason,
    )
    # Persist the transcript every turn (overwrites the same deterministic
    # path keyed on session_id[:8] + started_at). Cheap insurance against
    # process loss mid-conversation.
    transcript_path = save_transcript(
        session_id,
        session.member_hint,
        session.started_at,
        session.messages,
        stage1=session.stage1,
    )
    response.transcript_path = str(transcript_path)
    # If the model called end_interview, auto-trigger reflector
    if session.ended:
        SESSIONS.pop(session_id, None)
        notes_path = await asyncio.to_thread(
            write_notes,
            session_id,
            session.member_hint,
            session.messages,
            transcript_path,
            stage1=session.stage1,
        )
        response.notes_path = str(notes_path)
    return response


def _sse(event: dict) -> str:
    """Format an event dict as a Server-Sent Event."""
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/sessions/{session_id}/turn-stream")
def turn_stream(session_id: str, req: TurnRequest):
    """Stream a participant turn as SSE.

    Events: text_delta, tool_use, tool_done, turn_done, error.
    The full turn is also persisted to the transcript when streaming completes.
    """
    if CLIENT is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set")
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    if session.ended:
        raise HTTPException(410, "session has already ended")

    def gen():
        saved = False
        try:
            for evt in step_stream(session, req.text, CLIENT, opening=False):
                yield _sse(evt)
            # After the streamed turn, persist transcript and (if ended) write notes.
            transcript_path = save_transcript(
                session_id,
                session.member_hint,
                session.started_at,
                session.messages,
                stage1=session.stage1,
            )
            saved = True
            yield _sse({"type": "transcript_saved", "path": str(transcript_path)})
            if session.ended:
                SESSIONS.pop(session_id, None)
                yield _sse({"type": "notes_writing"})
                notes_path = write_notes(
                    session_id,
                    session.member_hint,
                    session.messages,
                    transcript_path,
                    stage1=session.stage1,
                )
                yield _sse({"type": "notes_written", "path": str(notes_path)})
        except Exception as e:
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            # Guarantee a save even if the client disconnected mid-stream (which
            # raises GeneratorExit here and skips the happy-path save above).
            if not saved:
                _save_transcript_quietly(session)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/sessions/start-stream")
def start_stream(req: CreateSessionRequest):
    """Create a session AND stream the opening turn in one request.

    Events: session_created (first), then text_delta / tool_use / tool_done / turn_done.
    """
    if CLIENT is None:
        raise HTTPException(503, "ANTHROPIC_API_KEY not set")
    sid = uuid.uuid4().hex
    chosen_model = req.model or (MODEL_FAST if req.fast else MODEL_DEFAULT)
    session = Session(
        session_id=sid,
        member_hint=req.member_hint,
        model=chosen_model,
    )
    SESSIONS[sid] = session
    _apply_stage1(session, req)

    def gen():
        saved = False
        yield _sse({"type": "session_created", "session_id": sid})
        try:
            for evt in step_stream(session, None, CLIENT, opening=True):
                yield _sse(evt)
            transcript_path = save_transcript(
                sid,
                session.member_hint,
                session.started_at,
                session.messages,
                stage1=session.stage1,
            )
            saved = True
            yield _sse({"type": "transcript_saved", "path": str(transcript_path)})
        except Exception as e:
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            if not saved:
                _save_transcript_quietly(session)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/sessions/{session_id}/end", response_model=EndSessionResponse)
async def end_session(session_id: str):
    session = SESSIONS.pop(session_id, None)
    if not session:
        raise HTTPException(404, "session not found")
    session.ended = True
    if not session.end_reason:
        session.end_reason = "participant ended on their side"
    transcript_path = save_transcript(
        session_id,
        session.member_hint,
        session.started_at,
        session.messages,
        stage1=session.stage1,
    )
    # Run the reflector pass off the request thread so it doesn't block the response
    notes_path = await asyncio.to_thread(
        write_notes,
        session_id,
        session.member_hint,
        session.messages,
        transcript_path,
        stage1=session.stage1,
    )
    notes_content = ""
    try:
        notes_content = Path(notes_path).read_text(encoding="utf-8")
    except Exception:
        pass
    return EndSessionResponse(
        transcript_path=str(transcript_path),
        notes_path=str(notes_path),
        notes_content=notes_content,
        duration_seconds=session.elapsed(),
    )


@app.get("/sessions/{session_id}/notes", response_model=NotesResponse)
def get_notes(session_id: str):
    """Fetch the current notes file for a session — works after end."""
    notes_path = find_notes_path_for_session(session_id)
    if not notes_path:
        raise HTTPException(404, "no notes found for that session_id")
    draft_sibling = notes_path.with_suffix(".draft.md")
    return NotesResponse(
        notes_path=str(notes_path),
        notes_content=notes_path.read_text(encoding="utf-8"),
        has_been_edited=draft_sibling.exists(),
    )


@app.put("/sessions/{session_id}/notes", response_model=NotesResponse)
def put_notes(session_id: str, req: NotesUpdateRequest):
    """Replace the notes content with a participant-edited version.

    The first edit preserves the original auto-generated version as
    `<basename>.draft.md` so the original is never lost.
    """
    notes_path = find_notes_path_for_session(session_id)
    if not notes_path:
        raise HTTPException(404, "no notes found for that session_id")
    save_edited_notes(notes_path, req.content)
    draft_sibling = notes_path.with_suffix(".draft.md")
    return NotesResponse(
        notes_path=str(notes_path),
        notes_content=notes_path.read_text(encoding="utf-8"),
        has_been_edited=draft_sibling.exists(),
    )


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        raise HTTPException(404, "session not found")
    return {
        "session_id": session_id,
        "started_at": session.started_at,
        "elapsed_seconds": session.elapsed(),
        "time_budget_seconds": session.time_budget_seconds,
        "member_hint": session.member_hint,
        "n_messages": len(session.messages),
        "model": session.model,
    }


@app.post("/human-requests")
def human_request(req: HumanRequest):
    """Capture a 'screw ai, i want to talk to a human' handoff request.

    Writes one JSON file per request into server/human_requests/. Someone in
    the collective is expected to read this directory and follow up.
    """
    contact = (req.contact or "").strip()
    if not contact:
        raise HTTPException(400, "contact is required")
    HUMAN_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    rid = uuid.uuid4().hex[:8]
    payload = {
        "received_at": ts,
        "name": (req.name or "").strip() or None,
        "contact": contact,
        "note": (req.note or "").strip() or None,
    }
    (HUMAN_REQUESTS_DIR / f"{ts}_{rid}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"ok": True}


# ---- stale-session sweeper ------------------------------------------------


async def _sweep_idle_sessions():
    """Background task: drop+persist sessions that have been idle > IDLE_TIMEOUT_SECONDS."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            stale = [sid for sid, s in SESSIONS.items() if s.idle_seconds() > IDLE_TIMEOUT_SECONDS]
            for sid in stale:
                session = SESSIONS.pop(sid, None)
                if not session or not session.messages:
                    continue
                session.ended = True
                session.end_reason = session.end_reason or "idle timeout"
                try:
                    transcript_path = save_transcript(
                        sid,
                        session.member_hint,
                        session.started_at,
                        session.messages,
                        stage1=session.stage1,
                    )
                    await asyncio.to_thread(
                        write_notes,
                        sid,
                        session.member_hint,
                        session.messages,
                        transcript_path,
                        stage1=session.stage1,
                    )
                except Exception:
                    # Don't let one bad session kill the sweeper
                    pass
        except Exception:
            pass


@app.on_event("startup")
async def _start_sweeper():
    asyncio.create_task(_sweep_idle_sessions())


@app.get("/health")
def health():
    return {
        "ok": True,
        "anthropic_api_key": bool(ANTHROPIC_API_KEY),
        "active_sessions": len(SESSIONS),
    }
