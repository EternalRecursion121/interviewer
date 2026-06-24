"""Robustness regression tests for the turn loop.

These cover three failure modes that took down real interviews:

1. A transient API error mid-turn must NOT poison the session. The just-added
   user message has to be rolled back so the history stays well-formed and the
   next turn can succeed (instead of every later turn 400-ing on a dangling
   user turn).
2. The non-streaming path has the same atomicity guarantee.
3. Completed turns are persisted to an append-only log as they happen, so a
   client disconnect after a turn completes can't lose it.

The tests drive the loop with a scripted fake Anthropic client — no network.
"""
from __future__ import annotations

import types

import pytest

import loop
import transcripts
from loop import Session, step, step_stream


# --- a scriptable fake Anthropic client -----------------------------------


class _Reply:
    def __init__(self, text="ok", stop_reason="end_turn"):
        self.text = text
        self.stop_reason = stop_reason

    def _block(self):
        return types.SimpleNamespace(
            type="text",
            text=self.text,
            model_dump=lambda: {"type": "text", "text": self.text},
        )

    def final_message(self):
        return types.SimpleNamespace(content=[self._block()], stop_reason=self.stop_reason)


class _StreamCtx:
    def __init__(self, item):
        self._item = item

    def __enter__(self):
        if isinstance(self._item, Exception):
            raise self._item
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        delta = types.SimpleNamespace(type="text_delta", text=self._item.text)
        yield types.SimpleNamespace(type="content_block_delta", delta=delta, index=0)

    def get_final_message(self):
        return self._item.final_message()


class _FakeMessages:
    def __init__(self, script):
        self._script = list(script)
        self.calls = 0

    def _next(self):
        item = self._script[self.calls]
        self.calls += 1
        return item

    def stream(self, **kwargs):
        return _StreamCtx(self._next())

    def create(self, **kwargs):
        item = self._next()
        if isinstance(item, Exception):
            raise item
        return item.final_message()


class FakeClient:
    def __init__(self, script):
        self.messages = _FakeMessages(script)


def _drain(gen):
    return list(gen)


@pytest.fixture(autouse=True)
def _isolate_transcripts(tmp_path, monkeypatch):
    """Redirect the append-only log dir to a temp path so tests that run
    successful turns never write into the real transcripts/ directory."""
    monkeypatch.setattr(transcripts, "TRANSCRIPTS_DIR", tmp_path)


# --- tests -----------------------------------------------------------------


def test_failed_stream_turn_rolls_back_and_session_recovers():
    session = Session(session_id="t1")
    client = FakeClient([
        _Reply("hello, welcome"),       # opening
        RuntimeError("overloaded_error"),  # turn 1: transient blow-up mid-turn
        _Reply("good question"),         # turn 2: should still work
    ])

    _drain(step_stream(session, None, client, opening=True))
    baseline = len(session.messages)
    assert baseline == 2  # opening user msg + assistant reply
    assert session.messages[-1]["role"] == "assistant"

    # A turn that errors must leave history exactly as it was — no dangling user turn.
    events = _drain(step_stream(session, "this will fail", client))
    assert any(e["type"] == "error" for e in events)
    assert len(session.messages) == baseline, "failed turn poisoned the history"
    assert session.messages[-1]["role"] == "assistant"

    # The session is not poisoned: the next turn succeeds and history alternates.
    events = _drain(step_stream(session, "and this works", client))
    assert any(e["type"] == "turn_done" for e in events)
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_failed_nonstreaming_turn_rolls_back():
    session = Session(session_id="t2")
    client = FakeClient([_Reply("opening"), RuntimeError("boom"), _Reply("recovered")])

    # opening (non-streaming) — uses create()
    loop.opening_turn(session, client=client)
    baseline = len(session.messages)

    with pytest.raises(RuntimeError):
        step(session, "fails", client=client)
    assert len(session.messages) == baseline, "failed turn left a dangling user message"

    out = step(session, "works", client=client)
    assert out == "recovered"
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_completed_turns_are_appended_to_log(tmp_path, monkeypatch):
    monkeypatch.setattr(transcripts, "TRANSCRIPTS_DIR", tmp_path)
    session = Session(session_id="abc12345", member_hint="tester")
    client = FakeClient([_Reply("hi"), _Reply("answer")])

    _drain(step_stream(session, None, client, opening=True))
    assert session.persisted_count == len(session.messages) == 2

    _drain(step_stream(session, "a question", client))
    assert session.persisted_count == len(session.messages) == 4

    logs = list(tmp_path.glob("*.jsonl"))
    assert len(logs) == 1
    lines = [ln for ln in logs[0].read_text().splitlines() if ln.strip()]
    assert len(lines) == 4  # every committed message logged exactly once
