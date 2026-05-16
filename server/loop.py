"""Anthropic conversation loop: cached system block, tool dispatch, time-aware
injection, two-phase opening, and a streaming surface.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from anthropic import Anthropic

from config import (
    ANTHROPIC_API_KEY,
    MAX_TOKENS_PER_TURN,
    MAX_TOOL_TURNS,
    MODEL_DEFAULT,
    PROMPTS_DIR,
    WIKI_DIR,
)
from tools import (
    END_INTERVIEW_TOOL,
    TOOL_SCHEMAS,
    UPDATE_TIME_BUDGET_TOOL,
    dispatch,
)

# Wiki tools surfaced to the frontend as "look what i'm doing" indicators.
# Operational tools (end_interview, update_time_budget) are not surfaced.
SURFACED_TOOLS = {"participant", "search", "open", "open_many", "follow"}


def _humanize_tool_call(name: str, inp: dict) -> str:
    if name == "participant":
        target = (inp.get("name_or_handle") or "").strip() or "someone"
        return f"looking up {target}"
    if name == "search":
        q = (inp.get("query") or "").strip()
        return f'searching the wiki for "{q}"' if q else "searching the wiki"
    if name == "open":
        path = (inp.get("path") or "").strip().removesuffix(".md")
        return f"reading {path}" if path else "reading a wiki page"
    if name == "open_many":
        paths = inp.get("paths") or []
        n = len(paths)
        if n == 1:
            return f"reading {str(paths[0]).removesuffix('.md')}"
        return f"reading {n} wiki pages"
    if name == "follow":
        ref = (inp.get("reference") or "").strip()
        return f"following link to {ref}" if ref else "following a link"
    return f"calling {name}"


# -- always-loaded wiki context ---------------------------------------------
# Short, broadly-useful pages worth the one-time prompt-cache write cost.
# Everything else is a tool call away.
ALWAYS_LOAD_WIKI_PAGES = [
    "index.md",
    "overview.md",
    "cohort-portrait.md",
    "tree.md",
    "pods.md",
]


def _build_system_prompt() -> list[dict]:
    """System blocks with cache_control on the long (stable) suffix."""
    main = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")

    chunks = []
    for rel in ALWAYS_LOAD_WIKI_PAGES:
        p = WIKI_DIR / rel
        if p.is_file():
            chunks.append(f"\n\n=== wiki/{rel} ===\n\n{p.read_text(encoding='utf-8')}")
    wiki_blob = (
        "\n\n# Always-loaded wiki context\n\nThis content is always in your prompt — "
        "don't fetch it. Use the tools for everything else.\n" + "".join(chunks)
    )
    return [
        {"type": "text", "text": main},
        {"type": "text", "text": wiki_blob, "cache_control": {"type": "ephemeral"}},
    ]


# -- session state ----------------------------------------------------------

# Phase-1 form fields, in display order, with human labels for the context block.
PHASE1_FIELDS = [
    ("name", "Name / handle"),
    ("working_on", "What they're working on"),
    ("stuck_on", "What they're stuck on"),
    ("want_to_know", "What they want to know"),
]


@dataclass
class Session:
    session_id: str = ""
    started_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    time_budget_seconds: int | None = None
    messages: list[dict] = field(default_factory=list)
    participant_hint: str | None = None  # name/handle from phase 1, optional
    phase1: dict = field(default_factory=dict)  # raw phase-1 form answers
    model: str = MODEL_DEFAULT
    ended: bool = False
    end_reason: str | None = None

    def elapsed(self) -> int:
        return int(time.time() - self.started_at)

    def touch(self) -> None:
        self.last_activity_at = time.time()

    def idle_seconds(self) -> int:
        return int(time.time() - self.last_activity_at)

    def time_tag(self) -> str:
        elapsed = self.elapsed()
        budget = self.time_budget_seconds
        if budget is None:
            return f"<time>elapsed={elapsed}s; no budget set yet — ask them how long they have</time>"
        remaining = budget - elapsed
        ratio = elapsed / budget if budget > 0 else 0
        flag = ""
        if elapsed >= budget:
            flag = " — past their stated time; check in if you haven't recently"
        elif ratio >= 0.8:
            flag = " — ≥80% through; start steering toward what's most worth hitting"
        return f"<time>elapsed={elapsed}s; budget={budget}s; remaining={remaining}s{flag}</time>"

    def phase1_block(self) -> str:
        """Render the phase-1 form answers as a <phase1> context block.

        Only non-empty fields are included. If nothing was filled in, returns a
        marker so the model knows it's a cold open.
        """
        rows = []
        for key, label in PHASE1_FIELDS:
            val = (self.phase1.get(key) or "").strip()
            if val:
                rows.append(f"- {label}: {val}")
        if not rows:
            return (
                "<phase1>The participant skipped the entire intake form — no "
                "answers on file. Treat this as a cold open.</phase1>"
            )
        return (
            "<phase1>Before connecting, the participant filled in some of the "
            "optional intake form. Use this to open from substance — don't re-ask "
            "what they already told you:\n" + "\n".join(rows) + "</phase1>"
        )


def _sanitize_user_text(text: str) -> str:
    return text.replace("<participant>", "[participant]").replace("</participant>", "[/participant]")


def _wrap_user_message(session: Session, text: str) -> dict:
    safe = _sanitize_user_text(text)
    return {"role": "user", "content": f"{session.time_tag()}\n<participant>{safe}</participant>"}


_OPENING_INSTRUCTION = (
    "<system_event>The participant has just connected. No message from them yet. "
    "Compose your opening turn — short, warm, real. The phase-1 block above tells "
    "you what (if anything) they shared in the intake form.\n\n"
    "The opening has these parts, in one short message:\n"
    "(a) a brief warm hello;\n"
    "(b) **a short, concrete explanation of what this is**: a two-way conversation "
    "the AFFINE seminar uses to get a real sense of what its people care about, "
    "what they want to know, and what they're worried about regarding the future — "
    "grounded in what's already in the wiki (the concept tree, the cohort, the "
    "talks); afterwards notes get written that they can read and edit before "
    "anything is filed. Two-three sentences, no marketing tone;\n"
    "(c) if a time budget is NOT already set, the time question with a soft default "
    "(*'how long do you want — about 15-20 minutes is usual, but i'll check in there "
    "if it's still going.'*). If a budget IS already set (they gave it in the form), "
    "skip the time question entirely;\n"
    "(d) a genuinely open invitation that they can ask you anything first — about "
    "AFFINE, a person, a concept, a talk, why this is happening, anything.\n\n"
    "If the phase-1 block has content, **open from it**: react to the specific thing "
    "they're working on or stuck on or want to know, connect it to something concrete "
    "in the wiki if you can — but DON'T launch the deep substantive question yet, and "
    "DON'T read their form back to them like a checklist. The substantive thread "
    "develops on the NEXT turn, once they've responded and any questions they had are "
    "handled. If a name came through, you may quietly call participant() before "
    "composing this so your opening can be specific.\n\n"
    "If the phase-1 block says it was a cold open, don't fish for a thesis statement "
    "with abstract openers (*'what's most alive for you?'*). Keep it to (a)-(d) and "
    "let the first real question come next turn, anchored in something concrete.\n\n"
    "Keep the opening tight.</system_event>"
)


def _opening_user_message(session: Session) -> dict:
    return {
        "role": "user",
        "content": f"{session.phase1_block()}\n{session.time_tag()}\n{_OPENING_INSTRUCTION}",
    }


# -- tool dispatch shared by streaming + non-streaming ----------------------


def _handle_operational_or_dispatch(session: Session, block) -> tuple[dict, bool]:
    """Return (tool_result_block, is_surfaced_wiki_tool)."""
    if block.name == END_INTERVIEW_TOOL:
        session.ended = True
        session.end_reason = (block.input or {}).get("reason", "")
        return (
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": (
                    "Interview marked as ended. The participant cannot receive "
                    "further messages. If your previous text already said goodbye, "
                    "output nothing more (an empty turn is fine). If you didn't say "
                    "goodbye yet, write one short final line and stop."
                ),
            },
            False,
        )
    if block.name == UPDATE_TIME_BUDGET_TOOL:
        inp = block.input or {}
        try:
            mins = float(inp.get("minutes_remaining", 0))
        except (TypeError, ValueError):
            mins = 0
        if mins <= 0:
            return (
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        "update_time_budget failed: minutes_remaining must be > 0. "
                        "If they didn't give a real number, leave the budget unset."
                    ),
                },
                False,
            )
        new_budget = session.elapsed() + int(mins * 60)
        session.time_budget_seconds = new_budget
        return (
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": (
                    f"Time budget updated: {int(mins)} more minute(s) from now "
                    f"(total {new_budget}s from start). Acknowledge briefly, no ceremony."
                ),
            },
            False,
        )
    # Regular wiki tool
    try:
        output = dispatch(block.name, block.input or {})
    except Exception as e:
        output = f"tool {block.name} raised: {type(e).__name__}: {e}"
    return (
        {"type": "tool_result", "tool_use_id": block.id, "content": output},
        block.name in SURFACED_TOOLS,
    )


def _run_turn(client: Anthropic, session: Session, system: list[dict]) -> dict:
    final_assistant: dict | None = None
    for _ in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=session.model,
            max_tokens=MAX_TOKENS_PER_TURN,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=session.messages,
        )
        assistant_msg = {"role": "assistant", "content": resp.content}
        session.messages.append(assistant_msg)
        final_assistant = assistant_msg
        if resp.stop_reason != "tool_use":
            break
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                result, _ = _handle_operational_or_dispatch(session, block)
                tool_results.append(result)
        if tool_results:
            session.messages.append({"role": "user", "content": tool_results})
        else:
            break
    return final_assistant or {"role": "assistant", "content": []}


def _assistant_text(msg: dict) -> str:
    parts = []
    for b in msg.get("content", []):
        if hasattr(b, "type") and b.type == "text":
            parts.append(b.text)
        elif isinstance(b, dict) and b.get("type") == "text":
            parts.append(b["text"])
    return "".join(parts)


def step(session: Session, user_text: str, client: Anthropic | None = None) -> str:
    if client is None:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system = _build_system_prompt()
    session.messages.append(_wrap_user_message(session, user_text))
    return _assistant_text(_run_turn(client, session, system))


def opening_turn(session: Session, client: Anthropic | None = None) -> str:
    if client is None:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system = _build_system_prompt()
    session.messages.append(_opening_user_message(session))
    return _assistant_text(_run_turn(client, session, system))


# -- streaming --------------------------------------------------------------


def _stream_one_round(client, session, system):
    pending: dict[int, dict] = {}
    with client.messages.stream(
        model=session.model,
        max_tokens=MAX_TOKENS_PER_TURN,
        system=system,
        tools=TOOL_SCHEMAS,
        messages=session.messages,
    ) as stream:
        for event in stream:
            etype = getattr(event, "type", None)
            if etype == "content_block_start":
                block = event.content_block
                if getattr(block, "type", None) == "tool_use":
                    pending[event.index] = {"id": block.id, "name": block.name, "input_text": ""}
            elif etype == "content_block_delta":
                delta = event.delta
                dtype = getattr(delta, "type", None)
                if dtype == "text_delta":
                    yield {"type": "text_delta", "text": delta.text}
                elif dtype == "input_json_delta":
                    if event.index in pending:
                        pending[event.index]["input_text"] += delta.partial_json
            elif etype == "content_block_stop":
                if event.index in pending:
                    pt = pending.pop(event.index)
                    if pt["name"] in SURFACED_TOOLS:
                        try:
                            inp = json.loads(pt["input_text"]) if pt["input_text"] else {}
                        except Exception:
                            inp = {}
                        yield {
                            "type": "tool_use",
                            "id": pt["id"],
                            "name": pt["name"],
                            "label": _humanize_tool_call(pt["name"], inp),
                        }
        final = stream.get_final_message()
    session.messages.append({"role": "assistant", "content": final.content})
    return final


def _dispatch_tools_streamed(session, final):
    tool_results = []
    for block in final.content:
        if not (hasattr(block, "type") and block.type == "tool_use"):
            continue
        result, surfaced = _handle_operational_or_dispatch(session, block)
        tool_results.append(result)
        if surfaced:
            ok = not str(result.get("content", "")).startswith(f"tool {block.name} raised")
            yield {"type": "tool_done", "id": block.id, "ok": ok}
    if tool_results:
        session.messages.append({"role": "user", "content": tool_results})
        return True
    return False


def step_stream(session: Session, user_text: str | None, client: Anthropic, *, opening: bool = False):
    """Generator streaming one turn.

    Events: text_delta, tool_use, tool_done, turn_done, error.
    """
    session.touch()
    system = _build_system_prompt()
    if opening:
        session.messages.append(_opening_user_message(session))
    else:
        session.messages.append(_wrap_user_message(session, user_text or ""))

    try:
        for _ in range(MAX_TOOL_TURNS):
            final = yield from _stream_one_round(client, session, system)
            if final.stop_reason != "tool_use":
                break
            looped = yield from _dispatch_tools_streamed(session, final)
            if not looped:
                break
    except Exception as e:
        yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
        return

    yield {
        "type": "turn_done",
        "elapsed_seconds": session.elapsed(),
        "time_budget_seconds": session.time_budget_seconds,
        "interview_ended": session.ended,
        "end_reason": session.end_reason,
    }
