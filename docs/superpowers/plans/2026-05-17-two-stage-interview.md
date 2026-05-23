# Two-Stage Interview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a short optional pre-interview form (stage 1) whose answers arm the existing conversational interview (stage 2), so the interviewer stops tunnelling into the first topic and the value/criticism/ideas/involvement/newsletter data is captured even from people who never finish stage 2.

**Architecture:** Stage-1 answers are threaded through the existing session-creating `/sessions/start-stream` call (no separate endpoint, no orphan session). A new pure module `server/stage1.py` normalizes the payload, derives the time budget, renders a breadth-map block, and builds the newsletter record. The breadth map is injected into the opening-turn user message; a stage-1-aware opening instruction tells the model not to re-ask the form, not to re-ask time when a budget is set, and to open hot on the map. The newsletter tool is removed from stage 2. The reflector and transcript persist the stage-1 block; `notes.md` gains an `## Ideas proposed` section.

**Tech Stack:** Python 3.12, FastAPI, Anthropic SDK, Pydantic v2, `uv` (server); SvelteKit + Svelte 5 runes + TypeScript (`/root/idealists-site` frontend). Tests: `pytest` via `uv` (new dev dep) for the pure server logic; `npm run check` for the frontend.

**Branches:** server work on `two-stage-interview` (already checked out in `/root/interviewer`). Frontend work on a new branch `two-stage-interview-form` in `/root/idealists-site` (separate from `mobile-enter-newline`).

**Scope note:** The notes-pipeline reliability bug (~28% garbage reflector output) is explicitly out of scope per the spec; it is a separate plan. This plan only adds the stage-1 ingestion hook to the reflector input.

---

## File Structure

**Create:**
- `server/stage1.py` — pure helpers: `normalize_stage1`, `time_choice_to_budget_seconds`, `render_breadth_map`, `format_stage1_for_notes`, `newsletter_payload`. No I/O, no network — fully unit-testable.
- `server/tests/__init__.py` — empty, makes `tests` a package.
- `server/tests/test_stage1.py` — unit tests for `stage1.py`.

**Modify:**
- `server/pyproject.toml` — add `pytest` dev dependency.
- `server/loop.py` — `Session.stage1` field; rename `_save_newsletter_subscription` → `save_newsletter_subscription`; remove `NEWSLETTER_TOOL` import + both newsletter tool-handler branches; stage-1-aware opening message.
- `server/tools.py` — remove the `capture_newsletter_preference` schema and the `NEWSLETTER_TOOL` constant.
- `server/app.py` — `Stage1Payload` model + `stage1` field on `CreateSessionRequest`; apply stage-1 at session creation in `/sessions` and `/sessions/start-stream`; pass `session.stage1` to `save_transcript`/`write_notes`.
- `server/transcripts.py` — `save_transcript` and `write_notes` accept + persist/feed `stage1`.
- `server/prompts/system.md` — remove the Personalised-newsletters section, the arc's newsletter step, simplify the close, adjust the Time section.
- `server/prompts/notes.md` — ingest the stage-1 block; add `## Ideas proposed`.
- `questions.md` — document the stage-1 form.
- `/root/idealists-site/src/lib/interviewer-client.ts` — `Stage1` interface; `stage1` on `CreateSessionRequest`.
- `/root/idealists-site/src/routes/interview/+page.svelte` — `'form'` phase, form UI, flow.

---

## Task 1: Stage-1 pure helpers — normalize + time budget

**Files:**
- Create: `server/stage1.py`
- Create: `server/tests/__init__.py`
- Create: `server/tests/test_stage1.py`
- Modify: `server/pyproject.toml`

- [ ] **Step 1: Add pytest dev dependency**

Run (from `/root/interviewer/server`):

```bash
uv add --dev pytest
```

Expected: `pyproject.toml` gains a `[dependency-groups]` (or `[tool.uv]`) entry with `pytest`; `uv.lock` updates; exit 0.

- [ ] **Step 2: Create the tests package marker**

Create `server/tests/__init__.py` with exactly:

```python
```

(empty file)

- [ ] **Step 3: Write the failing tests for normalize + time budget**

Create `server/tests/test_stage1.py`:

```python
from stage1 import normalize_stage1, time_choice_to_budget_seconds


def test_normalize_empty_returns_none():
    assert normalize_stage1(None) is None
    assert normalize_stage1({}) is None
    assert normalize_stage1(
        {"value": "  ", "falling_short": "", "ideas": None, "involvement": "\n"}
    ) is None


def test_normalize_strips_and_keeps_present_fields():
    out = normalize_stage1(
        {
            "value": "  the people  ",
            "falling_short": "too much talk",
            "ideas": "",
            "involvement": None,
            "time_minutes": 20,
            "no_time_limit": False,
            "newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": "  "},
        }
    )
    assert out == {
        "value": "the people",
        "falling_short": "too much talk",
        "ideas": None,
        "involvement": None,
        "time_minutes": 20,
        "no_time_limit": False,
        "newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": None},
    }


def test_normalize_no_time_limit_alone_is_not_empty():
    out = normalize_stage1({"no_time_limit": True})
    assert out is not None
    assert out["no_time_limit"] is True
    assert out["time_minutes"] is None


def test_normalize_newsletter_without_email_is_dropped():
    out = normalize_stage1({"value": "x", "newsletter": {"email": "  ", "frequency": "weekly"}})
    assert out is not None
    assert out["newsletter"] is None


def test_normalize_bad_time_minutes_becomes_none():
    assert normalize_stage1({"value": "x", "time_minutes": "abc"})["time_minutes"] is None
    assert normalize_stage1({"value": "x", "time_minutes": -5})["time_minutes"] is None
    assert normalize_stage1({"value": "x", "time_minutes": 0})["time_minutes"] is None


def test_time_choice_to_budget_seconds():
    assert time_choice_to_budget_seconds(None) is None
    assert time_choice_to_budget_seconds({"time_minutes": None, "no_time_limit": True}) is None
    assert time_choice_to_budget_seconds({"time_minutes": None, "no_time_limit": False}) is None
    assert time_choice_to_budget_seconds({"time_minutes": 20, "no_time_limit": False}) == 1200
```

- [ ] **Step 4: Run the tests to verify they fail**

Run (from `/root/interviewer/server`):

```bash
uv run pytest tests/test_stage1.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'stage1'`.

- [ ] **Step 5: Implement `stage1.py` (normalize + time budget only)**

Create `server/stage1.py`:

```python
"""Pure helpers for the stage-1 pre-interview form.

No I/O, no network — everything here is deterministic and unit-tested.
The canonical normalized shape is:

    {
        "value": str | None,            # what they value about the collective
        "falling_short": str | None,    # where we're falling short
        "ideas": str | None,            # ideas / things they wish existed
        "involvement": str | None,      # whether/how they want to get involved
        "time_minutes": int | None,     # explicit minutes; None if no limit / skipped
        "no_time_limit": bool,          # True iff they explicitly chose "no fixed limit"
        "newsletter": {                 # None unless they gave at least an email
            "email": str | None,
            "frequency": str | None,
            "interested_in": str | None,
        } | None,
    }

`normalize_stage1` returns None when the participant supplied nothing at all
(form skipped) so callers can treat "no stage 1" uniformly.
"""
from __future__ import annotations

TEXT_FIELDS = ("value", "falling_short", "ideas", "involvement")


def _clean(v) -> str | None:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _coerce_minutes(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def normalize_stage1(raw: dict | None) -> dict | None:
    """Clean a raw stage-1 payload into the canonical shape, or None if empty."""
    if not raw:
        return None

    text = {f: _clean(raw.get(f)) for f in TEXT_FIELDS}
    time_minutes = _coerce_minutes(raw.get("time_minutes"))
    no_time_limit = bool(raw.get("no_time_limit"))

    newsletter = None
    nl = raw.get("newsletter")
    if isinstance(nl, dict):
        email = _clean(nl.get("email"))
        if email:  # an email is the minimum to record a subscription
            newsletter = {
                "email": email,
                "frequency": _clean(nl.get("frequency")),
                "interested_in": _clean(nl.get("interested_in")),
            }

    out = {
        **text,
        "time_minutes": time_minutes,
        "no_time_limit": no_time_limit,
        "newsletter": newsletter,
    }

    # "Empty" = nothing the participant actually chose. no_time_limit=True is a
    # real choice and must survive even if every other field is blank.
    if (
        all(out[f] is None for f in TEXT_FIELDS)
        and time_minutes is None
        and not no_time_limit
        and newsletter is None
    ):
        return None
    return out


def time_choice_to_budget_seconds(stage1: dict | None) -> int | None:
    """Minutes → seconds for the session time budget, or None (no limit / skipped)."""
    if not stage1:
        return None
    mins = stage1.get("time_minutes")
    if isinstance(mins, int) and mins > 0:
        return mins * 60
    return None
```

- [ ] **Step 6: Run the tests to verify they pass**

Run:

```bash
uv run pytest tests/test_stage1.py -q
```

Expected: PASS (7 passed).

- [ ] **Step 7: Commit**

```bash
cd /root/interviewer
git config user.name "Samuel Ratnam" && git config user.email "samueljratnam@gmail.com"
git add server/stage1.py server/tests/__init__.py server/tests/test_stage1.py server/pyproject.toml server/uv.lock
git commit -m "stage1: normalize + time-budget helpers" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(If the commit is blocked by the identity guardrail, stop and hand the exact command to the user, then continue with the next task — do not fight the guardrail.)

---

## Task 2: Stage-1 pure helpers — breadth map, notes block, newsletter payload

**Files:**
- Modify: `server/stage1.py`
- Modify: `server/tests/test_stage1.py`

- [ ] **Step 1: Add failing tests**

Append to `server/tests/test_stage1.py`:

```python
from stage1 import render_breadth_map, format_stage1_for_notes, newsletter_payload


def test_render_breadth_map_empty():
    assert render_breadth_map(None) == ""
    assert render_breadth_map(
        {"value": None, "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": 30, "no_time_limit": False,
         "newsletter": None}
    ) == ""


def test_render_breadth_map_includes_only_present_fields():
    bm = render_breadth_map(
        {"value": "the people", "falling_short": None, "ideas": "a book club",
         "involvement": None, "time_minutes": None, "no_time_limit": False,
         "newsletter": {"email": "a@b.com", "frequency": None, "interested_in": None}}
    )
    assert bm.startswith("<stage1_breadth_map>")
    assert bm.rstrip().endswith("</stage1_breadth_map>")
    assert "the people" in bm
    assert "a book club" in bm
    assert "falling short" not in bm.lower()  # skipped field omitted
    assert "newsletter" in bm.lower()          # tells stage 2 not to re-ask it


def test_format_stage1_for_notes_plain_block():
    s = format_stage1_for_notes(
        {"value": "x", "falling_short": "y", "ideas": None,
         "involvement": "maybe events", "time_minutes": 20,
         "no_time_limit": False, "newsletter": {"email": "a@b.com",
         "frequency": "weekly", "interested_in": None}}
    )
    assert "# Stage 1 form" in s
    assert "x" in s and "y" in s and "maybe events" in s
    assert format_stage1_for_notes(None) == ""


def test_newsletter_payload():
    assert newsletter_payload(None) is None
    assert newsletter_payload({"newsletter": None}) is None
    assert newsletter_payload(
        {"newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": None}}
    ) == {
        "email": "a@b.com",
        "frequency": "weekly",
        "interested_in": None,
        "source": "stage1_form",
    }
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_stage1.py -q
```

Expected: FAIL — `ImportError: cannot import name 'render_breadth_map'`.

- [ ] **Step 3: Implement the three functions**

Append to `server/stage1.py`:

```python
_MAP_FIELDS = (
    ("value", "What they value about the collective"),
    ("falling_short", "Where they think we're falling short"),
    ("ideas", "Ideas / things they wish existed"),
    ("involvement", "Whether / how they want to get more involved"),
)

_MAP_PREAMBLE = (
    "The participant filled out a short pre-interview form. This is your "
    "breadth map. Do NOT re-ask these cold. Open hot on whatever is most "
    "alive here and follow your curiosity across threads — one deep vein or "
    "many, your call. The failure mode this map exists to prevent is "
    "tunnelling into the first topic and never achieving breadth. A blank "
    "field means they skipped it; absence is a signal, not a prompt to "
    "interrogate."
)


def render_breadth_map(stage1: dict | None) -> str:
    """The <stage1_breadth_map> block injected into stage 2's opening turn.

    Returns "" when there is nothing substantive to show (the time-only or
    skipped case) so the caller can fall back to the legacy opener.
    """
    if not stage1:
        return ""
    lines = []
    for key, label in _MAP_FIELDS:
        val = stage1.get(key)
        if val:
            lines.append(f'- {label}: "{val}"')
    has_newsletter = bool(stage1.get("newsletter"))
    if not lines and not has_newsletter:
        return ""
    if has_newsletter:
        lines.append(
            "- Newsletter: already captured via the form — do NOT ask about "
            "the newsletter in the conversation."
        )
    body = "\n".join(lines)
    return f"<stage1_breadth_map>\n{_MAP_PREAMBLE}\n\n{body}\n</stage1_breadth_map>"


def format_stage1_for_notes(stage1: dict | None) -> str:
    """A plain (non-instructional) block prepended to the reflector input."""
    if not stage1:
        return ""
    lines = ["# Stage 1 form", ""]
    for key, label in _MAP_FIELDS:
        val = stage1.get(key)
        lines.append(f"- {label}: {val if val else '(skipped)'}")
    nl = stage1.get("newsletter")
    if nl:
        lines.append(
            f"- Newsletter: email={nl.get('email')}, "
            f"frequency={nl.get('frequency')}, "
            f"interested_in={nl.get('interested_in')} "
            "(captured via form, not the conversation)"
        )
    return "\n".join(lines)


def newsletter_payload(stage1: dict | None) -> dict | None:
    """The record body for an existing-format newsletter subscription, or None."""
    if not stage1:
        return None
    nl = stage1.get("newsletter")
    if not nl:
        return None
    return {
        "email": nl.get("email"),
        "frequency": nl.get("frequency"),
        "interested_in": nl.get("interested_in"),
        "source": "stage1_form",
    }
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_stage1.py -q
```

Expected: PASS (11 passed).

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer
git add server/stage1.py server/tests/test_stage1.py
git commit -m "stage1: breadth-map, notes block, newsletter payload" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Remove the newsletter tool from stage 2

**Files:**
- Modify: `server/tools.py:144-168` (delete the `capture_newsletter_preference` schema), `server/tools.py:173` (delete the constant)
- Modify: `server/loop.py:27` (import), `server/loop.py:62` (rename function), `server/loop.py:327-367` and `server/loop.py:509-536` (delete newsletter branches)

- [ ] **Step 1: Delete the newsletter tool schema**

In `server/tools.py`, delete the entire dict element (the block that starts with `{` on the line after `},` at line 143 and ends with `},` at line 168):

```python
    {
        "name": "capture_newsletter_preference",
        "description": (
            "Capture a participant's interest in a personalised newsletter from the "
            ... (entire block) ...
            "required": ["email", "frequency", "interested_in"],
        },
    },
```

So `TOOL_SCHEMAS` ends with the `update_time_budget` schema followed immediately by the closing `]`.

- [ ] **Step 2: Delete the NEWSLETTER_TOOL constant**

In `server/tools.py`, delete this line:

```python
NEWSLETTER_TOOL = "capture_newsletter_preference"
```

Leave `END_INTERVIEW_TOOL` and `UPDATE_TIME_BUDGET_TOOL`.

- [ ] **Step 3: Fix the loop.py import**

In `server/loop.py` line 27, change:

```python
from tools import END_INTERVIEW_TOOL, NEWSLETTER_TOOL, TOOL_SCHEMAS, UPDATE_TIME_BUDGET_TOOL, dispatch
```

to:

```python
from tools import END_INTERVIEW_TOOL, TOOL_SCHEMAS, UPDATE_TIME_BUDGET_TOOL, dispatch
```

- [ ] **Step 4: Make the newsletter saver public**

In `server/loop.py`, rename `_save_newsletter_subscription` to `save_newsletter_subscription` (definition at line 62). It is now called only from `app.py` (the tool branches are deleted next).

```python
def save_newsletter_subscription(session_id: str, payload: dict) -> Path:
```

- [ ] **Step 5: Delete the newsletter branch in `_run_turn`**

In `server/loop.py`, delete the entire `elif block.name == NEWSLETTER_TOOL:` branch inside `_run_turn` (the block spanning roughly lines 327–367, from `elif block.name == NEWSLETTER_TOOL:` up to but not including the following `else:`). After deletion the `UPDATE_TIME_BUDGET_TOOL` branch is followed directly by the generic `else:` dispatch branch.

- [ ] **Step 6: Delete the newsletter branch in `_dispatch_tools_streamed`**

In `server/loop.py`, delete the entire `elif block.name == NEWSLETTER_TOOL:` branch inside `_dispatch_tools_streamed` (roughly lines 509–536), so the `UPDATE_TIME_BUDGET_TOOL` branch is followed directly by the generic `else:`.

- [ ] **Step 7: Verify the module imports cleanly**

Run (from `/root/interviewer/server`):

```bash
uv run python -c "import tools, loop; print('NEWSLETTER_TOOL' not in dir(tools)); print(hasattr(loop, 'save_newsletter_subscription'))"
```

Expected: prints `True` then `True`, exit 0, no ImportError.

- [ ] **Step 8: Commit**

```bash
cd /root/interviewer
git add server/tools.py server/loop.py
git commit -m "stage2: remove capture_newsletter_preference tool (moves to stage-1 form)" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Session field + stage-1-aware opening message

**Files:**
- Modify: `server/loop.py:124` area (add `stage1` field), `server/loop.py:237-248` (`_opening_user_message`)

- [ ] **Step 1: Add the `stage1` field to `Session`**

In `server/loop.py`, in the `Session` dataclass, add after the `time_budget_seconds` field (line ~124):

```python
    stage1: dict | None = None  # normalized stage-1 form answers, set at creation
```

- [ ] **Step 2: Add the stage-1 opening instruction constant**

In `server/loop.py`, immediately after the `_OPENING_INSTRUCTION = (...)` definition (after line 234), add:

```python
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
```

- [ ] **Step 3: Rewrite `_opening_user_message` to use the breadth map**

In `server/loop.py`, replace the whole `_opening_user_message` function (lines ~237-248) with:

```python
def _opening_user_message(session: Session) -> dict:
    """Build the opening-turn user message.

    Cold (no stage 1): time tag + legacy opening instruction + member hint.
    Armed (stage 1 present): time tag + breadth map + stage-1 opening
    instruction + member hint.
    """
    from stage1 import render_breadth_map

    hint = ""
    if session.member_hint:
        hint = (
            f"\n<hint>Frontend says they identified themselves as: {session.member_hint!r}. "
            "Quietly call `member()` with that to look them up before composing your opening.</hint>"
        )

    breadth_map = render_breadth_map(session.stage1)
    if session.stage1 is not None:
        instruction = _OPENING_INSTRUCTION_STAGE1
    else:
        instruction = _OPENING_INSTRUCTION

    parts = [session.time_tag()]
    if breadth_map:
        parts.append(breadth_map)
    parts.append(f"{instruction}{hint}</system_event>")
    return {"role": "user", "content": "\n".join(parts)}
```

Note: both `_OPENING_INSTRUCTION` and `_OPENING_INSTRUCTION_STAGE1` begin with `<system_event>` and this function appends the closing `</system_event>` exactly as the original did — unchanged framing for the cold path.

- [ ] **Step 4: Smoke-check the opening message builder (no network)**

Run (from `/root/interviewer/server`):

```bash
uv run python -c "
from loop import Session, _opening_user_message
s = Session(session_id='x'*32)
print('COLD:', 'stage1_breadth_map' not in _opening_user_message(s)['content'])
s.stage1 = {'value':'the people','falling_short':None,'ideas':None,'involvement':None,'time_minutes':20,'no_time_limit':False,'newsletter':None}
s.time_budget_seconds = 1200
m = _opening_user_message(s)['content']
print('ARMED map:', 'stage1_breadth_map' in m)
print('ARMED instr:', 'already filled out' in m)
print('ENDS TAG:', m.rstrip().endswith('</system_event>'))
"
```

Expected: `COLD: True`, `ARMED map: True`, `ARMED instr: True`, `ENDS TAG: True`.

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer
git add server/loop.py
git commit -m "stage2: inject stage-1 breadth map into the opening turn" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Wire stage 1 into session creation (app.py)

**Files:**
- Modify: `server/app.py` — request model, `create_session`, `start_stream`, transcript/notes call sites

- [ ] **Step 1: Add the request model and imports**

In `server/app.py`, update the imports near line 30:

```python
from loop import Session, opening_turn, step, step_stream, save_newsletter_subscription
from stage1 import normalize_stage1, time_choice_to_budget_seconds, newsletter_payload
```

Then add a `Stage1Payload` model and a `stage1` field on `CreateSessionRequest` (replace the existing `CreateSessionRequest` class at lines 62-74):

```python
class Stage1Newsletter(BaseModel):
    email: Optional[str] = None
    frequency: Optional[str] = None
    interested_in: Optional[str] = None


class Stage1Payload(BaseModel):
    value: Optional[str] = None
    falling_short: Optional[str] = None
    ideas: Optional[str] = None
    involvement: Optional[str] = None
    time_minutes: Optional[int] = None
    no_time_limit: bool = False
    newsletter: Optional[Stage1Newsletter] = None


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
```

- [ ] **Step 2: Add a shared apply-stage-1 helper**

In `server/app.py`, add this function just above `@app.post("/sessions", ...)` (before line 129):

```python
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
        save_newsletter_subscription(
            session.session_id, {**np, "member_hint": session.member_hint}
        )
```

- [ ] **Step 3: Call it in `create_session`**

In `server/app.py` `create_session` (lines ~129-142), after `SESSIONS[sid] = session` and before `text = opening_turn(...)`, insert:

```python
    _apply_stage1(session, req)
```

Then change the `save_transcript` is not called here (create_session doesn't persist) — no further change in this function.

- [ ] **Step 4: Call it in `start_stream`**

In `server/app.py` `start_stream` (lines ~246-286), after `SESSIONS[sid] = session` and before `def gen():`, insert:

```python
    _apply_stage1(session, req)
```

- [ ] **Step 5: Pass `session.stage1` to every `save_transcript` and `write_notes` call**

In `server/app.py`, update all `save_transcript(...)` calls to pass `stage1=session.stage1` and all `write_notes(...)` calls to pass `stage1=session.stage1`. There are `save_transcript` calls in `turn` (~169), `turn_stream` gen (~215), `start_stream` gen (~268), `end_session` (~297), `_sweep_idle_sessions` (~415); and `write_notes` calls in `turn` (~179), `turn_stream` gen (~225), `end_session` (~304), `_sweep_idle_sessions` (~418). Each becomes e.g.:

```python
        transcript_path = save_transcript(
            session_id,
            session.member_hint,
            session.started_at,
            session.messages,
            stage1=session.stage1,
        )
```

and

```python
        notes_path = write_notes(
            session_id,
            session.member_hint,
            session.messages,
            transcript_path,
            stage1=session.stage1,
        )
```

(`save_transcript`/`write_notes` gain these keyword params in Task 6; adding the kwargs here first is fine because Task 6 lands before any run.)

- [ ] **Step 6: Verify app imports**

Run (from `/root/interviewer/server`):

```bash
uv run python -c "import app; print('ok')"
```

Expected: prints `ok` (no API key needed for import; `CLIENT` is None and that's fine).

- [ ] **Step 7: Commit**

```bash
cd /root/interviewer
git add server/app.py
git commit -m "stage1: apply form answers at session creation (budget + newsletter + map)" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Persist stage 1 in the transcript and feed it to the reflector

**Files:**
- Modify: `server/transcripts.py` — `save_transcript`, `write_notes`
- Modify: `server/prompts/notes.md`

- [ ] **Step 1: Add `stage1` to `save_transcript`**

In `server/transcripts.py`, change the `save_transcript` signature (line ~96) and payload (line ~106):

```python
def save_transcript(
    session_id: str,
    member_hint: str | None,
    started_at: float,
    messages: list[dict],
    stage1: dict | None = None,
) -> Path:
    """Write the full conversation as JSON. Returns the path."""
    ts = datetime.fromtimestamp(started_at, tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    slug = _slug(member_hint or "anon")
    path = TRANSCRIPTS_DIR / f"{ts}_{slug}_{session_id[:8]}.json"
    payload = {
        "session_id": session_id,
        "member_hint": member_hint,
        "stage1": stage1,
        "started_at_iso": ts,
        "ended_at_iso": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "duration_seconds": int(time.time() - started_at),
        "messages": _serialize_messages(messages),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
```

- [ ] **Step 2: Add `stage1` to `write_notes` and prepend it to the reflector input**

In `server/transcripts.py`, add the import at the top (after line 12):

```python
from stage1 import format_stage1_for_notes
```

Change `write_notes` (signature line ~159 and the `user_msg` construction ~177):

```python
def write_notes(
    session_id: str,
    member_hint: str | None,
    messages: list[dict],
    transcript_path: Path,
    stage1: dict | None = None,
) -> Path:
```

and build `user_msg` as:

```python
    stage1_block = format_stage1_for_notes(stage1)
    stage1_prefix = f"{stage1_block}\n\n---\n\n" if stage1_block else ""
    user_msg = (
        f"# Transcript\n\nsession_id: {session_id}\n"
        f"member_hint: {member_hint!r}\n"
        f"transcript_file: {transcript_path.name}\n"
        f"\n---\n\n{stage1_prefix}{transcript_text}"
    )
```

- [ ] **Step 3: Add the `## Ideas proposed` section + stage-1 ingestion to `notes.md`**

In `server/prompts/notes.md`, in the body-sections list, add a new section block immediately before the `### \`## Surprises\`` section:

```markdown
### `## Ideas proposed`

If the participant proposed any concrete initiative, ritual, tool, or thing
they wish existed — in the stage-1 form OR in the conversation — capture each
verbatim, whether they'd want to own/run it (quote them if they said), and who
in the collective you'd point them at. This is the structural input to a
future cross-participant idea-pool aggregation. If nothing concrete was
proposed, omit the section.
```

And in the `## What you're writing` preamble, after the sentence describing the transcript, add:

```markdown
The input may begin with a `# Stage 1 form` block — the participant's
pre-interview answers (value / falling-short / ideas / involvement /
newsletter). Treat it as first-class source material: fold *value* into what's
working, *falling-short* into criticism and `Positions on open questions` Q5,
*involvement* into Q3/Q4 and matchmaking, and *ideas* into `## Ideas
proposed`. Newsletter was captured by the form — do not treat its absence in
the conversation as a gap.
```

- [ ] **Step 4: Run the full stage1 test suite (regression)**

```bash
cd /root/interviewer/server && uv run pytest tests/ -q
```

Expected: PASS (11 passed) — confirms nothing imported by the test path broke.

- [ ] **Step 5: Verify transcript/notes signatures accept stage1**

```bash
cd /root/interviewer/server && uv run python -c "
import inspect, transcripts
print('stage1' in inspect.signature(transcripts.save_transcript).parameters)
print('stage1' in inspect.signature(transcripts.write_notes).parameters)
"
```

Expected: `True` then `True`.

- [ ] **Step 6: Commit**

```bash
cd /root/interviewer
git add server/transcripts.py server/prompts/notes.md
git commit -m "stage1: persist in transcript + feed reflector; notes.md gains Ideas proposed" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Update system.md and questions.md prose

**Files:**
- Modify: `server/prompts/system.md`
- Modify: `questions.md`

- [ ] **Step 1: Remove the Personalised-newsletters section from system.md**

In `server/prompts/system.md`, delete the entire `## Personalised newsletters` section (the header line through to just before the `## Time` header — in the current file this is the block starting "## Personalised newsletters" and ending with the line before "## Time").

- [ ] **Step 2: Remove the newsletter step from the default arc**

In `server/prompts/system.md`, in the `## A default arc` list, delete arc item **8** ("**Newsletter** — if it feels right …") and renumber: old item 9 ("**Close** …") becomes item 8.

- [ ] **Step 3: Add a stage-1 note to the arc preamble**

In `server/prompts/system.md`, at the end of the `## A default arc` intro paragraph (just before the numbered list), add this sentence:

```markdown
Many participants will have completed a short pre-interview form (you'll see a `<stage1_breadth_map>` in your opening context). When present, treat stages 2–6 of this arc as already *mapped*: don't re-ask what the form covered, use it to choose where to go deep, and follow your curiosity across threads rather than marching the list.
```

- [ ] **Step 4: Adjust the Time section**

In `server/prompts/system.md`, in the `## Time` section, replace the first bullet (the "**Always ask up front how long they want to spend…**" bullet) with:

```markdown
- **The time budget usually comes from the stage-1 form.** If your opening context's `<time>` tag already shows a budget, they set it in the form — do **not** ask how long they have; just begin. Only if the `<time>` tag says *"no budget set yet"* (they skipped the form's time question) should you ask up front, with a soft default: *"how long do you have? about 15-20 minutes is the usual, but i'll check in if you want to keep going."*
```

Leave the remaining Time bullets (80% steering, check-in at budget, extensions via `update_time_budget`) unchanged.

- [ ] **Step 5: Remove the newsletter line from the Closing section**

In `server/prompts/system.md`, in the `## Closing` section, delete the sentence/line that instructs mentioning the newsletter near `end_interview` if any exists. (Search the Closing section for "newsletter" and remove that clause only; keep the notes-review mention and the `end_interview` instruction.)

- [ ] **Step 6: Document the stage-1 form in questions.md**

In `/root/interviewer/questions.md`, append:

```markdown
## Stage 1 — the pre-interview form

Before the conversation, the participant optionally fills a short form. These
answers are injected into the interviewer's opening context as a breadth map.
The interviewer must NOT re-ask these cold — they exist so it can go deep in
the right place instead of tunnelling into the first topic.

1. **what do you value about the collective?**
2. **where do you think we're falling short?**
3. **any ideas for things we could do differently, or things you wish existed?**
4. **would you like to get more involved? if so, what would you actually want to do?**
5. **newsletter — want one? how often, what would you want in it, what email?**

Plus a time question (quick-pick minutes, or "no fixed limit"). All optional.
Newsletter and time are captured here, not in the conversation.
```

- [ ] **Step 7: Sanity-check no dangling newsletter references remain in system.md**

```bash
cd /root/interviewer && grep -n -i "newsletter\|capture_newsletter" server/prompts/system.md || echo "NO newsletter refs remain"
```

Expected: `NO newsletter refs remain` (or only an incidental mention that is clearly not an instruction to ask — if any line remains, remove it).

- [ ] **Step 8: Commit**

```bash
cd /root/interviewer
git add server/prompts/system.md questions.md
git commit -m "stage2: drop newsletter from the conversation; arc/time aware of stage-1 form" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Frontend client types

**Files:**
- Modify: `/root/idealists-site/src/lib/interviewer-client.ts`

- [ ] **Step 1: Create the frontend branch**

```bash
cd /root/idealists-site && git checkout main && git checkout -b two-stage-interview-form && git branch --show-current
```

Expected: prints `two-stage-interview-form`.

- [ ] **Step 2: Add the `Stage1` interface and field**

In `/root/idealists-site/src/lib/interviewer-client.ts`, after the `CreateSessionRequest` interface (line ~15), add:

```typescript
export interface Stage1Newsletter {
	email?: string | null;
	frequency?: string | null;
	interested_in?: string | null;
}

export interface Stage1 {
	value?: string | null;
	falling_short?: string | null;
	ideas?: string | null;
	involvement?: string | null;
	time_minutes?: number | null;
	no_time_limit?: boolean;
	newsletter?: Stage1Newsletter | null;
}
```

and add `stage1` to `CreateSessionRequest`:

```typescript
export interface CreateSessionRequest {
	member_hint?: string | null;
	fast?: boolean;
	model?: string | null;
	stage1?: Stage1 | null;
}
```

- [ ] **Step 3: Type-check**

```bash
cd /root/idealists-site && npm run check 2>&1 | tail -1
```

Expected: error/warning count unchanged from the pre-existing baseline (8 errors / 32 warnings, all in unrelated files) — no new errors in `interviewer-client.ts`.

- [ ] **Step 4: Commit**

```bash
cd /root/idealists-site
git config user.name "Samuel Ratnam" && git config user.email "samueljratnam@gmail.com"
git add src/lib/interviewer-client.ts
git commit -m "interview: Stage1 client types" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

(If the commit is blocked, hand the user the command and continue.)

---

## Task 9: Frontend `form` phase UI + flow

**Files:**
- Modify: `/root/idealists-site/src/routes/interview/+page.svelte`

- [ ] **Step 1: Add `form` to the Phase union**

In `+page.svelte` line ~11, change:

```typescript
	type Phase = 'welcome' | 'conversation' | 'notes' | 'done' | 'error';
```

to:

```typescript
	type Phase = 'welcome' | 'form' | 'conversation' | 'notes' | 'done' | 'error';
```

- [ ] **Step 2: Add form state**

In `+page.svelte`, after the `let memberHint = $state('');` line (~31), add:

```typescript
	// Stage-1 form state
	let s1Value = $state('');
	let s1FallingShort = $state('');
	let s1Ideas = $state('');
	let s1Involvement = $state('');
	let s1TimeMinutes = $state<number | null>(20);
	let s1NoTimeLimit = $state(false);
	let s1WantsNewsletter = $state(false);
	let s1NlEmail = $state('');
	let s1NlInterested = $state(''); // free text: "how often + what in it"
	const TIME_CHOICES = [15, 20, 30, 45, 60];
```

- [ ] **Step 3: Refactor `begin()` into welcome→form, add form→conversation start**

In `+page.svelte`, replace the entire `begin()` function (lines ~64-85) with:

```typescript
	function begin() {
		// Welcome → stage-1 form. (No network yet; the session starts after the form.)
		errorMessage = '';
		phase = 'form';
	}

	function buildStage1() {
		const t = (s: string) => {
			const v = s.trim();
			return v ? v : null;
		};
		const newsletter =
			s1WantsNewsletter && s1NlEmail.trim()
				? {
						email: s1NlEmail.trim(),
						frequency: null,
						interested_in: t(s1NlInterested)
					}
				: null;
		return {
			value: t(s1Value),
			falling_short: t(s1FallingShort),
			ideas: t(s1Ideas),
			involvement: t(s1Involvement),
			time_minutes: s1NoTimeLimit ? null : s1TimeMinutes,
			no_time_limit: s1NoTimeLimit,
			newsletter
		};
	}

	async function startConversation(stage1: import('$lib/interviewer-client').Stage1 | null) {
		errorMessage = '';
		busy = true;
		try {
			const hint = memberHint.trim() || null;
			turns = [];
			phase = 'conversation';
			await tick();
			inputEl?.focus();
			const events = await interviewer.startStream({ member_hint: hint, stage1 });
			await consumeStream(events);
		} catch (e) {
			handleError(e);
			if (turns.length === 0) phase = 'form';
		} finally {
			busy = false;
			await tick();
			inputEl?.focus();
		}
	}

	function submitForm() {
		startConversation(buildStage1());
	}

	function skipForm() {
		startConversation(null);
	}
```

Note: `handleError` sets `phase = 'error'`; the line after it overrides to `phase = 'form'` when no turns streamed, so a failed start returns the participant to the form with their answers intact and the error message visible (the form markup renders `{#if errorMessage}`). **This refines the spec's error-handling** ("proceed to conversation with an empty map") to "return to the form with answers intact" — it still satisfies the non-negotiable requirement (the interview is never *blocked*: the one-click "skip straight to it" is always available), and it avoids silently discarding what the participant just typed. Functionally superior; flagged here so it's a documented decision, not a drift.

- [ ] **Step 4: Add the `form` phase markup**

In `+page.svelte`, find the welcome block boundary `{:else if phase === 'conversation'}` (line ~773) and insert this new branch immediately *before* it:

```svelte
	{:else if phase === 'form'}
		<section class="welcome stage1" in:fade={{ duration: 400 }}>
			<h1 class="display-title">
				<span class="title-line-1">before</span>
				<span class="title-line-2">we talk</span>
			</h1>
			<div class="rule"></div>
			<p class="lede">
				a couple of minutes of rough notes — all optional, a sentence is plenty. it lets the
				conversation go deeper instead of starting cold. skip anything, or skip the whole thing.
			</p>

			<div class="form">
				<div class="field">
					<span class="field-label">how long do you want the conversation to be?</span>
					<div class="chips">
						{#each TIME_CHOICES as m}
							<button
								type="button"
								class="chip"
								class:active={!s1NoTimeLimit && s1TimeMinutes === m}
								onclick={() => {
									s1TimeMinutes = m;
									s1NoTimeLimit = false;
								}}>{m} min</button
							>
						{/each}
						<button
							type="button"
							class="chip"
							class:active={s1NoTimeLimit}
							onclick={() => (s1NoTimeLimit = true)}>no fixed limit</button
						>
					</div>
				</div>

				<label class="field">
					<span class="field-label">what do you value about the collective?</span>
					<textarea class="s1-input" rows="2" bind:value={s1Value} disabled={busy}></textarea>
				</label>
				<label class="field">
					<span class="field-label">where do you think we're falling short?</span>
					<textarea class="s1-input" rows="2" bind:value={s1FallingShort} disabled={busy}
					></textarea>
				</label>
				<label class="field">
					<span class="field-label"
						>any ideas for things we could do differently, or things you wish existed?</span
					>
					<textarea class="s1-input" rows="2" bind:value={s1Ideas} disabled={busy}></textarea>
				</label>
				<label class="field">
					<span class="field-label"
						>would you like to get more involved? if so, what would you want to do?</span
					>
					<textarea class="s1-input" rows="2" bind:value={s1Involvement} disabled={busy}
					></textarea>
				</label>

				<label class="field newsletter-toggle">
					<input type="checkbox" bind:checked={s1WantsNewsletter} disabled={busy} />
					<span class="field-label">i'd like a personalised newsletter</span>
				</label>
				{#if s1WantsNewsletter}
					<label class="field">
						<span class="field-label">email</span>
						<input
							class="underline-input"
							type="email"
							bind:value={s1NlEmail}
							spellcheck="false"
							autocomplete="off"
							disabled={busy}
						/>
					</label>
					<label class="field">
						<span class="field-label">how often, and what would you want in it?</span>
						<textarea class="s1-input" rows="2" bind:value={s1NlInterested} disabled={busy}
						></textarea>
					</label>
				{/if}

				{#if errorMessage}
					<p class="error" in:fade>{errorMessage}</p>
				{/if}

				<div class="actions">
					<button class="begin-btn" onclick={submitForm} disabled={busy} aria-busy={busy}>
						<span class="begin-text">{busy ? 'opening' : 'start the conversation'}</span>
					</button>
					<button class="skip-btn" onclick={skipForm} disabled={busy}>skip straight to it</button>
				</div>
			</div>
		</section>
```

Note: the "how often / what in it" textarea binds to `s1NlInterested`; `frequency` is sent as `null` (the single free-text field carries cadence + content), so the existing newsletter-record shape is unchanged.

- [ ] **Step 5: Add minimal scoped styles for the new controls**

In `+page.svelte`, inside the existing `<style>` block, append:

```css
	.stage1 .form {
		max-width: 36rem;
	}
	.s1-input {
		width: 100%;
		background: transparent;
		border: none;
		border-bottom: 1px solid var(--rule, rgba(0, 0, 0, 0.2));
		font: inherit;
		color: inherit;
		resize: vertical;
		padding: 0.35rem 0;
	}
	.s1-input:focus {
		outline: none;
		border-bottom-color: currentColor;
	}
	.chips {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 0.4rem;
	}
	.chip {
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--rule, rgba(0, 0, 0, 0.25));
		border-radius: 999px;
		background: transparent;
		font: inherit;
		color: inherit;
		cursor: pointer;
	}
	.chip.active {
		border-color: currentColor;
		font-weight: 600;
	}
	.newsletter-toggle {
		flex-direction: row;
		align-items: center;
		gap: 0.5rem;
	}
	.skip-btn {
		background: none;
		border: none;
		font: inherit;
		color: inherit;
		opacity: 0.6;
		cursor: pointer;
		text-decoration: underline;
	}
	.skip-btn:hover {
		opacity: 1;
	}
```

(If `--rule` is not a defined CSS variable in this component, the `rgba(...)` fallback applies — verify visually in Step 7.)

- [ ] **Step 6: Type-check**

```bash
cd /root/idealists-site && npm run check 2>&1 | tail -1
```

Expected: error/warning count unchanged from the baseline (8 errors / 32 warnings in unrelated files). If `npm run check` reports any error whose path is `src/routes/interview/+page.svelte`, fix it before continuing.

- [ ] **Step 7: Manual visual + flow check**

Run `npm run dev` (in `/root/idealists-site`), open `/interview`:
- "begin" goes to the form (no network call yet).
- The 5 prompts + time chips + newsletter toggle render; "no fixed limit" deselects the minute chips and vice-versa.
- "skip straight to it" starts the conversation (requires the backend running with `ANTHROPIC_API_KEY`); "start the conversation" with some fields filled also starts it.
- A backend error returns to the form with answers intact.

(If the backend isn't available in this environment, verify the welcome→form transition and the form rendering/interaction only, and note the conversation-start path as untested-here.)

- [ ] **Step 8: Commit**

```bash
cd /root/idealists-site
git add src/routes/interview/+page.svelte
git commit -m "interview: stage-1 form phase (time + 5 prompts + newsletter)" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: End-to-end verification

**Files:**
- Modify: `server/smoke_test.py`

- [ ] **Step 1: Extend the smoke test with a stage-1 path**

In `server/smoke_test.py`, replace the `session = Session(member_hint="lou")` line and the `session.time_budget_seconds = 5 * 60` line with:

```python
    from stage1 import normalize_stage1, time_choice_to_budget_seconds
    s1 = normalize_stage1(
        {
            "value": "the people and the writing",
            "falling_short": "lots of talk, less shipping",
            "ideas": "a weekly show-and-tell call",
            "involvement": "would help organise events",
            "time_minutes": 5,
            "no_time_limit": False,
            "newsletter": None,
        }
    )
    session = Session(member_hint="lou", stage1=s1)
    budget = time_choice_to_budget_seconds(s1)
    if budget is not None:
        session.time_budget_seconds = budget
```

and update the `save_transcript(...)` / `write_notes(...)` calls at the bottom to pass `stage1=session.stage1`:

```python
    transcript_path = save_transcript("smoke-test", session.member_hint, session.started_at, session.messages, stage1=session.stage1)
    print(f"transcript → {transcript_path}")
    notes_path = write_notes("smoke-test", session.member_hint, session.messages, transcript_path, stage1=session.stage1)
```

- [ ] **Step 2: Run the full unit suite**

```bash
cd /root/interviewer/server && uv run pytest tests/ -q
```

Expected: PASS (11 passed).

- [ ] **Step 3: Run the live smoke test (requires ANTHROPIC_API_KEY)**

```bash
cd /root/interviewer/server && uv run python smoke_test.py
```

Expected: prints an opening turn that does **not** ask "how long do you have" (budget came from the form), references the breadth-map material naturally without reciting it, runs three turns, and writes a transcript whose JSON contains a non-null `"stage1"` key and a notes file containing a `Stage 1 form`-derived `## Ideas proposed` entry. If `ANTHROPIC_API_KEY` is unset the script prints the skip message and exits 0 — note that the live assertions were not exercised.

- [ ] **Step 4: Inspect the written transcript for the stage1 block**

```bash
cd /root/interviewer/server && python3 -c "
import json, glob, os
f = max(glob.glob('transcripts/*smoke-test*.json'), key=os.path.getmtime)
d = json.load(open(f))
print('stage1 present:', d.get('stage1') is not None)
print('value:', d['stage1']['value'])
"
```

Expected: `stage1 present: True`, `value: the people and the writing`.

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer
git add server/smoke_test.py
git commit -m "stage1: smoke test exercises the form-armed path" -m "Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Final review against the spec**

Re-read `docs/superpowers/specs/2026-05-17-two-stage-interview-design.md` and confirm each spec section maps to landed work: stage-1 form (Tasks 8-9), time→budget (Tasks 1,5,7), breadth-map injection + anti-tunnel + graceful degradation (Tasks 2,4,7), newsletter relocation (Tasks 3,5,9), transcript+reflector ingest + `## Ideas proposed` (Task 6), no remaining stage-2 newsletter machinery (Tasks 3,7). The notes-pipeline reliability bug remains explicitly out of scope (separate plan).

---

## Notes for the executor

- **Commit-identity guardrail:** several commits set `git config user.*` to the project owner. If a commit is blocked by the safety classifier, do NOT attempt workarounds — print the exact `git` command for the user to run, mark the step done once they confirm, and continue.
- **No API key in this environment:** every backend step except Task 10 Step 3 is verifiable without `ANTHROPIC_API_KEY` (imports, pure-function tests, signature checks). Don't block the plan on the live smoke test; record it as "not exercised here" if the key is absent.
- **Frontend build:** `npm run build` fails pre-existing on missing `GITHUB_*` env (`git-history.ts`) and reaches nothing in the interview route — use `npm run check` as the authoritative frontend gate, comparing against the documented baseline (8 errors / 32 warnings in unrelated files), not absolute zero.
