"""Read-only wiki tools for the interviewer.

Five tools, all scoped strictly inside `wiki/`:
- search(query, type?) — ripgrep-style snippets
- open(path)            — single page
- open_many(paths[])    — batch read
- member(name_or_handle) — smart lookup that bundles member page + their box channel
- follow(link_text)     — resolve a wikilink
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable

from config import WIKI_DIR


# Tool schemas — passed to messages.create as `tools=[...]`.
# Schemas are kept small and human-readable to avoid wasted tokens in the prompt.
TOOL_SCHEMAS = [
    {
        "name": "member",
        "description": (
            "Look up a member of the Idealists Collective by name or discord handle. "
            "Returns their member page plus, if they have one, the contents of their "
            "personal box channel. This is the right tool whenever you have a name or "
            "handle to look up — it bundles what would otherwise be 2-3 separate calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_handle": {
                    "type": "string",
                    "description": "A first name, full name, or Discord handle (with or without `@`).",
                }
            },
            "required": ["name_or_handle"],
        },
    },
    {
        "name": "search",
        "description": (
            "Search the wiki for a query string. Returns matching lines with surrounding "
            "context (~3 lines either side) and the file path. Optional `type` filters by "
            "page kind (member, project, theme, concept, writing, channel, source)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["member", "project", "theme", "concept", "writing", "channel", "source"],
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "open",
        "description": "Read a single wiki page in full. Path is relative to wiki/, e.g. `projects/anthist.md`.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "open_many",
        "description": (
            "Read multiple wiki pages in one call. Use this when you want to compare or "
            "assemble context (e.g., a project page plus its lead's member page). Paths "
            "are relative to wiki/."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            "required": ["paths"],
        },
    },
    {
        "name": "follow",
        "description": (
            "Resolve a wikilink-style reference. Pass either the exact path "
            "(`wiki/projects/foo.md`) or the bare slug (`foo`) and you'll get the page. "
            "Use this when a page you just read mentioned a cross-link you want to follow."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reference": {"type": "string"}},
            "required": ["reference"],
        },
    },
    {
        "name": "end_interview",
        "description": (
            "Call this when the conversation has reached a real natural close — "
            "they said goodbye, you said goodbye, your next instinct would be to "
            "mirror an emoji or a *nods*. Once you call this, the participant "
            "cannot receive any further messages, so include your goodbye in the "
            "same turn (text alongside the tool call). Use this instead of letting "
            "the conversation devolve into echoing acknowledgments. Also use it if "
            "the participant becomes uncommunicative for several turns, or if a "
            "safety boundary requires you to stop. The `reason` is free text — "
            "'natural close', 'they said goodbye', 'they bailed', 'safety', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
    {
        "name": "update_time_budget",
        "description": (
            "Set the conversation's time budget. Call this in two cases: "
            "(1) when the participant first tells you how long they want to spend "
            "('20 minutes', 'half an hour', 'until 3pm'), and "
            "(2) when they extend ('let's go 15 more', 'maybe another half hour'). "
            "The argument `minutes_remaining` is how many more minutes from NOW — "
            "the server will set the budget to elapsed + minutes_remaining*60. "
            "If they give an absolute time ('until 3pm'), do the math yourself "
            "and pass remaining minutes. Decimals are fine ('half an hour' = 30; "
            "'1.5 hours' = 90). Don't call this for vague answers like 'whenever' "
            "or 'no rush' — leave the budget unset in that case."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes_remaining": {
                    "type": "number",
                    "description": "How many more minutes from now they want to spend.",
                },
            },
            "required": ["minutes_remaining"],
        },
    },
]

# Special tool names — handled in the loop, not via `dispatch`.
END_INTERVIEW_TOOL = "end_interview"
UPDATE_TIME_BUDGET_TOOL = "update_time_budget"


def _safe_resolve(path: str) -> Path | None:
    """Resolve `path` (relative to wiki/) and ensure it stays inside wiki/."""
    if not path:
        return None
    # Normalize: drop leading wiki/, leading ./
    p = path.strip().lstrip("/")
    for prefix in ("wiki/", "./", "./wiki/"):
        if p.startswith(prefix):
            p = p[len(prefix):]
    if not p.endswith(".md"):
        p = p + ".md"
    candidate = (WIKI_DIR / p).resolve()
    try:
        candidate.relative_to(WIKI_DIR.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.lower()).strip("-")
    return s


# ---- search ----------------------------------------------------------------


def _iter_pages(type_filter: str | None = None) -> Iterable[Path]:
    if type_filter:
        sub = WIKI_DIR / f"{type_filter}s"  # members, projects, themes, ...
        if sub.is_dir():
            yield from sorted(sub.rglob("*.md"))
            return
        # singletons (overview, principles) have no sub-dir
    yield from sorted(WIKI_DIR.rglob("*.md"))


def search(query: str, type: str | None = None, limit: int = 10) -> str:
    if not query.strip():
        return "search: empty query"
    q = query.lower()
    hits: list[tuple[Path, int, list[str]]] = []
    for p in _iter_pages(type):
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines):
            if q in line.lower():
                lo = max(0, i - 2)
                hi = min(len(lines), i + 3)
                hits.append((p, i + 1, lines[lo:hi]))
                break  # one snippet per page
    if not hits:
        return f"search: no matches for {query!r}"
    hits = hits[:limit]
    out = [f"search: {len(hits)} hit(s) for {query!r}" + (f" (type={type})" if type else "")]
    for p, lineno, snippet in hits:
        rel = p.relative_to(WIKI_DIR)
        out.append(f"\n## {rel}:{lineno}")
        out.extend(snippet)
    return "\n".join(out)


# ---- open / open_many / follow --------------------------------------------


def open_page(path: str) -> str:
    resolved = _safe_resolve(path)
    if not resolved:
        return f"open: no such page {path!r}"
    rel = resolved.relative_to(WIKI_DIR)
    return f"# {rel}\n\n{resolved.read_text(encoding='utf-8')}"


def open_many(paths: list[str]) -> str:
    if not paths:
        return "open_many: no paths"
    parts = []
    for p in paths[:8]:
        parts.append(open_page(p))
    return "\n\n---\n\n".join(parts)


def follow(reference: str) -> str:
    """Resolve a slug-or-path; try a few common locations."""
    ref = reference.strip().lstrip("/")
    for prefix in ("wiki/", "./", "./wiki/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    if ref.endswith(".md"):
        ref = ref[:-3]

    # Try exact path
    direct = _safe_resolve(ref + ".md")
    if direct:
        return open_page(ref + ".md")

    # Try common containers
    for container in ("members", "projects", "themes", "concepts", "writings", "channels", "sources"):
        candidate = _safe_resolve(f"{container}/{ref}.md")
        if candidate:
            return open_page(f"{container}/{ref}.md")

    # Try slugified search
    slug = _slugify(ref)
    if slug != ref:
        for container in ("members", "projects", "themes", "concepts", "writings", "channels", "sources"):
            candidate = _safe_resolve(f"{container}/{slug}.md")
            if candidate:
                return open_page(f"{container}/{slug}.md")

    return f"follow: could not resolve {reference!r}"


# ---- member: the smart bundle ---------------------------------------------


def _members_index() -> dict[str, str]:
    """Map of lowercased name/handle/slug → slug. Built lazily (small)."""
    index: dict[str, str] = {}
    for p in (WIKI_DIR / "members").glob("*.md"):
        slug = p.stem
        index[slug.lower()] = slug
        # Pull the title and discord handle from the page header
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r'^title:\s*"?Member:\s*([^"\n]+?)"?\s*$', text, re.MULTILINE)
        if m:
            name = m.group(1).strip()
            index[name.lower()] = slug
            # First-name fallback
            first = name.split()[0].lower() if name.split() else ""
            if first and first not in index:
                index[first] = slug
        h = re.search(r"-\s+\*\*Discord:\*\*\s+`([^`]+)`", text)
        if h:
            index[h.group(1).lower().lstrip("@")] = slug
    return index


def _box_channel_for(slug: str) -> Path | None:
    """A member's #firstname-box channel, if it exists."""
    p = WIKI_DIR / "members" / f"{slug}.md"
    if not p.exists():
        return None
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r'^title:\s*"?Member:\s*([^"\n]+?)"?\s*$', text, re.MULTILINE)
    if not m:
        return None
    first = m.group(1).split()[0].lower() if m.group(1).split() else ""
    if not first:
        return None
    box = WIKI_DIR / "channels" / f"{_slugify(first)}-box.md"
    return box if box.is_file() else None


def member(name_or_handle: str) -> str:
    needle = name_or_handle.strip().lower().lstrip("@")
    if not needle:
        return "member: empty input"
    index = _members_index()

    slug = index.get(needle)
    if not slug:
        # Try as a substring of name fields
        for k, v in index.items():
            if needle in k:
                slug = v
                break
    if not slug:
        return (
            f"member: no exact match for {name_or_handle!r}. "
            "Use `search` with their name to find related references in the wiki."
        )

    parts = [open_page(f"members/{slug}.md")]
    box = _box_channel_for(slug)
    if box:
        rel = box.relative_to(WIKI_DIR)
        parts.append(f"\n\n---\n\n# {rel}\n\n{box.read_text(encoding='utf-8')}")
    return "".join(parts)


# ---- dispatcher -----------------------------------------------------------


def dispatch(name: str, params: dict) -> str:
    if name == "member":
        return member(params.get("name_or_handle", ""))
    if name == "search":
        return search(params.get("query", ""), params.get("type"), int(params.get("limit", 10)))
    if name == "open":
        return open_page(params.get("path", ""))
    if name == "open_many":
        return open_many(params.get("paths", []))
    if name == "follow":
        return follow(params.get("reference", ""))
    return f"unknown tool: {name}"
