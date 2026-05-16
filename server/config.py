"""Paths, model selection, environment for the AFFINE interviewer."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SERVER_DIR = Path(__file__).resolve().parent
REPO_DIR = SERVER_DIR.parent
WIKI_DIR = REPO_DIR / "wiki"
PROMPTS_DIR = SERVER_DIR / "prompts"
STATIC_DIR = SERVER_DIR / "static"

# The unprocessed → processed pipeline. Interview transcripts, reflector
# notes, and uploaded files all land in unprocessed/; a later "integrate"
# pass folds them into the wiki and archives the consumed inputs in processed/.
UNPROCESSED_DIR = REPO_DIR / "unprocessed"
PROCESSED_DIR = REPO_DIR / "processed"
TRANSCRIPTS_DIR = UNPROCESSED_DIR / "transcripts"
NOTES_DIR = UNPROCESSED_DIR / "notes"
UPLOADS_DIR = UNPROCESSED_DIR / "uploads"

for _d in (TRANSCRIPTS_DIR, NOTES_DIR, UPLOADS_DIR, PROCESSED_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Model selection. Opus 4.7 is the interviewer; Sonnet is a faster fallback
# for debugging / low-stakes runs.
MODEL_DEFAULT = "claude-opus-4-7"
MODEL_FAST = "claude-sonnet-4-6"

# Hard caps so a runaway tool loop can't pile up turns / tokens.
MAX_TOOL_TURNS = 16
MAX_TOKENS_PER_TURN = 1600

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
