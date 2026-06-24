"""Read-only wiki tools for the AFFINE interviewer.

All tools are scoped strictly inside `wiki/`. The interviewer cannot write,
run shell, or reach the network beyond the Anthropic API.

- search(query, type?)     — substring search with snippets
- open(path)               — single page
- open_many(paths[])       — batch read
- follow(reference)        — resolve a wikilink slug
- participant(name_or_handle) — smart person lookup (page + pod assignment)
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from config import WIKI_DIR

# Subdirectories that hold a "kind" of page. Used by the search `type` filter
# and by follow()'s container search.
CONTAINERS = ("concepts", "participants", "mentors", "team", "themes", "talks", "tags", "sources")

# People live in one of three layers by role.
PEOPLE_DIRS = ("participants", "mentors", "team")

# search `type` value -> subdir
_TYPE_TO_DIR = {
    "concept": "concepts",
    "participant": "participants",
    "theme": "themes",
    "talk": "talks",
    "tag": "tags",
    "mentor": "mentors",
    "team": "team",
    "source": "sources",
}


TOOL_SCHEMAS = [
    {
        "name": "participant",
        "description": (
            "Look up someone in the AFFINE 2026 cohort by name or handle. Returns "
            "their canonical participant page (which already merges their intro, any "
            "enrichment, Discord activity, and mentor-catalog entry) plus their pod "
            "assignment if they have one. Use this whenever you have a name or handle — "
            "the pre-loaded cohort portrait summarizes the group; this returns the "
            "specific things the person actually said."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name_or_handle": {
                    "type": "string",
                    "description": "A first name, full name, or handle (with or without `@`).",
                }
            },
            "required": ["name_or_handle"],
        },
    },
    {
        "name": "search",
        "description": (
            "Search the wiki for a query string. Returns matching lines with ~3 lines "
            "of surrounding context and the file path. Optional `type` filters by page "
            "kind. Use when a topic/concept comes up and you want to find who or what "
            "touches it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["concept", "participant", "theme", "talk", "tag", "mentor", "source"],
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "open",
        "description": "Read a single wiki page in full. Path is relative to wiki/, e.g. `concepts/goodhart.md`.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "open_many",
        "description": (
            "Read multiple wiki pages in one call. Use this to assemble context "
            "(e.g. a concept page + a participant's page + the relevant theme). "
            "Paths are relative to wiki/."
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
            "Resolve a wikilink-style reference. Pass the exact path "
            "(`wiki/concepts/goodhart.md`) or the bare slug (`goodhart`) and you'll "
            "get the page. Use this to follow a cross-link a page just mentioned."
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
            "mirror an emoji or a *nods*. Once you call it, the participant cannot "
            "receive further messages, so include your goodbye in the same turn "
            "(text alongside the tool call). Also use it if they go uncommunicative "
            "for several turns, or a safety boundary requires stopping. `reason` is "
            "free text — 'natural close', 'they said goodbye', 'they bailed', 'safety'."
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
            "Set the conversation's time budget. Call it (1) when the participant "
            "first says how long they want ('20 minutes', 'half an hour', 'until "
            "3pm'), and (2) when they extend ('let's go 15 more'). `minutes_remaining` "
            "is how many more minutes from NOW. If they gave an absolute time, do the "
            "math yourself. Decimals fine. Don't call for vague answers ('whenever', "
            "'no rush') — leave the budget unset."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "minutes_remaining": {
                    "type": "number",
                    "description": "How many more minutes from now they want to spend.",
                }
            },
            "required": ["minutes_remaining"],
        },
    },
]

# Special tool names — handled in the loop, not via dispatch().
END_INTERVIEW_TOOL = "end_interview"
UPDATE_TIME_BUDGET_TOOL = "update_time_budget"


def _safe_resolve(path: str) -> Path | None:
    """Resolve `path` (relative to wiki/) and ensure it stays inside wiki/."""
    if not path:
        return None
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


def _frontmatter_title(text: str) -> str | None:
    m = re.search(r'^title:\s*"?([^"\n]+?)"?\s*$', text, re.MULTILINE)
    return m.group(1).strip() if m else None


# ---- search ----------------------------------------------------------------


def _iter_pages(type_filter: str | None = None) -> Iterable[Path]:
    if type_filter:
        sub = WIKI_DIR / _TYPE_TO_DIR.get(type_filter, "")
        if sub.is_dir():
            yield from sorted(sub.rglob("*.md"))
            return
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
    return "\n\n---\n\n".join(open_page(p) for p in paths[:8])


def follow(reference: str) -> str:
    ref = reference.strip().lstrip("/")
    for prefix in ("wiki/", "./", "./wiki/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    if ref.endswith(".md"):
        ref = ref[:-3]

    direct = _safe_resolve(ref + ".md")
    if direct:
        return open_page(ref + ".md")

    for container in CONTAINERS:
        if _safe_resolve(f"{container}/{ref}.md"):
            return open_page(f"{container}/{ref}.md")

    slug = _slugify(ref)
    if slug != ref:
        for container in CONTAINERS:
            if _safe_resolve(f"{container}/{slug}.md"):
                return open_page(f"{container}/{slug}.md")

    return f"follow: could not resolve {reference!r}"


# ---- participant: the smart bundle ----------------------------------------


@lru_cache(maxsize=1)
def _participant_index() -> dict[str, str]:
    """Map lowercased name / first-name / slug -> 'dir/slug'.

    Scans all three people layers (participants/, mentors/, team/). participants/
    is scanned first so an ambiguous bare name resolves to a fellow over a
    same-named mentor/team member. Cached (the cohort is static)."""
    index: dict[str, str] = {}
    for d in PEOPLE_DIRS:
        pdir = WIKI_DIR / d
        if not pdir.is_dir():
            continue
        for p in sorted(pdir.glob("*.md")):
            if p.stem in ("index", "auto-match-review", "matchmaker"):
                continue
            rel = f"{d}/{p.stem}"
            index.setdefault(p.stem.lower(), rel)
            index.setdefault(p.stem.replace("-", " ").lower(), rel)
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            name = _frontmatter_title(text)
            if name:
                index.setdefault(name.lower(), rel)
                parts = name.split()
                if parts:
                    index.setdefault(parts[0].lower(), rel)  # first-name fallback
    return index


@lru_cache(maxsize=1)
def _pod_table() -> dict[str, str]:
    """Map lowercased participant display-name -> pod, parsed from pods.md."""
    table: dict[str, str] = {}
    pods = WIKI_DIR / "pods.md"
    if not pods.is_file():
        return table
    for line in pods.read_text(encoding="utf-8").splitlines():
        # rows look like: | [Ben Auer](participants/ben-auer.md) | Ambitious Research Pod |
        m = re.match(r"\|\s*(?:\[([^\]]+)\]\([^)]+\)|([^|]+?))\s*\|\s*([^|]+?)\s*\|", line)
        if not m:
            continue
        name = (m.group(1) or m.group(2) or "").strip()
        pod = m.group(3).strip()
        if name and pod and pod.lower() not in ("pod", "name"):
            table[name.lower()] = pod
    return table


def participant(name_or_handle: str) -> str:
    needle = name_or_handle.strip().lower().lstrip("@")
    if not needle:
        return "participant: empty input"
    index = _participant_index()

    rel = index.get(needle)
    if not rel:
        for k, v in index.items():
            if needle in k:
                rel = v
                break
    if not rel:
        return (
            f"participant: no match for {name_or_handle!r}. "
            "Try `search` with their name to find references elsewhere in the wiki, "
            "or ask them how they'd like to be looked up."
        )

    layer, slug = rel.split("/", 1)
    page = open_page(f"{rel}.md")

    # Surface the role up front — the interviewer MUST honor the distinction
    # between a seminar fellow, a mentor, and event team (see CLAUDE.md).
    rm = re.search(r"^role:\s*(.+?)\s*$", page, re.M)
    role = (rm.group(1).strip() if rm else
            {"mentors": "mentor", "team": "event-team"}.get(layer, "participant"))
    if layer != "participants" or role not in ("participant", "visitor"):
        page = (f"**[{role} — NOT a seminar fellow. Don't suggest them as a "
                f"research collaborator or peer; surface the {role} role "
                f"explicitly.]**\n\n" + page)

    # Append pod assignment if we can find one by display name.
    pods = _pod_table()
    name = _frontmatter_title(page) or slug.replace("-", " ")
    pod = pods.get(name.lower())
    if not pod:
        for k, v in pods.items():
            if name.lower() in k or k in name.lower():
                pod = v
                break
    if pod:
        page += f"\n\n---\n\n**Pod assignment** (from wiki/pods.md): {name} → **{pod}**"
    return page


# ---- dispatcher -----------------------------------------------------------


def dispatch(name: str, params: dict) -> str:
    if name == "participant":
        return participant(params.get("name_or_handle", ""))
    if name == "search":
        return search(params.get("query", ""), params.get("type"), int(params.get("limit", 10)))
    if name == "open":
        return open_page(params.get("path", ""))
    if name == "open_many":
        return open_many(params.get("paths", []))
    if name == "follow":
        return follow(params.get("reference", ""))
    return f"unknown tool: {name}"
