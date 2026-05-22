"""Anthropic conversation loop with tool dispatching, time-aware injection,
and a small streaming surface.

The loop holds:
- the cached system block (system prompt + always-loaded wiki context)
- the conversation history (assistant + user turns)
- a tool-dispatching inner loop that runs until the model emits no tool_use
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Iterable

from anthropic import Anthropic

from config import (
    ANTHROPIC_API_KEY,
    MAX_TOKENS_PER_TURN,
    MAX_TOOL_TURNS,
    MODEL_DEFAULT,
    PROMPTS_DIR,
    WIKI_DIR,
)
from stage1 import render_breadth_map
from tools import END_INTERVIEW_TOOL, TOOL_SCHEMAS, UPDATE_TIME_BUDGET_TOOL, dispatch


# Tools the frontend gets to see (the wiki tools — informational, useful as
# "look what i'm doing" indicators). Operational tools (end_interview,
# update_time_budget) are NOT surfaced.
SURFACED_TOOLS = {"member", "search", "open", "open_many", "follow"}


def _humanize_tool_call(name: str, inp: dict) -> str:
    """Turn a tool call into a short verb-form sentence for the UI."""
    if name == "member":
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


NEWSLETTER_DIR = Path(__file__).parent / "newsletter_subscriptions"


def save_newsletter_subscription(session_id: str, payload: dict) -> Path:
    NEWSLETTER_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H-%M-%S")
    path = NEWSLETTER_DIR / f"{ts}_{session_id[:8]}.json"
    record = {
        "received_at": ts,
        "session_id": session_id,
        **payload,
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# -- always-loaded wiki context ---------------------------------------------
# These pages are short, broadly-useful, and worth paying the prompt-cache
# write-cost once. Everything else fetched on demand via tools.
ALWAYS_LOAD_WIKI_PAGES = [
    "index.md",
    "overview.md",
    "principles.md",
    "themes/identification-gaps.md",
    "themes/social-topology.md",
    "concepts/glossary.md",
    "open-questions.md",  # surface during interview when natural; capture positions in notes
]


def _build_system_prompt() -> list[dict]:
    """Return a list of system blocks with cache_control on the long ones.

    Anthropic prompt caching: marking the LAST block of a contiguous prefix
    with `cache_control: {"type": "ephemeral"}` caches everything up to that
    point.
    """
    main = (PROMPTS_DIR / "system.md").read_text(encoding="utf-8")

    wiki_chunks = []
    for rel in ALWAYS_LOAD_WIKI_PAGES:
        p = WIKI_DIR / rel
        if p.is_file():
            wiki_chunks.append(f"\n\n=== wiki/{rel} ===\n\n{p.read_text(encoding='utf-8')}")
    wiki_blob = (
        "\n\n# Always-loaded wiki context\n\nBelow is content from the wiki that's "
        "always in your prompt — you don't need to fetch it. Use the tools for everything else.\n"
        + "".join(wiki_chunks)
    )

    return [
        {"type": "text", "text": main},
        {"type": "text", "text": wiki_blob, "cache_control": {"type": "ephemeral"}},
    ]


# -- session state ----------------------------------------------------------


@dataclass
class Session:
    """One interview. Owns the conversation history + timing context."""
    session_id: str = ""  # set by app.py when the session is created
    started_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    time_budget_seconds: int | None = None  # set by user once they answer "how long"
    stage1: dict | None = None  # normalized stage-1 form answers, set at creation
    messages: list[dict] = field(default_factory=list)
    member_hint: str | None = None  # name/handle from frontend, optional
    model: str = MODEL_DEFAULT
    transcript_path: Path | None = None
    ended: bool = False  # set when end_interview tool is called or /end is hit
    end_reason: str | None = None  # populated by end_interview's `reason` arg

    def elapsed(self) -> int:
        return int(time.time() - self.started_at)

    def touch(self) -> None:
        """Mark the session as active right now (called on every turn)."""
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
        return (
            f"<time>elapsed={elapsed}s; budget={budget}s; remaining={remaining}s{flag}</time>"
        )


def _sanitize_user_text(text: str) -> str:
    """Strip <participant> tags from user input before re-wrapping ourselves.

    The model is told to treat content inside `<participant>` as data, not
    instructions. If a user includes literal `<participant>` tags in their
    message we strip them so they can't escape their own tag.
    """
    return text.replace("<participant>", "[participant]").replace("</participant>", "[/participant]")


def _wrap_user_message(session: Session, text: str, is_first: bool) -> dict:
    """Wrap participant text in <participant> tags + prepend time + first-turn hints."""
    safe = _sanitize_user_text(text)
    parts: list[str] = []
    parts.append(session.time_tag())
    if is_first and session.member_hint:
        parts.append(
            f"<hint>Frontend says they identified themselves as: {session.member_hint!r}. "
            "Quietly call `member()` with that to look them up.</hint>"
        )
    parts.append(f"<participant>{safe}</participant>")
    return {"role": "user", "content": "\n".join(parts)}


# The opening-turn instruction is long because it has to override several
# default model behaviors at once (don't ask substantive questions yet, do
# explain the format, do offer a ballpark time, do invite questions).
# Used by both the streaming and non-streaming opening paths.
_OPENING_INSTRUCTION = (
    "<system_event>The participant has just connected. No message yet. "
    "Compose your opening turn — short, warm, real. "
    "**Briefly explain what this is**, then ask how long they want to spend, "
    "BEFORE you get into anything substantive. The first turn has four parts, "
    "in roughly this order, in one short message: "
    "(a) a brief warm hello; "
    "(b) **a short explanation of what this is, what it's for, and what it'll "
    "involve** — frame it as a process, not as 'who I am'. Something like: "
    "this is a two-way interview the collective uses to get a real sense of "
    "what its members care about, what they want from it, and what they're "
    "worried about; it'll be a back-and-forth conversation grounded in what "
    "you've already shared (Discord, application, writings); afterwards, notes "
    "get written up that you can review and edit before anything is filed. "
    "Two-three sentences, concrete, no marketing tone. The participant should "
    "know what they're stepping into; "
    "(c) the time question with a recommended ballpark (*'how long do you want "
    "to spend? about 15-20 minutes is the usual length, but i'll check in there "
    "if you want to keep going.'*); "
    "(d) a small open invitation that they can ask you anything first — *'…or "
    "if there's anything you want to ask first — about this, the collective, "
    "anything — fire away.'* The invitation should feel genuinely open, not "
    "scoped to format/meta questions only — they may want to ask about a member, "
    "a project, what the collective even is, why we're doing this, whatever. "
    "If you don't already know from member(), you can also ask one quick "
    "familiarity question — but only if it doesn't bloat the message; the "
    "explanation + time + invitation are the priority. "
    "The concrete substantive question comes on the NEXT turn, once they've "
    "told you how long they have (and answered any questions they had). Don't "
    "pile a substantive question on top of the opening — it feels like pressure "
    "before they've even sat down. "
    "When you do get to the substantive opener (next turn, not this one), avoid "
    "two failure modes: (1) blank-canvas openers like 'this can be whatever's "
    "useful' / 'we can go wherever you want' / 'you steer' — they put all the "
    "structuring labor on the participant; (2) abstract self-survey openers like "
    "'what's most live for you?' / 'what's animating you?' / 'what's on your "
    "mind?' — they demand the participant introspect and hand over a thesis "
    "statement before the conversation has any warmth, like a job-interview "
    "*'tell me about yourself'* in disguise. Those abstract questions are fine "
    "*later*, once trust is established — just not as the opener. The substantive "
    "opener should be ONE concrete, externally-grounded question — anchored in "
    "something specific you can see (a recent thing they shipped, posted, or "
    "wrote about; a project on their member page) or (if they're fresh) the "
    "concrete fact of how they got here. If you can't think of anything specific, "
    "default to *'how did you find your way here?'* or *'have you been around "
    "the collective much, or is this your first proper look at it?'*. "
    "Keep this opening tight."
)


# Used when the participant completed the stage-1 form. The breadth map is
# injected separately (before this text). Key differences from the cold
# opener: do NOT re-ask the form items, and only ask about time if the time
# tag still says no budget is set (they skipped the time question).
_OPENING_INSTRUCTION_STAGE1 = (
    "<system_event>The participant has just connected and already filled out "
    "a short pre-interview form — the <stage1_breadth_map> above is their "
    "answers. Compose your opening turn — short, warm, real, in one message: "
    "(a) a brief warm hello; (b) one or two sentences on what this is (a "
    "two-way interview grounded in what they've shared; notes get written up "
    "afterwards that they can review and edit); (c) a small open invitation "
    "that they can ask you anything first. Then go straight into ONE concrete "
    "substantive opener that builds on the most alive thread in the breadth "
    "map — do NOT recite their answers back, do NOT re-ask the form "
    "questions, and do NOT ask 'what do you want to talk about'. "
    "About time: if the <time> tag above shows a budget, the participant "
    "already set their time in the form — do NOT ask how long they have. "
    "Only if the <time> tag says 'no budget set yet' should you fold the "
    "time question into this opening. Keep this opening tight."
)


def _opening_user_message(session: Session) -> dict:
    """Build the opening-turn user message.

    Cold (no stage 1): time tag + legacy opening instruction + member hint.
    Armed (stage 1 present): time tag + breadth map + stage-1 opening
    instruction + member hint.
    """
    hint = ""
    if session.member_hint:
        hint = (
            f"\n<hint>Frontend says they identified themselves as: {session.member_hint!r}. "
            "Quietly call `member()` with that to look them up before composing your opening.</hint>"
        )

    breadth_map = render_breadth_map(session.stage1)
    if breadth_map:
        instruction = _OPENING_INSTRUCTION_STAGE1
    else:
        instruction = _OPENING_INSTRUCTION

    parts = [session.time_tag()]
    if breadth_map:
        parts.append(breadth_map)
    parts.append(f"{instruction}{hint}</system_event>")
    return {"role": "user", "content": "\n".join(parts)}


# -- the loop ---------------------------------------------------------------


def _run_turn(client: Anthropic, session: Session, system: list[dict]) -> dict:
    """Run one model turn, including tool-use rounds, and return the final assistant message."""
    final_assistant: dict | None = None
    for turn in range(MAX_TOOL_TURNS):
        resp = client.messages.create(
            model=session.model,
            max_tokens=MAX_TOKENS_PER_TURN,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=session.messages,
        )
        # Append the assistant's response to history
        assistant_msg = {"role": "assistant", "content": resp.content}
        session.messages.append(assistant_msg)
        final_assistant = assistant_msg

        if resp.stop_reason != "tool_use":
            break

        # Collect tool_use blocks and dispatch them
        tool_results = []
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == END_INTERVIEW_TOOL:
                    session.ended = True
                    session.end_reason = (block.input or {}).get("reason", "")
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": (
                                "Interview marked as ended. The participant cannot receive "
                                "further messages from you. If your previous text already "
                                "said goodbye, output nothing more (an empty turn is fine). "
                                "If you didn't say goodbye yet, write one short final line "
                                "and stop."
                            ),
                        }
                    )
                elif block.name == UPDATE_TIME_BUDGET_TOOL:
                    inp = block.input or {}
                    try:
                        mins = float(inp.get("minutes_remaining", 0))
                    except (TypeError, ValueError):
                        mins = 0
                    if mins <= 0:
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": (
                                    "update_time_budget failed: minutes_remaining must "
                                    "be > 0. If they didn't give a real number, leave "
                                    "the budget unset and don't call this again until "
                                    "they do."
                                ),
                            }
                        )
                    else:
                        new_budget = session.elapsed() + int(mins * 60)
                        session.time_budget_seconds = new_budget
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": (
                                    f"Time budget updated. They now have {int(mins)} "
                                    f"more minute(s) from now (total budget = {new_budget}s "
                                    f"from session start). Acknowledge briefly and "
                                    "continue — don't make a ceremony of it."
                                ),
                            }
                        )
                else:
                    try:
                        output = dispatch(block.name, block.input or {})
                    except Exception as e:
                        output = f"tool {block.name} raised: {type(e).__name__}: {e}"
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": output,
                        }
                    )
        if tool_results:
            session.messages.append({"role": "user", "content": tool_results})
        else:
            break

    return final_assistant or {"role": "assistant", "content": []}


def _assistant_text(msg: dict) -> str:
    """Concatenate the text blocks of an assistant message."""
    parts = []
    for b in msg.get("content", []):
        if hasattr(b, "type") and b.type == "text":
            parts.append(b.text)
        elif isinstance(b, dict) and b.get("type") == "text":
            parts.append(b["text"])
    return "".join(parts)


def step(session: Session, user_text: str, client: Anthropic | None = None) -> str:
    """One human-facing turn: take user text, run the loop, return assistant text."""
    if client is None:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system = _build_system_prompt()
    is_first = len(session.messages) == 0
    session.messages.append(_wrap_user_message(session, user_text, is_first))
    msg = _run_turn(client, session, system)
    return _assistant_text(msg)


# -- streaming --------------------------------------------------------------


def _stream_one_round(client, session, system):
    """Stream one model round; yield event dicts and append the assistant
    message to the session. Returns the final message object so the caller
    can dispatch tools and decide whether to loop."""
    pending: dict[int, dict] = {}  # block index -> {id, name, input_text}

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
                    pending[event.index] = {
                        "id": block.id,
                        "name": block.name,
                        "input_text": "",
                    }
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
    """Run tool calls from a streamed assistant message; yield tool_done
    events for surfaced tools, and append the tool_results message to history.
    Returns True if we should loop again."""
    tool_results = []
    for block in final.content:
        if not (hasattr(block, "type") and block.type == "tool_use"):
            continue
        if block.name == END_INTERVIEW_TOOL:
            session.ended = True
            session.end_reason = (block.input or {}).get("reason", "")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": (
                    "Interview marked as ended. The participant cannot receive "
                    "further messages from you. If your previous text already "
                    "said goodbye, output nothing more (an empty turn is fine). "
                    "If you didn't say goodbye yet, write one short final line "
                    "and stop."
                ),
            })
        elif block.name == UPDATE_TIME_BUDGET_TOOL:
            inp = block.input or {}
            try:
                mins = float(inp.get("minutes_remaining", 0))
            except (TypeError, ValueError):
                mins = 0
            if mins <= 0:
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": "update_time_budget failed: minutes_remaining must be > 0.",
                })
            else:
                new_budget = session.elapsed() + int(mins * 60)
                session.time_budget_seconds = new_budget
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        f"Time budget updated. They now have {int(mins)} more minute(s) "
                        f"from now. Acknowledge briefly and continue."
                    ),
                })
        else:
            try:
                output = dispatch(block.name, block.input or {})
                ok = True
            except Exception as e:
                output = f"tool {block.name} raised: {type(e).__name__}: {e}"
                ok = False
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
            })
            if block.name in SURFACED_TOOLS:
                yield {"type": "tool_done", "id": block.id, "ok": ok}
    if tool_results:
        session.messages.append({"role": "user", "content": tool_results})
        return True
    return False


def step_stream(session: Session, user_text: str | None, client: Anthropic, *, opening: bool = False):
    """Generator: streams one participant turn (or the opening turn).

    Yields event dicts:
      {type: "text_delta", text: str}
      {type: "tool_use", id, name, label}
      {type: "tool_done", id, ok}
      {type: "turn_done", elapsed_seconds, time_budget_seconds, interview_ended,
                          end_reason}
      {type: "error", message}
    """
    session.touch()
    system = _build_system_prompt()
    if opening:
        session.messages.append(_opening_user_message(session))
    else:
        is_first = len(session.messages) == 0
        session.messages.append(_wrap_user_message(session, user_text or "", is_first))

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


def opening_turn(session: Session, client: Anthropic | None = None) -> str:
    """Generate the interviewer's opening turn — no user input yet."""
    if client is None:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system = _build_system_prompt()
    session.messages.append(_opening_user_message(session))
    msg = _run_turn(client, session, system)
    return _assistant_text(msg)
