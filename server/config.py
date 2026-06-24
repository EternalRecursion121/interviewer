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

# Model selection. The interviewer runs on Sonnet 4.6 (switched from Opus 4.7
# at the operator's request — faster and cheaper). Opus 4.7 had originally been
# chosen after a head-to-head experiment (see /tmp/experiment3/report_addendum.md)
# where it produced the highest-ceiling reframes; revisit if interview quality
# regresses. MODEL_FAST remains the explicit Sonnet alias used by the `fast` flag.
MODEL_DEFAULT = "claude-sonnet-4-6"
MODEL_FAST = "claude-sonnet-4-6"

# Hard caps so a runaway loop can't pile up turns.
MAX_TOOL_TURNS = 16
# Cap on output per assistant turn. 1600 leaves room for substantive syntheses
# and longer wiki-grounded explanations when warranted; the brevity discipline
# lives in the system prompt's "default short, expand when they want" guidance,
# not in this cap.
MAX_TOKENS_PER_TURN = 1600

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# Transient-error resilience. The Anthropic SDK retries 408/409/429/500/529 and
# connection errors with exponential backoff up to this many times — covers the
# "overloaded at connect" failures that previously killed a whole turn. Streaming
# requests get the same retry on connection establishment.
ANTHROPIC_MAX_RETRIES = int(os.environ.get("ANTHROPIC_MAX_RETRIES", "4"))
