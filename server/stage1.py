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
        "open_questions": {             # None unless ≥1 braindump is non-empty
            "membership": str | None,
            "growth": str | None,
            "roles": str | None,
            "action": str | None,
        } | None,
    }

`normalize_stage1` returns None when the participant supplied nothing at all
(form skipped) so callers can treat "no stage 1" uniformly.
"""
from __future__ import annotations

TEXT_FIELDS = ("value", "falling_short", "ideas", "involvement")

# The open governance questions the stage-1 form lets participants braindump
# on — a trimmed subset of wiki/open-questions.md. Q4 ("what's stopping you")
# and Q5 ("what could we do better") are omitted because broad stage-1 prompts
# 4 and 2 already cover that ground. Each tuple is
# (slug, wiki Q-number, short question text): the slug keys the data, the
# Q-number attributes the braindump to the right `## Positions on open
# questions` bucket. wiki/open-questions.md is canonical — keep this in sync
# by hand.
OPEN_QUESTIONS = (
    ("membership", "Q1", "How should new membership be handled?"),
    ("growth", "Q2", "Should the collective grow — and if so, how?"),
    ("roles", "Q3", "What roles of responsibility should exist, and who'd want them?"),
    ("action", "Q6", "How do we shift from talking to actually doing?"),
)
OPEN_QUESTION_KEYS = tuple(slug for slug, _, _ in OPEN_QUESTIONS)


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


def _clean_open_questions(v) -> dict | None:
    """Clean a raw open_questions dict to {slug: str|None}, or None if all blank."""
    if not isinstance(v, dict):
        return None
    cleaned = {k: _clean(v.get(k)) for k in OPEN_QUESTION_KEYS}
    return cleaned if any(cleaned.values()) else None


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

    open_questions = _clean_open_questions(raw.get("open_questions"))

    out = {
        **text,
        "time_minutes": time_minutes,
        "no_time_limit": no_time_limit,
        "newsletter": newsletter,
        "open_questions": open_questions,
    }

    # "Empty" = nothing the participant actually chose. no_time_limit=True is a
    # real choice and must survive even if every other field is blank.
    if (
        all(out[f] is None for f in TEXT_FIELDS)
        and time_minutes is None
        and not no_time_limit
        and newsletter is None
        and open_questions is None
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

    oq = stage1.get("open_questions") or {}
    oq_answered = [(text, oq[slug]) for slug, _, text in OPEN_QUESTIONS if oq.get(slug)]
    has_newsletter = bool(stage1.get("newsletter"))

    if not lines and not oq_answered and not has_newsletter:
        return ""

    if oq_answered:
        lines.append(
            "- Open questions they already wrote thoughts on. Go deeper on "
            "these or skip them — do NOT surface them cold. The open questions "
            "they left blank are still fair game:"
        )
        lines.extend(f'  - {text}: "{val}"' for text, val in oq_answered)

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
