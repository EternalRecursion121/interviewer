#!/usr/bin/env python3
"""One-shot consolidation: merge participants/discord/*, participants/enrichment/*,
and mentors/<slug>.md (per-person pages, not the catalog files) into a single
canonical wiki/participants/<slug>.md per person.

After running this:
  - wiki/participants/<slug>.md is the single page per person.
  - wiki/participants/discord/ and wiki/participants/enrichment/ are removed.
  - wiki/mentors/ keeps only index.md and matchmaker.md (catalogs).
  - Cross-links in mentors/index.md and mentors/matchmaker.md are rewritten
    to point at ../participants/<slug>.md.

Idempotent block markers used:
  <!-- INTRO START/END -->        — managed by build_participants.py
  <!-- ENRICHMENT START/END -->   — hand-edited web-fetched profile content
  <!-- DISCORD START/END -->      — Discord pod / activity content
  <!-- MENTOR START/END -->       — mentor-catalog content (research themes, what to bring)
  <!-- BACKLINKS START/END -->    — managed by build_backlinks.py

Run once after running build_participants.py with the new INTRO-wrapping logic.
"""

from __future__ import annotations

import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
PARTICIPANTS = WIKI / "participants"
DISCORD_DIR = PARTICIPANTS / "discord"
ENRICHMENT_DIR = PARTICIPANTS / "enrichment"
MENTORS_DIR = WIKI / "mentors"

TODAY = date.today().isoformat()

BLOCK_MARKERS = {
    "discord": ("<!-- DISCORD START -->", "<!-- DISCORD END -->"),
    "enrichment": ("<!-- ENRICHMENT START -->", "<!-- ENRICHMENT END -->"),
    "mentor": ("<!-- MENTOR START -->", "<!-- MENTOR END -->"),
}

INTRO_START = "<!-- INTRO START -->"
INTRO_END = "<!-- INTRO END -->"
BACKLINKS_START = "<!-- BACKLINKS START -->"

KEEP_IN_MENTORS = {"index.md", "matchmaker.md"}


def strip_frontmatter(md: str) -> tuple[str, str]:
    """Return (frontmatter, body). Frontmatter includes the --- delimiters."""
    m = re.match(r"^(---\n.*?\n---\n+)(.*)", md, re.S)
    if not m:
        return "", md
    return m.group(1), m.group(2)


def parse_frontmatter(fm: str) -> dict:
    out: dict = {}
    body = fm.strip().strip("-").strip()
    for line in body.splitlines():
        if ":" in line and not line.lstrip().startswith("-"):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def collect_sources(md_files: list[Path]) -> list[str]:
    out: list[str] = []
    for p in md_files:
        if not p.exists():
            continue
        fm, _ = strip_frontmatter(p.read_text(encoding="utf-8"))
        in_sources = False
        for line in fm.splitlines():
            if re.match(r"^sources:\s*$", line):
                in_sources = True
                continue
            if in_sources:
                m = re.match(r"^\s*-\s+(.*)$", line)
                if m:
                    out.append(m.group(1).strip())
                else:
                    in_sources = False
    seen = set()
    deduped = []
    for s in out:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
    return deduped


def upsert_block(
    path: Path,
    block_key: str,
    body: str,
    *,
    section_heading: str | None = None,
) -> None:
    """Insert or replace a delimited block on a participant page.
    Block placement order (top→bottom): INTRO, ENRICHMENT, DISCORD, MENTOR, BACKLINKS."""
    start, end = BLOCK_MARKERS[block_key]
    body = body.strip()
    if section_heading:
        wrapped = f"{start}\n\n{section_heading}\n\n{body}\n\n{end}\n"
    else:
        wrapped = f"{start}\n\n{body}\n\n{end}\n"

    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    if start in existing and end in existing:
        new = re.sub(
            rf"{re.escape(start)}.*?{re.escape(end)}\n*",
            wrapped,
            existing,
            count=1,
            flags=re.S,
        )
        path.write_text(new, encoding="utf-8")
        return

    insertion_anchor = None
    if block_key == "enrichment":
        insertion_anchor = INTRO_END
    elif block_key == "discord":
        for anchor_key in ("enrichment",):
            _, anchor_end = BLOCK_MARKERS[anchor_key]
            if anchor_end in existing:
                insertion_anchor = anchor_end
                break
        if insertion_anchor is None:
            insertion_anchor = INTRO_END
    elif block_key == "mentor":
        for anchor_key in ("discord", "enrichment"):
            _, anchor_end = BLOCK_MARKERS[anchor_key]
            if anchor_end in existing:
                insertion_anchor = anchor_end
                break
        if insertion_anchor is None:
            insertion_anchor = INTRO_END

    if insertion_anchor and insertion_anchor in existing:
        idx = existing.index(insertion_anchor) + len(insertion_anchor)
        new = existing[:idx] + "\n\n" + wrapped + existing[idx:].lstrip("\n")
        path.write_text(new, encoding="utf-8")
        return

    if BACKLINKS_START in existing:
        idx = existing.index(BACKLINKS_START)
        new = existing[:idx].rstrip() + "\n\n" + wrapped + "\n" + existing[idx:]
        path.write_text(new, encoding="utf-8")
        return

    if existing:
        new = existing.rstrip() + "\n\n" + wrapped
    else:
        new = wrapped
    path.write_text(new, encoding="utf-8")


def update_sources(path: Path, new_sources: list[str]) -> None:
    """Merge new_sources into the page's frontmatter sources: list."""
    md = path.read_text(encoding="utf-8")
    fm, body = strip_frontmatter(md)
    if not fm:
        return

    existing_lines = fm.splitlines()
    new_lines: list[str] = []
    i = 0
    sources_existing: list[str] = []
    sources_block_range: tuple[int, int] | None = None
    while i < len(existing_lines):
        line = existing_lines[i]
        if re.match(r"^sources:\s*$", line):
            start_i = i
            i += 1
            while i < len(existing_lines):
                m = re.match(r"^\s*-\s+(.*)$", existing_lines[i])
                if m:
                    sources_existing.append(m.group(1).strip())
                    i += 1
                else:
                    break
            sources_block_range = (start_i, i)
            break
        i += 1

    merged: list[str] = []
    seen: set[str] = set()
    for s in sources_existing + new_sources:
        s = s.strip()
        if s and s not in seen:
            seen.add(s)
            merged.append(s)

    if sources_block_range is None:
        rebuilt = (
            existing_lines
            + ["sources:"]
            + [f"  - {s}" for s in merged]
        )
    else:
        sb, se = sources_block_range
        rebuilt = (
            existing_lines[:sb]
            + ["sources:"]
            + [f"  - {s}" for s in merged]
            + existing_lines[se:]
        )

    rebuilt = [
        re.sub(r"^last_updated:.*$", f"last_updated: {TODAY}", line)
        for line in rebuilt
    ]

    new_fm = "\n".join(rebuilt) + "\n"
    if not new_fm.startswith("---\n"):
        new_fm = "---\n" + new_fm
    if not new_fm.rstrip().endswith("---"):
        new_fm = new_fm.rstrip() + "\n---\n"
    new_fm += "\n"
    path.write_text(new_fm + body, encoding="utf-8")


def extract_body_without_frontmatter(md: str) -> str:
    _, body = strip_frontmatter(md)
    return body.strip()


def fix_relative_links_for_participants(body: str, from_dir: Path) -> str:
    """Rewrite relative links so they resolve from wiki/participants/<slug>.md.
    from_dir is the original location (e.g. wiki/participants/discord/)."""
    def rewrite(match: re.Match) -> str:
        label = match.group(1)
        url = match.group(2)
        if "://" in url or url.startswith("#") or url.startswith("/"):
            return match.group(0)
        if not url.endswith(".md") and "/" not in url and ".md#" not in url:
            return match.group(0)
        prefix_count = 0
        u = url
        while u.startswith("../"):
            prefix_count += 1
            u = u[3:]
        if from_dir == DISCORD_DIR:
            if prefix_count == 3:
                u_new = u
            elif prefix_count == 2:
                u_new = f"../{u}"
            elif prefix_count == 1:
                if u.startswith("concepts/") or u.startswith("themes/") or u.startswith("talks/") or u.startswith("mentors/") or u.startswith("tags/"):
                    u_new = f"../{u}"
                else:
                    u_new = u
            else:
                u_new = url
        elif from_dir == ENRICHMENT_DIR:
            if prefix_count == 2:
                u_new = u
            elif prefix_count == 1:
                u_new = u if not (u.startswith("concepts/") or u.startswith("themes/") or u.startswith("talks/")) else f"../{u}"
            else:
                u_new = url
        elif from_dir == MENTORS_DIR:
            if prefix_count == 1:
                if u.startswith("participants/"):
                    u_new = u.replace("participants/", "")
                else:
                    u_new = f"../{u}"
            elif prefix_count == 2:
                u_new = u
            else:
                u_new = url
        else:
            u_new = url
        return f"[{label}]({u_new})"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", rewrite, body)


def role_for_discord_only(slug: str, body: str) -> str:
    body_lower = body.lower()
    if "mentor" in body_lower and ("interp" in body_lower or "facilitator" in body_lower):
        return "external-speaker"
    if "facilitator" in body_lower or "lecturer" in body_lower:
        return "external-speaker"
    return "participant"


def consolidate_one(slug: str, person_name: str) -> dict:
    """Returns a dict describing what was merged for this person."""
    intro_path = PARTICIPANTS / f"{slug}.md"
    discord_path = DISCORD_DIR / f"{slug}.md"
    enrichment_path = ENRICHMENT_DIR / f"{slug}.md"
    mentor_path = MENTORS_DIR / f"{slug}.md"

    has_intro = intro_path.exists()
    has_discord = discord_path.exists()
    has_enrichment = enrichment_path.exists()
    has_mentor = mentor_path.exists()

    new_sources: list[str] = []
    if has_discord:
        new_sources.append("raw/discord/affine_participants_raw.md")
        new_sources.append("raw/discord/affine_alignment_questions_channel.md")
    if has_enrichment:
        new_sources.append("(web-fetched profile content; see ENRICHMENT block for URLs)")
    if has_mentor:
        new_sources.append("wiki/mentors/<self>")
        new_sources.append("raw/sheet/Resources.csv")

    if not has_intro:
        title = person_name
        primary_source = None
        body_source_paths: list[tuple[str, Path]] = []
        if has_discord:
            body_source_paths.append(("discord", discord_path))
            primary_source = "raw/discord/affine_participants_raw.md"
        if has_mentor:
            body_source_paths.append(("mentor", mentor_path))
            if not primary_source:
                primary_source = "wiki/mentors/<self>"
        if has_enrichment:
            body_source_paths.append(("enrichment", enrichment_path))

        first_body = body_source_paths[0][1].read_text(encoding="utf-8")
        first_fm, _ = strip_frontmatter(first_body)
        fm_data = parse_frontmatter(first_fm)
        role = fm_data.get("role") or "discord-only"
        if has_mentor and not has_discord:
            role = "external-speaker"
        if has_mentor and has_discord:
            role = "external-speaker"

        first_body_text = extract_body_without_frontmatter(first_body)
        if not first_body_text.startswith("# "):
            first_body_text = f"# {title}\n\n{first_body_text}"

        stub_fm = "\n".join([
            "---",
            f"title: {title}",
            "type: participant",
            f"role: {role}",
            "sources:",
            *[f"  - {s}" for s in new_sources],
            f"last_updated: {TODAY}",
            "---",
            "",
        ])

        intro_body = (
            f"# {title}\n\n"
            f"_No self-introduction on file. This page is assembled from "
            f"{'Discord, ' if has_discord else ''}"
            f"{'mentor catalog, ' if has_mentor else ''}"
            f"{'web-fetched profile ' if has_enrichment else ''}"
            f"sources. The interviewer should treat the absence of a self-intro "
            f"as significant: ask open questions rather than reflecting back stated motivations._\n"
        )
        intro_path.write_text(
            stub_fm + f"{INTRO_START}\n{intro_body.strip()}\n{INTRO_END}\n",
            encoding="utf-8",
        )

    else:
        update_sources(intro_path, new_sources)

    if has_enrichment:
        body = enrichment_path.read_text(encoding="utf-8")
        body = extract_body_without_frontmatter(body)
        body = fix_relative_links_for_participants(body, ENRICHMENT_DIR)
        upsert_block(intro_path, "enrichment", body, section_heading="## Public-artifact enrichment")

    if has_discord:
        body = discord_path.read_text(encoding="utf-8")
        body = extract_body_without_frontmatter(body)
        body = fix_relative_links_for_participants(body, DISCORD_DIR)
        upsert_block(intro_path, "discord", body, section_heading="## Discord activity")

    if has_mentor:
        body = mentor_path.read_text(encoding="utf-8")
        body = extract_body_without_frontmatter(body)
        body = fix_relative_links_for_participants(body, MENTORS_DIR)
        upsert_block(intro_path, "mentor", body, section_heading="## Mentor catalog entry")

    return {
        "slug": slug,
        "name": person_name,
        "intro": has_intro,
        "discord": has_discord,
        "enrichment": has_enrichment,
        "mentor": has_mentor,
    }


def discover_all_people() -> dict[str, str]:
    """Return slug → display_name for every person across all four sources."""
    out: dict[str, str] = {}

    for path in PARTICIPANTS.glob("*.md"):
        if path.name in {"index.md", "auto-match-review.md"}:
            continue
        if path.is_dir():
            continue
        md = path.read_text(encoding="utf-8")
        fm, _ = strip_frontmatter(md)
        fm_data = parse_frontmatter(fm)
        out[path.stem] = fm_data.get("title", path.stem)

    for path in DISCORD_DIR.glob("*.md"):
        if path.name == "index.md":
            continue
        md = path.read_text(encoding="utf-8")
        fm, _ = strip_frontmatter(md)
        fm_data = parse_frontmatter(fm)
        slug = path.stem
        if slug not in out:
            out[slug] = fm_data.get("title", slug)

    for path in ENRICHMENT_DIR.glob("*.md"):
        if path.name == "index.md":
            continue
        md = path.read_text(encoding="utf-8")
        fm, _ = strip_frontmatter(md)
        fm_data = parse_frontmatter(fm)
        slug = path.stem
        if slug not in out:
            out[slug] = fm_data.get("title", slug)

    for path in MENTORS_DIR.glob("*.md"):
        if path.name in KEEP_IN_MENTORS:
            continue
        md = path.read_text(encoding="utf-8")
        fm, _ = strip_frontmatter(md)
        fm_data = parse_frontmatter(fm)
        slug = path.stem
        if slug not in out:
            out[slug] = fm_data.get("title", slug)

    return out


def rewrite_mentor_catalog_links() -> None:
    for filename in KEEP_IN_MENTORS:
        path = MENTORS_DIR / filename
        if not path.exists():
            continue
        md = path.read_text(encoding="utf-8")
        new = re.sub(
            r"\]\(([a-z0-9-]+)\.md\)",
            r"](../participants/\1.md)",
            md,
        )
        new = re.sub(
            r"\]\(\./([a-z0-9-]+)\.md\)",
            r"](../participants/\1.md)",
            new,
        )
        if new != md:
            path.write_text(new, encoding="utf-8")


def delete_per_person_mentor_pages() -> None:
    for path in MENTORS_DIR.glob("*.md"):
        if path.name in KEEP_IN_MENTORS:
            continue
        path.unlink()


def remove_subdirs() -> None:
    if DISCORD_DIR.exists():
        shutil.rmtree(DISCORD_DIR)
    if ENRICHMENT_DIR.exists():
        shutil.rmtree(ENRICHMENT_DIR)


def main() -> None:
    if not PARTICIPANTS.exists():
        print("Participants dir missing — aborting.")
        sys.exit(1)

    people = discover_all_people()
    print(f"Discovered {len(people)} unique people across all four source folders.")

    report: list[dict] = []
    for slug, name in sorted(people.items()):
        info = consolidate_one(slug, name)
        report.append(info)

    rewrite_mentor_catalog_links()
    delete_per_person_mentor_pages()
    remove_subdirs()

    print()
    print(f"Wrote {len(report)} canonical participant pages at wiki/participants/<slug>.md.")
    intro_count = sum(1 for r in report if r["intro"])
    discord_count = sum(1 for r in report if r["discord"])
    enrichment_count = sum(1 for r in report if r["enrichment"])
    mentor_count = sum(1 for r in report if r["mentor"])
    print(f"  intro pages merged: {intro_count}")
    print(f"  discord blocks merged: {discord_count}")
    print(f"  enrichment blocks merged: {enrichment_count}")
    print(f"  mentor blocks merged: {mentor_count}")

    print()
    print("New: discord-only / external-speaker / mentor-only people (no intro form):")
    for r in report:
        if not r["intro"]:
            srcs = []
            if r["discord"]:
                srcs.append("discord")
            if r["enrichment"]:
                srcs.append("enrichment")
            if r["mentor"]:
                srcs.append("mentor")
            print(f"  - {r['name']} ({r['slug']}) — from {'+'.join(srcs)}")

    print()
    print("Removed: wiki/participants/discord/, wiki/participants/enrichment/, individual mentor pages.")
    print("Kept:    wiki/mentors/index.md, wiki/mentors/matchmaker.md (catalogs).")


if __name__ == "__main__":
    main()
