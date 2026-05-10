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
    session = Session(member_hint="lou")  # known member; tests member() lookup

    print("=== opening turn ===")
    print(opening_turn(session, client=client))
    print()

    # Set a 5-min budget so the time-tag has something to work with
    session.time_budget_seconds = 5 * 60

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
    transcript_path = save_transcript("smoke-test", session.member_hint, session.started_at, session.messages)
    print(f"transcript → {transcript_path}")
    notes_path = write_notes("smoke-test", session.member_hint, session.messages, transcript_path)
    print(f"notes → {notes_path}")
    print(f"elapsed: {session.elapsed()}s; budget: {session.time_budget_seconds}s")


if __name__ == "__main__":
    main()
