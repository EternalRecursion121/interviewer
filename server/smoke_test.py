"""End-to-end smoke test: boot server in-process, run a tiny conversation.

Requires ANTHROPIC_API_KEY in env. Run from /root/interviewer/server:

    uv run python smoke_test.py
"""
from __future__ import annotations

import os
import sys

if not os.environ.get("ANTHROPIC_API_KEY"):
    print("ANTHROPIC_API_KEY not set — skipping live test")
    sys.exit(0)

from anthropic import Anthropic

from config import ANTHROPIC_API_KEY
from loop import Session, opening_turn, step
from transcripts import save_transcript, write_notes


def main():
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
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
            "open_questions": {
                "roles": "a small rotating crew for events and the website",
            },
        }
    )
    session = Session(member_hint="lou", stage1=s1)
    budget = time_choice_to_budget_seconds(s1)
    if budget is not None:
        session.time_budget_seconds = budget

    print("=== opening turn ===")
    print(opening_turn(session, client=client))
    print()

    user_inputs = [
        "i've got about 5 minutes — i'm a member, you can probably look me up. just want to chat.",
        "what's something interesting about the collective i might not know?",
        "ok thanks, that's enough for now",
    ]
    for ut in user_inputs:
        print(f"=== participant ===\n{ut}\n")
        reply = step(session, ut, client=client)
        print(f"=== interviewer ===\n{reply}\n")

    # Save + reflect
    transcript_path = save_transcript("smoke-test", session.member_hint, session.started_at, session.messages, stage1=session.stage1)
    print(f"transcript → {transcript_path}")
    notes_path = write_notes("smoke-test", session.member_hint, session.messages, transcript_path, stage1=session.stage1)
    print(f"notes → {notes_path}")
    print(f"elapsed: {session.elapsed()}s; budget: {session.time_budget_seconds}s")


if __name__ == "__main__":
    main()
