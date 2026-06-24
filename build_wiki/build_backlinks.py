#!/usr/bin/env python3
"""Append a "People interested in this concept" backlinks section to each concept page.

Reads wiki/participants/*.md, finds the auto-matched "Related concepts" links each
page contains, and groups by concept. Then rewrites each concept page's tail to
include the backlinks. Idempotent — strips any previous backlinks block before
re-adding.

Run order:
    1) build_wiki/build_concepts.py
    2) build_wiki/build_participants.py
    3) build_wiki/build_backlinks.py   (this)
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARTICIPANTS = ROOT / "wiki" / "participants"
CONCEPTS = ROOT / "wiki" / "concepts"
THEMES = ROOT / "wiki" / "themes"
TALKS = ROOT / "wiki" / "talks"

# Marker block we manage. Anything inside is replaced on rerun.
MARKER_START = "<!-- BACKLINKS START -->"
MARKER_END = "<!-- BACKLINKS END -->"


def extract_concept_links(participant_md: str) -> list[str]:
    """Return concept slugs linked from a participant page."""
    # Lines of form: - [Name](../concepts/<slug>.md)
    return list(set(re.findall(r"\(\.\./concepts/([a-z0-9-]+)\.md\)", participant_md)))


def participant_name(participant_md: str, fallback_slug: str) -> str:
    m = re.search(r"^title:\s*(.+?)\s*$", participant_md, re.M)
    if m:
        return m.group(1)
    m = re.search(r"^#\s+(.+?)\s*$", participant_md, re.M)
    if m:
        return m.group(1)
    return fallback_slug


def participant_role(participant_md: str) -> str:
    m = re.search(r"^role:\s*(.+?)\s*$", participant_md, re.M)
    return m.group(1) if m else "participant"


def collect() -> dict[str, list[dict]]:
    """concept_slug → [{slug, name, role}, ...]"""
    out: dict[str, list[dict]] = defaultdict(list)
    for dirname in ("participants", "mentors", "team"):
        ddir = ROOT / "wiki" / dirname
        if not ddir.is_dir():
            continue
        for path in sorted(ddir.glob("*.md")):
            if path.name in ("index.md", "auto-match-review.md", "matchmaker.md"):
                continue
            md = path.read_text(encoding="utf-8")
            for cslug in extract_concept_links(md):
                out[cslug].append(
                    {
                        "slug": path.stem,
                        "name": participant_name(md, path.stem),
                        "role": participant_role(md),
                        "dir": dirname,
                    }
                )
    return out


def collect_theme_links() -> dict[str, list[dict]]:
    """concept_slug → [{slug, title}, ...] from themes that link the concept."""
    out: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(THEMES.glob("*.md")):
        md = path.read_text(encoding="utf-8")
        slugs = set(re.findall(r"\(\.\./concepts/([a-z0-9-]+)\.md\)", md))
        if not slugs:
            continue
        m = re.search(r"^title:\s*(.+?)\s*$", md, re.M)
        title = m.group(1) if m else path.stem
        for cslug in slugs:
            out[cslug].append({"slug": path.stem, "title": title})
    return out


def collect_talk_links() -> dict[str, list[dict]]:
    """concept_slug → [{slug, title, speaker}, ...] from talks that link the concept."""
    out: dict[str, list[dict]] = defaultdict(list)
    if not TALKS.exists():
        return out
    for path in sorted(TALKS.glob("*.md")):
        if path.name in {"index.md", "by-speaker.md"}:
            continue
        md = path.read_text(encoding="utf-8")
        slugs = set(re.findall(r"\(\.\./concepts/([a-z0-9-]+)\.md\)", md))
        if not slugs:
            continue
        m = re.search(r"^title:\s*(.+?)\s*$", md, re.M)
        title = m.group(1) if m else path.stem
        sm = re.search(r"^speaker:\s*(.+?)\s*$", md, re.M)
        speaker = sm.group(1) if sm else ""
        for cslug in slugs:
            out[cslug].append({"slug": path.stem, "title": title, "speaker": speaker})
    return out


def render_block(
    concept_slug: str,
    participants: list[dict],
    themes: list[dict],
    talks: list[dict],
) -> str:
    lines = [MARKER_START, "", "## Backlinks", ""]
    if participants:
        # Group by role
        by_role: dict[str, list[dict]] = defaultdict(list)
        for p in participants:
            by_role[p["role"]].append(p)
        order = ["participant", "mentor", "event-team", "visitor"]
        pretty = {
            "participant": "Participants interested",
            "mentor": "Mentors who could discuss this",
            "event-team": "Event team members who flagged this",
            "visitor": "Visitors interested",
        }
        for role in order + [r for r in by_role if r not in order]:
            ppl = by_role.get(role, [])
            if not ppl:
                continue
            label = pretty.get(role, role.title())
            lines.append(f"### {label}")
            lines.append("")
            for p in sorted(ppl, key=lambda p: p["name"].lower()):
                lines.append(f"- [{p['name']}](../{p.get('dir', 'participants')}/{p['slug']}.md)")
            lines.append("")
    if themes:
        lines.append("### Themes that touch this concept")
        lines.append("")
        for t in sorted(themes, key=lambda t: t["title"].lower()):
            lines.append(f"- [{t['title']}](../themes/{t['slug']}.md)")
        lines.append("")
    if talks:
        lines.append("### Talks that touch this concept")
        lines.append("")
        for t in sorted(talks, key=lambda t: t["title"].lower()):
            suffix = f" — {t['speaker']}" if t.get("speaker") and t["speaker"].lower() != "unknown" else ""
            lines.append(f"- [{t['title']}](../talks/{t['slug']}.md){suffix}")
        lines.append("")
    lines.append("_Backlinks are auto-generated by `build_wiki/build_backlinks.py`._")
    lines.append("")
    lines.append(MARKER_END)
    return "\n".join(lines)


def upsert_backlinks(concept_path: Path, block: str) -> None:
    md = concept_path.read_text(encoding="utf-8")
    # Strip any existing block.
    md = re.sub(
        rf"\n*{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}\n*",
        "\n",
        md,
        flags=re.S,
    )
    if not md.endswith("\n"):
        md += "\n"
    md = md.rstrip() + "\n\n" + block + "\n"
    concept_path.write_text(md, encoding="utf-8")


def main() -> None:
    concept_to_participants = collect()
    concept_to_themes = collect_theme_links()
    concept_to_talks = collect_talk_links()
    touched = 0
    cleared = 0
    for path in sorted(CONCEPTS.glob("*.md")):
        slug = path.stem
        participants = concept_to_participants.get(slug, [])
        themes = concept_to_themes.get(slug, [])
        talks = concept_to_talks.get(slug, [])
        if not participants and not themes and not talks:
            md = path.read_text(encoding="utf-8")
            new = re.sub(
                rf"\n*{re.escape(MARKER_START)}.*?{re.escape(MARKER_END)}\n*",
                "\n",
                md,
                flags=re.S,
            )
            if new != md:
                path.write_text(new, encoding="utf-8")
                cleared += 1
            continue
        block = render_block(slug, participants, themes, talks)
        upsert_backlinks(path, block)
        touched += 1

    print(
        f"Added backlinks to {touched} concept pages. Cleared stale blocks from {cleared}."
    )


if __name__ == "__main__":
    main()
