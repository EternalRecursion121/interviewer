"""
Add a brief Synthesis section to each personal #*-box channel page that points
to the corresponding member page. Box channels duplicate content that's better
covered in the member page; the channel page should be a pointer plus a tiny
context note.

Idempotent — only adds the section if it isn't already there.
"""
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "raw"
WIKI = REPO / "wiki"

# Map box channel name -> the member's slug (best guess; manual override).
# Slugs computed by hand to match what build_member_pages.py produces from
# the application form's "name" column.
BOX_TO_MEMBER_SLUG = {
    "ariel-box": "ariel-cheng",
    "david-box": None,  # multiple Davids: Lieman, ?
    "eva-box": "eva",
    "georgios-box": "georgios-alexandros-vazouras",
    "harry-box": "harry-waterman",
    "james-box": "james-leung",
    "katya-box": "katya",
    "keiji-box": "keiji-imai",
    "leo-box": "leo-hammett",
    "lou-box": "lou",
    "megan-box": "megan-walker",  # not in form CSV; check
    "michael-box": "michael-domarkas",
    "muhammed-box": "muhammed-tariq",
    "oscar-box": None,  # multiple Oscars: Moxon, Schmidt, Petrov
    "pi-box": "pi",
    "pranshul-box": "pranshul-bohra",
    "samuel-box": "samuel-ratnam",
    "sudarsh-box": "sudarsh-kunnavakkam",
    "tim-box": "tim-kostolansky",
    "xi-box": "xi",
}


def load_messages():
    with open(RAW / "messages.json") as f:
        return json.load(f)


def find_member_page(slug):
    """Find an existing member page that best matches this slug."""
    if not slug:
        return None
    direct = WIKI / "members" / f"{slug}.md"
    if direct.exists():
        return direct
    # Fuzzy: match against existing member pages
    for p in (WIKI / "members").glob("*.md"):
        stem = p.stem
        if slug in stem or stem in slug:
            return p
    return None


def render_synthesis(box_name, msgs, member_page):
    authors = Counter(m["author_name"] for m in msgs)
    total = len(msgs)
    distinct = len(authors)
    owner_name = box_name.replace("-box", "").title()

    if total == 0:
        return f"## Synthesis (curated)\n\nThe channel exists but has no messages.\n"

    # Find the dominant voice
    top_author, top_count = authors.most_common(1)[0]
    is_owned_by_top = top_count > total * 0.4
    member_link = (
        f"`wiki/members/{member_page.stem}.md`"
        if member_page
        else "(no corresponding member page yet)"
    )

    lines = ["## Synthesis (curated)", ""]
    if total < 5:
        lines.append(
            f"`#{box_name}` is essentially empty — {total} message{'' if total == 1 else 's'} from {distinct} distinct author{'' if distinct == 1 else 's'}. "
            f"The channel exists as a placeholder for {owner_name}'s thinking-out-loud but hasn't been used. "
            f"See {member_link} for what is known about them through the application form and other channels."
        )
    elif total < 30:
        most_active = ", ".join(f"`{a}` ({n})" for a, n in authors.most_common(3))
        lines.append(
            f"`#{box_name}` is sparsely used — {total} messages, {distinct} authors. "
            f"Most active: {most_active}. "
            f"For substantive material on this member, see {member_link} and (if it exists) their auto-generated *Activity in Discord* and *Representative things they've said* sections."
        )
    elif is_owned_by_top:
        lines.append(
            f"`#{box_name}` is the personal thinking-out-loud channel for the member it's named after. "
            f"{total} messages, {distinct} contributors, dominated by `{top_author}` ({top_count} = {top_count*100//total}%). "
            f"The hand-curated synthesis of this content lives in the member page (under `## What they think out loud`), not duplicated here. "
            f"See {member_link}."
        )
    else:
        most_active = ", ".join(f"`{a}` ({n})" for a, n in authors.most_common(3))
        lines.append(
            f"`#{box_name}` is the channel named after one member but heavily used by others. "
            f"{total} messages, {distinct} contributors. Top three: {most_active}. "
            f"The owner is not the dominant voice here — read it as a salon, not a journal. "
            f"For the corresponding member page, see {member_link}."
        )
    lines.append("")
    return "\n".join(lines)


def main():
    messages = load_messages()
    by_channel = {}
    for m in messages:
        by_channel.setdefault(m["channel_name"], []).append(m)

    n_added = 0
    n_skipped = 0
    for box_name, slug in BOX_TO_MEMBER_SLUG.items():
        page = WIKI / "channels" / f"{box_name}.md"
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        if "## Synthesis" in text:
            n_skipped += 1
            continue

        msgs = by_channel.get(box_name, [])
        member_page = find_member_page(slug) if slug else None
        synth = render_synthesis(box_name, msgs, member_page)

        # Insert after frontmatter
        m = re.match(r"^(---\n.*?\n---\n)", text, re.DOTALL)
        if not m:
            continue
        new_text = m.group(1) + "\n" + synth + "\n" + text[m.end():]
        page.write_text(new_text, encoding="utf-8")
        n_added += 1

    print(f"added synthesis to {n_added} box channels, skipped {n_skipped} (already had synthesis)")


if __name__ == "__main__":
    main()
