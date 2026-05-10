"""Paths, model selection, environment."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
WIKI_DIR = REPO_DIR / "wiki"
TRANSCRIPTS_DIR = SERVER_DIR / "transcripts"
NOTES_DIR = SERVER_DIR / "notes"
PROMPTS_DIR = SERVER_DIR / "prompts"

TRANSCRIPTS_DIR.mkdir(exist_ok=True)
NOTES_DIR.mkdir(exist_ok=True)

# Model selection. Default is Opus 4.7 — chosen after a head-to-head experiment
# (see /tmp/experiment3/report_addendum.md) where it produced the highest-ceiling
# reframes (the moves participants explicitly named as "that landed"). Sonnet is
# kept available as a faster/cheaper fallback for low-stakes / debugging runs.
MODEL_DEFAULT = "claude-opus-4-7"
MODEL_FAST = "claude-sonnet-4-6"
# Backwards-compat alias for any existing callers expecting MODEL_DEEP.
MODEL_DEEP = MODEL_DEFAULT

# Hard caps so a runaway loop can't pile up turns.
MAX_TOOL_TURNS = 16
# Cap on output per assistant turn. 1600 leaves room for substantive syntheses
# and longer wiki-grounded explanations when warranted; the brevity discipline
# lives in the system prompt's "default short, expand when they want" guidance,
# not in this cap.
MAX_TOKENS_PER_TURN = 1600

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
