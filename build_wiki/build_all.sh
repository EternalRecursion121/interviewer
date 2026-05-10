#!/usr/bin/env bash
# Re-build the auto-generated parts of the wiki from raw/.
# Hand-written pages (overview, principles, concepts, projects, themes,
# writings, sources) are NOT touched.

set -euo pipefail
cd "$(dirname "$0")/.."

uv run python build_wiki/build_member_pages.py
uv run python build_wiki/build_channel_summaries.py
uv run python build_wiki/build_index.py
uv run python build_wiki/lint.py
