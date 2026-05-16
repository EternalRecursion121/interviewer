#!/usr/bin/env python3
"""Generate wiki/concepts/, wiki/tags/, wiki/tree.md from raw/sheet/*.csv.

Deterministic — re-running overwrites generated pages.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "sheet"
WIKI = ROOT / "wiki"
TODAY = date.today().isoformat()


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def split_resource_names(raw: str) -> list[str]:
    """Replicates splitResourceNames from src/scripts/sync-topics.ts.

    Resources field is a comma-separated list of resource names, but the names
    themselves may be quoted (to protect embedded commas), and quotes inside
    quoted names are doubled.
    """
    if not raw.strip():
        return []
    inside = False
    last = 0
    parts: list[str] = []
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == '"':
            if i + 1 < len(raw) and raw[i + 1] == '"':
                i += 2
                continue
            inside = not inside
        elif not inside and c == ",":
            parts.append(raw[last:i])
            last = i + 1
        i += 1
    if last < len(raw):
        parts.append(raw[last:])
    out: list[str] = []
    for p in parts:
        s = re.sub(r"^,?\s*", "", p)
        s = re.sub(r",?\s*$", "", s).strip()
        if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
            s = s[1:-1]
        s = s.replace('""', '"')
        if s:
            out.append(s)
    return out


def parse_tags(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [t.strip() for t in re.split(r"[,/]", raw) if t.strip()]


def parse_prereqs(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def read_topics() -> list[dict]:
    with (RAW / "Topics.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for i, row in enumerate(rows, start=2):  # row 1 is the header in the CSV
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "row": i,
                "name": name,
                "description": (row.get("Description") or "").strip(),
                "guidance": (row.get("Guidance") or "").strip(),
                "resources": split_resource_names(row.get("Resources") or ""),
                "tags": parse_tags(row.get("Tags") or ""),
                "prereqs": parse_prereqs(row.get("Prerequisites") or ""),
                "importance": int(float((row.get("Importance") or "0").strip() or 0)),
            }
        )
    return out


def read_resources() -> dict[str, dict]:
    with (RAW / "Resources.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict] = {}
    for i, row in enumerate(rows, start=2):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        out[name] = {
            "row": i,
            "url": (row.get("Link") or "").strip(),
            "author": (row.get("Author") or "").strip().replace("\n", ", "),
            "comment": (row.get("Comments") or "").strip(),
        }
    return out


def read_tags() -> dict[str, dict]:
    with (RAW / "Topic_tags.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: dict[str, dict] = {}
    for i, row in enumerate(rows, start=2):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        out[name] = {
            "row": i,
            "description": (row.get("Description") or "").strip(),
        }
    return out


def write_concept_page(t: dict, resources: dict[str, dict], all_slugs: dict[str, str], dependents: dict[str, list[str]]) -> None:
    slug = all_slugs[t["name"]]
    path = WIKI / "concepts" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    fm = [
        "---",
        f"title: {t['name']}",
        "type: concept",
        f"tags: [{', '.join(t['tags'])}]",
        "sources:",
        f"  - raw/sheet/Topics.csv  # row {t['row']}",
        f"last_updated: {TODAY}",
        "generated: true  # by build_wiki/build_concepts.py — do not hand-edit",
        "---",
        "",
        f"# {t['name']}",
        "",
    ]

    body: list[str] = []

    if t["description"]:
        body.append(t["description"])
        body.append("")
    else:
        body.append("_(No description in the sheet yet.)_")
        body.append("")

    if t["guidance"]:
        body.append("## Reading guidance")
        body.append("")
        body.append(t["guidance"])
        body.append("")

    if t["tags"]:
        body.append("## Tags")
        body.append("")
        for tag in t["tags"]:
            body.append(f"- [{tag}](../tags/{slugify(tag)}.md)")
        body.append("")

    if t["prereqs"]:
        body.append("## Prerequisites")
        body.append("")
        for p in t["prereqs"]:
            if p in all_slugs:
                body.append(f"- [{p}]({all_slugs[p]}.md)")
            else:
                body.append(f"- {p} _(not in sheet)_")
        body.append("")

    deps = dependents.get(t["name"], [])
    if deps:
        body.append("## Builds toward")
        body.append("")
        for d in sorted(deps):
            body.append(f"- [{d}]({all_slugs[d]}.md)")
        body.append("")

    if t["resources"]:
        body.append("## Resources")
        body.append("")
        for r in t["resources"]:
            info = resources.get(r)
            if info and info["url"]:
                line = f"- [{r}]({info['url']})"
            else:
                line = f"- {r}"
            if info and info["author"]:
                line += f" — {info['author']}"
            body.append(line)
            if info and info["comment"]:
                body.append(f"  - _{info['comment']}_")
        body.append("")

    body.append("---")
    body.append("")
    body.append(f"_Source: row {t['row']} of [`raw/sheet/Topics.csv`](../../raw/sheet/Topics.csv)._")
    body.append("")

    path.write_text("\n".join(fm + body), encoding="utf-8")


def write_tag_page(tag_name: str, info: dict, members: list[dict], all_slugs: dict[str, str]) -> None:
    slug = slugify(tag_name)
    path = WIKI / "tags" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    members_sorted = sorted(members, key=lambda t: t["name"].lower())

    fm = [
        "---",
        f"title: {tag_name}",
        "type: tag",
        "sources:",
        f"  - raw/sheet/Topic_tags.csv  # row {info.get('row', '?')}",
        "  - raw/sheet/Topics.csv",
        f"last_updated: {TODAY}",
        "generated: true",
        "---",
        "",
        f"# {tag_name}",
        "",
    ]

    body: list[str] = []
    if info.get("description"):
        body.append(info["description"])
        body.append("")

    body.append(f"## Topics tagged `{tag_name}` ({len(members_sorted)})")
    body.append("")
    for t in members_sorted:
        body.append(f"- [{t['name']}](../concepts/{all_slugs[t['name']]}.md)")
    body.append("")

    path.write_text("\n".join(fm + body), encoding="utf-8")


def write_tree(topics: list[dict], tag_order: list[str], tags: dict[str, dict], all_slugs: dict[str, str]) -> None:
    """A bullet tree grouped by tag, with prerequisite chains nested under their roots within each tag."""
    by_tag: dict[str, list[dict]] = defaultdict(list)
    untagged: list[dict] = []
    for t in topics:
        if not t["tags"]:
            untagged.append(t)
        else:
            for tg in t["tags"]:
                by_tag[tg].append(t)

    lines: list[str] = []
    lines.append("---")
    lines.append("title: AFFINE concept tree")
    lines.append("type: overview")
    lines.append("sources:")
    lines.append("  - raw/sheet/Topics.csv")
    lines.append("  - raw/sheet/Topic_tags.csv")
    lines.append(f"last_updated: {TODAY}")
    lines.append("generated: true")
    lines.append("---")
    lines.append("")
    lines.append("# AFFINE concept tree")
    lines.append("")
    lines.append("All alignment concepts in the AFFINE tech tree, grouped by their top-level tag.")
    lines.append("A concept may appear under more than one tag.")
    lines.append("")
    lines.append("The same data renders as an interactive prerequisite graph at <https://learn.affi.ne/graph>.")
    lines.append("")

    for tag_name in tag_order:
        members = by_tag.get(tag_name, [])
        if not members:
            continue
        info = tags.get(tag_name, {})
        lines.append(f"## [{tag_name}](tags/{slugify(tag_name)}.md)")
        lines.append("")
        if info.get("description"):
            lines.append(f"_{info['description']}_")
            lines.append("")
        for t in sorted(members, key=lambda t: t["name"].lower()):
            slug = all_slugs[t["name"]]
            prereqs = [p for p in t["prereqs"] if p in all_slugs]
            line = f"- [{t['name']}](concepts/{slug}.md)"
            if prereqs:
                line += "  — prereqs: " + ", ".join(
                    f"[{p}](concepts/{all_slugs[p]}.md)" for p in prereqs
                )
            lines.append(line)
        lines.append("")

    other_tags = sorted(t for t in by_tag if t not in tag_order)
    if other_tags:
        lines.append("## Other tags")
        lines.append("")
        for tag_name in other_tags:
            lines.append(f"### [{tag_name}](tags/{slugify(tag_name)}.md)")
            lines.append("")
            for t in sorted(by_tag[tag_name], key=lambda t: t["name"].lower()):
                lines.append(f"- [{t['name']}](concepts/{all_slugs[t['name']]}.md)")
            lines.append("")

    if untagged:
        lines.append("## Untagged")
        lines.append("")
        for t in sorted(untagged, key=lambda t: t["name"].lower()):
            lines.append(f"- [{t['name']}](concepts/{all_slugs[t['name']]}.md)")
        lines.append("")

    (WIKI / "tree.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    topics = read_topics()
    resources = read_resources()
    tags = read_tags()

    all_slugs = {t["name"]: slugify(t["name"]) for t in topics}

    # collision check
    seen: dict[str, str] = {}
    for name, slug in all_slugs.items():
        if slug in seen:
            raise SystemExit(f"slug collision: {slug!r} from {name!r} and {seen[slug]!r}")
        seen[slug] = name

    # drop self-prereqs (the sheet has a few of these)
    for t in topics:
        t["prereqs"] = [p for p in t["prereqs"] if p != t["name"]]

    dependents: dict[str, list[str]] = defaultdict(list)
    for t in topics:
        for p in t["prereqs"]:
            if p in all_slugs:
                dependents[p].append(t["name"])

    # collect tags actually used by topics
    used_tags: set[str] = set()
    for t in topics:
        used_tags.update(t["tags"])

    # tag pages
    by_tag: dict[str, list[dict]] = defaultdict(list)
    for t in topics:
        for tg in t["tags"]:
            by_tag[tg].append(t)
    for tag_name in used_tags:
        write_tag_page(tag_name, tags.get(tag_name, {}), by_tag[tag_name], all_slugs)

    # concept pages
    for t in topics:
        write_concept_page(t, resources, all_slugs, dependents)

    # tree
    tag_order = ["Basics", "Foundations", "Outer Alignment", "Obstruction", "Meta"]
    write_tree(topics, tag_order, tags, all_slugs)

    print(
        f"Generated {len(topics)} concepts, {len(used_tags)} tag pages, tree.md."
    )


if __name__ == "__main__":
    main()
