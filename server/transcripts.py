"""Transcript saving + post-interview reflection (notes the participant edits)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, MODEL_DEFAULT, NOTES_DIR, PROMPTS_DIR, TRANSCRIPTS_DIR


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (s or "").lower()).strip("-")
    return s[:60] or "anon"


def find_notes_path_for_session(session_id: str) -> Path | None:
    """Locate the saved notes file for a session_id (filename carries id[:8])."""
    if not session_id:
        return None
    matches = list(NOTES_DIR.glob(f"*_{session_id[:8]}.md"))
    if matches:
        non_draft = [m for m in matches if not m.name.endswith(".draft.md")]
        return non_draft[0] if non_draft else matches[0]
    return None


def save_edited_notes(notes_path: Path, content: str) -> Path:
    """Replace notes with participant's edit; preserve the auto-generated draft once."""
    notes_path = Path(notes_path)
    draft = notes_path.with_suffix(".draft.md")
    if not draft.exists() and notes_path.exists():
        draft.write_text(notes_path.read_text(encoding="utf-8"), encoding="utf-8")
    notes_path.write_text(content, encoding="utf-8")
    return notes_path


def _serialize_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        blocks = []
        for b in content:
            if hasattr(b, "model_dump"):
                blocks.append(b.model_dump())
            elif isinstance(b, dict):
                blocks.append(b)
            else:
                blocks.append({"type": "unknown", "repr": repr(b)})
        out.append({"role": m["role"], "content": blocks})
    return out


def save_transcript(
    session_id: str,
    participant_hint: str | None,
    started_at: float,
    messages: list[dict],
    phase1: dict | None = None,
) -> Path:
    ts = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    slug = _slug(participant_hint or "anon")
    path = TRANSCRIPTS_DIR / f"{ts}_{slug}_{session_id[:8]}.json"
    payload = {
        "session_id": session_id,
        "participant_hint": participant_hint,
        "phase1": phase1 or {},
        "started_at_iso": ts,
        "ended_at_iso": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "duration_seconds": int(time.time() - started_at),
        "messages": _serialize_messages(messages),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _flatten_for_reflector(messages: list[dict]) -> str:
    out = []
    turn = 0
    for m in messages:
        turn += 1
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            text = content
        else:
            chunks = []
            for b in content:
                t = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
                if t == "text":
                    chunks.append(getattr(b, "text", None) or b.get("text", ""))
                elif t == "tool_use":
                    name = getattr(b, "name", None) or b.get("name", "")
                    inp = getattr(b, "input", None) or b.get("input", {})
                    chunks.append(f"[tool_use: {name}({json.dumps(inp, ensure_ascii=False)})]")
                elif t == "tool_result":
                    raw = b.get("content", "") if isinstance(b, dict) else ""
                    if isinstance(raw, list):
                        raw = " ".join(str(r) for r in raw)
                    snippet = (raw[:300] + "…") if len(raw) > 300 else raw
                    chunks.append(f"[tool_result: {snippet}]")
            text = " ".join(chunks).strip()
        if not text:
            continue
        out.append(f"=== turn {turn} [{role}] ===\n{text}")
    return "\n\n".join(out)


NOTES_HEADER = (
    "> Internal notes from an AFFINE interview. **Ask the participant before "
    "quoting any of this publicly.**\n"
)


def write_notes(
    session_id: str,
    participant_hint: str | None,
    messages: list[dict],
    transcript_path: Path,
    phase1: dict | None = None,
) -> Path:
    """Reflector pass: read transcript, write structured notes for participant review."""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    notes_prompt = (PROMPTS_DIR / "notes.md").read_text(encoding="utf-8")
    transcript_text = _flatten_for_reflector(messages)
    if not transcript_text.strip():
        return _write_empty_note(session_id, participant_hint, transcript_path, "transcript was empty")

    phase1_str = ""
    if phase1:
        kept = {k: v for k, v in phase1.items() if (v or "").strip()}
        if kept:
            phase1_str = "\nphase1_form: " + json.dumps(kept, ensure_ascii=False)

    user_msg = (
        f"# Transcript\n\nsession_id: {session_id}\n"
        f"participant_hint: {participant_hint!r}{phase1_str}\n"
        f"transcript_file: {transcript_path.name}\n\n---\n\n{transcript_text}"
    )

    resp = client.messages.create(
        model=MODEL_DEFAULT,
        max_tokens=4000,
        system=[{"type": "text", "text": notes_prompt}],
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    slug = _slug(participant_hint or "anon")
    path = NOTES_DIR / f"{ts}_{slug}_{session_id[:8]}.md"
    path.write_text(NOTES_HEADER + "\n" + text, encoding="utf-8")
    return path


def _write_empty_note(session_id, participant_hint, transcript_path, reason) -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    slug = _slug(participant_hint or session_id[:8])
    path = NOTES_DIR / f"{ts}_{slug}_{session_id[:8]}.md"
    path.write_text(
        f'---\ntitle: "Interview: {participant_hint or session_id[:8]}, {ts}"\n'
        f"type: interview\nsources:\n  - server/transcripts/{transcript_path.name}\n"
        f"last_updated: {ts}\n---\n\n# Skipped\n\n{reason}.\n",
        encoding="utf-8",
    )
    return path
