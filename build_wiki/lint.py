"""
Lint the wiki for the issues that hurt the interviewer most:

  - pages with no `sources:` line in their frontmatter
  - member pages that don't trace back to a real applicant or member
  - broken internal wiki links (./path/to/page.md that doesn't exist)
  - pages over 1500 words (karpathy threshold for splitting)
  - pages last_updated more than 90 days ago

Read-only. Prints findings; does not edit files.
"""
import csv
import re
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WIKI = REPO / "wiki"
RAW = REPO / "raw"

FM = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
LINK = re.compile(r"]\((\.\/[^)]+\.md)\)")


def normalize_name(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def known_member_names():
    names = set()
    with open(RAW / "application_responses.csv") as f:
        for row in csv.DictReader(f):
            n = (row.get("name") or "").strip()
            if n:
                names.add(normalize_name(n))
    with open(RAW / "members.csv") as f:
        for row in csv.DictReader(f):
            n = (row.get("name") or "").strip()
            if n:
                names.add(normalize_name(n))
    return names


def main():
    issues: list[str] = []
    pages = list(WIKI.rglob("*.md"))
    page_set = {p.relative_to(WIKI).as_posix() for p in pages}
    members = known_member_names()

    for p in pages:
        rel = p.relative_to(WIKI).as_posix()
        text = p.read_text(encoding="utf-8")

        m = FM.match(text)
        if not m:
            issues.append(f"{rel}: no frontmatter")
            continue
        front = m.group(1)
        if "sources:" not in front and rel not in {"index.md", "log.md"}:
            issues.append(f"{rel}: no `sources:` in frontmatter")

        # Member pages must trace back to a real person
        if rel.startswith("members/"):
            slug_norm = normalize_name(Path(rel).stem)
            if slug_norm not in members and not any(slug_norm in n or n in slug_norm for n in members):
                issues.append(f"{rel}: member name '{slug_norm}' not in raw/application_responses.csv or raw/members.csv")

        # Broken internal links
        body = text[m.end():] if m else text
        for link in LINK.findall(body):
            target = (Path(rel).parent / link[2:]).as_posix()
            target_clean = re.sub(r"\.\./", "", target)  # rough resolve; works for nearby links
            if target_clean not in page_set and link[2:] not in page_set:
                issues.append(f"{rel}: link to non-existent page '{link}'")

        # Word count — skip auto-generated/append-only files. Member pages get
        # a wider budget because they accumulate quotes from the member's posts.
        words = len(body.split())
        is_auto = rel in {"index.md", "log.md"} or rel.startswith("channels/")
        cap = 2500 if rel.startswith("members/") else 1500
        if words > cap and not is_auto:
            issues.append(f"{rel}: {words} words (>{cap}); consider splitting")

        # Stale
        m_lu = re.search(r"last_updated:\s*(\d{4}-\d{2}-\d{2})", front)
        if m_lu:
            d = datetime.strptime(m_lu.group(1), "%Y-%m-%d")
            if datetime.now() - d > timedelta(days=90):
                issues.append(f"{rel}: last_updated {m_lu.group(1)} (>90d)")

    if not issues:
        print("clean — no issues")
    else:
        print(f"{len(issues)} issues:")
        for i in issues:
            print(f"  - {i}")


if __name__ == "__main__":
    main()
