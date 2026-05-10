"""Transcript saving + post-interview reflection (notes for the wiki)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY, MODEL_DEFAULT, NOTES_DIR, PROMPTS_DIR, TRANSCRIPTS_DIR


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s[:60] or "anon"


def find_notes_path_for_session(session_id: str) -> Path | None:
    """Locate the saved notes file for a session_id.

    Notes filenames are `{date}_{slug}_{session_id[:8]}.md`. The session_id[:8]
    suffix makes the lookup deterministic — no scan of transcripts needed.
    """
    if not session_id:
        return None
    suffix = session_id[:8]
    matches = list(NOTES_DIR.glob(f"*_{suffix}.md"))
    if matches:
        # Prefer the non-draft if both exist
        non_draft = [m for m in matches if not m.name.endswith(".draft.md")]
        return non_draft[0] if non_draft else matches[0]
    return None


def save_edited_notes(notes_path: Path, content: str) -> Path:
    """Replace `notes_path` with `content`, preserving the auto-generated draft alongside.

    The first time the participant edits, the original file is moved to `<basename>.draft.md`
    so the auto-generated version is preserved for audit. Subsequent edits overwrite the
    edited file but don't touch the draft.
    """
    notes_path = Path(notes_path)
    draft = notes_path.with_suffix(".draft.md")
    if not draft.exists() and notes_path.exists():
        draft.write_text(notes_path.read_text(), encoding="utf-8")
    notes_path.write_text(content, encoding="utf-8")
    return notes_path


def has_completed_interview_for(member_hint: str) -> bool:
    """True if a saved transcript exists for this member_hint (case/punct insensitive).

    Any transcript file in TRANSCRIPTS_DIR with a matching `member_hint` field counts —
    transcripts are only written when a session ends (via `end_interview` or `/end`),
    so existence implies completion.

    Used to enforce one-interview-per-member while we're early in the process.
    Empty hints (anonymous sessions) are not constrained.
    """
    if not member_hint:
        return False
    needle = _slug(member_hint)
    for f in TRANSCRIPTS_DIR.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        existing = d.get("member_hint")
        if existing and _slug(existing) == needle:
            return True
    return False


def _serialize_messages(messages: list[dict]) -> list[dict]:
    """Anthropic content blocks are SDK objects; serialize for JSON."""
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
    member_hint: str | None,
    started_at: float,
    messages: list[dict],
) -> Path:
    """Write the full conversation as JSON. Returns the path."""
    ts = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    slug = _slug(member_hint or "anon")
    path = TRANSCRIPTS_DIR / f"{ts}_{slug}_{session_id[:8]}.json"
    payload = {
        "session_id": session_id,
        "member_hint": member_hint,
        "started_at_iso": ts,
        "ended_at_iso": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "duration_seconds": int(time.time() - started_at),
        "messages": _serialize_messages(messages),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _flatten_for_reflector(messages: list[dict]) -> str:
    """Reduce conversation to plain text the reflector model can read efficiently."""
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
                # SDK objects
                t = getattr(b, "type", None) or (b.get("type") if isinstance(b, dict) else None)
                if t == "text":
                    chunks.append(getattr(b, "text", None) or b.get("text", ""))
                elif t == "tool_use":
                    name = getattr(b, "name", None) or b.get("name", "")
                    inp = getattr(b, "input", None) or b.get("input", {})
                    chunks.append(f"[tool_use: {name}({json.dumps(inp, ensure_ascii=False)})]")
                elif t == "tool_result":
                    # Tool results are bulky; truncate for reflector.
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
    "> Internal notes from an interview. **Ask the participant before quoting "
    "any of this publicly.**\n"
)


def write_notes(
    session_id: str,
    member_hint: str | None,
    messages: list[dict],
    transcript_path: Path,
) -> Path:
    """Run the reflector pass: read transcript, write structured wiki notes.

    Returns the path of the written notes file. Saves under server/notes/ —
    the human reviewer decides whether to copy into wiki/interviews/ and
    contacts the participant before quoting publicly.
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    notes_prompt = (PROMPTS_DIR / "notes.md").read_text(encoding="utf-8")
    transcript_text = _flatten_for_reflector(messages)
    if not transcript_text.strip():
        return _write_empty_note(session_id, member_hint, transcript_path, "transcript was empty")

    user_msg = (
        f"# Transcript\n\nsession_id: {session_id}\n"
        f"member_hint: {member_hint!r}\n"
        f"transcript_file: {transcript_path.name}\n"
        f"\n---\n\n{transcript_text}"
    )

    resp = client.messages.create(
        model=MODEL_DEFAULT,
        max_tokens=4000,
        system=[{"type": "text", "text": notes_prompt}],
        messages=[{"role": "user", "content": user_msg}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    slug = _slug(member_hint or "anon")
    # Include session_id[:8] in the filename so multiple interviews on the same
    # day with the same member_hint don't overwrite each other. Each interview
    # gets its own notes file.
    path = NOTES_DIR / f"{ts}_{slug}_{session_id[:8]}.md"
    path.write_text(NOTES_HEADER + "\n" + text, encoding="utf-8")
    return path


def _write_empty_note(session_id: str, member_hint: str | None, transcript_path: Path, reason: str) -> Path:
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    slug = _slug(member_hint or session_id[:8])
    path = NOTES_DIR / f"{ts}_{slug}.md"
    path.write_text(
        f"---\ntitle: \"Interview: {member_hint or session_id[:8]}, {ts}\"\n"
        f"type: interview\nsources:\n  - server/transcripts/{transcript_path.name}\n"
        f"last_updated: {ts}\n---\n\n# Skipped\n\n{reason}.\n",
        encoding="utf-8",
    )
    return path
