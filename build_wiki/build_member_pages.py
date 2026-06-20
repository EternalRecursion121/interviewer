"""
Build wiki/members/*.md from raw/application_responses.csv joined with
raw/members.csv and raw/messages.json.

Deterministic structured extraction — no LLM calls, no hallucination surface.
The wiki entry for each member is built from material the member themselves
provided (their application form, their public site, their public messages).
"""
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "raw"
WIKI_MEMBERS = REPO / "wiki" / "members"


def slugify(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return s or "anonymous"


def load_application_responses():
    rows = []
    with open(RAW / "application_responses.csv") as f:
        for i, row in enumerate(csv.DictReader(f), start=2):  # row 2 = first data row
            row["_csv_row"] = i
            rows.append(row)
    return rows


def load_members_csv():
    by_name = {}
    with open(RAW / "members.csv") as f:
        for row in csv.DictReader(f):
            n = (row.get("name") or "").strip()
            if n:
                by_name[n.lower()] = (row.get("url") or "").strip()
    return by_name


def load_messages():
    with open(RAW / "messages.json") as f:
        return json.load(f)


def build_discord_to_name(application_rows):
    m = {}
    for row in application_rows:
        du = (row.get("discord username") or "").strip()
        nm = (row.get("name") or "").strip()
        if du and nm:
            m[du.lower()] = nm
    # Confident manual additions verified from intros / patterns
    m["eternalrecursion"] = "Samuel Ratnam"
    m["megelia"] = "Megan Walker"
    m["victiny1223"] = "Xi"
    m["lavender1729"] = "sudarsh kunnavakkam"
    m["_archimedean"] = "Georgios Alexandros Vazouras"
    m["logaems"] = "Lou"
    m["jassamyen"] = "Jasmine"
    m["silverflute"] = "Lydia Nottingham"          # self-intro in #intros
    m["currentlystillasleep"] = "Ariel Cheng"      # confirmed by user 2026-05-09
    m["dkgto"] = "Daniel Kiss"
    return m


def build_name_to_discord(discord_to_name):
    out = {v.lower(): k for k, v in discord_to_name.items()}
    # Aliases for members whose form name differs from the canonical name
    # in raw/members.csv. The form name on the left, the canonical (full) name
    # we already have a discord mapping for on the right.
    aliases = {
        "megan": "megelia",  # form has "megan", her handle is "megelia"
        "xi": "victiny1223",
        "lou": "logaems",
    }
    for alias, handle in aliases.items():
        out[alias] = handle
    return out


# Members who have changed their handle, or whose application form lists a
# different identifier than their actual server handle. Lookups should query the
# union — these handles all map to the same person.
HANDLE_ALIASES = {
    "adellama75": ["adellama75", "adellama_"],   # Ada renamed mid-history
    "adellama_": ["adellama75", "adellama_"],
    "m0x0n": ["m0x0n", "moxonsmoke"],            # Oscar Moxon — form vs actual
    # silverflute confirmed = Lydia Nottingham. See wiki/themes/identification-gaps.md.
    # Lydia self-introduced as "lydia here" in #intros; her last #website post
    # is "LydNot" matching the x.com/LydNot link on her application row.
    "silverflute": ["silverflute"],
    # currentlystillasleep confirmed = Ariel Cheng (also = "talk to the blanket"
    # applicant; same person, pseudonymous form name + Cheng email).
    "currentlystillasleep": ["currentlystillasleep"],
}


def find_member_messages(messages, discord_handle, max_quotes=8):
    if not discord_handle:
        return [], Counter()
    handle_lower = discord_handle.lower()
    handles = set(HANDLE_ALIASES.get(handle_lower, [handle_lower]))
    theirs = [m for m in messages if (m.get("author_name") or "").lower() in handles]
    by_channel = Counter(m["channel_name"] for m in theirs)
    # Pick representative substantive messages: longer messages, varied channels
    substantive = sorted(
        [m for m in theirs if 60 < len(m["content"]) < 400],
        key=lambda m: len(m["content"]),
        reverse=True,
    )
    seen_channels = set()
    quotes = []
    for m in substantive:
        if m["channel_name"] in seen_channels and len(quotes) >= 3:
            continue
        quotes.append(m)
        seen_channels.add(m["channel_name"])
        if len(quotes) >= max_quotes:
            break
    return quotes, by_channel


# Known CSV typos and handle changes in the discord-username column.
# CSV value -> actual handle in messages.json.
DISCORD_TYPO_FIX = {
    "lavendar1729": "lavender1729",  # sudarsh — extra 'a'
    "_melancthon": "_archimedean",   # Georgios — changed handle
    "moxonsmoke": "m0x0n",           # Oscar Moxon — form handle vs actual
    "adellama_": "adellama75",       # Ada — renamed (HANDLE_ALIASES merges old msgs)
}

# Display-name overrides for application form rows where the form name should
# not be used verbatim in the wiki (e.g., parenthetical asides, deadnames).
# Keyed by application-form CSV row number. Maps to (display_name, slug).
NAME_DISPLAY_OVERRIDES = {
    76: ("Frost", "frost"),
    # Dea's form name is "Dea (or at least that's one of the names we use!)",
    # which slugify mangles into a monster slug. Her canonical hand-curated
    # page is dea.md. Consolidate onto it (curated content lives under the
    # preserved ## What they think out loud header).
    127: ("Dea", "dea"),
    # Row 148 (2026-06-16) is Livia Kalossaka re-applying after Vision Weekend
    # London; her form name is just "Livia". Without this, slugify("Livia")
    # spawns a spurious livia.md separate from her livia-kalossaka.md (row 120).
    # Consolidate. NOTE: row 148 is processed after row 120, so a rebuild makes
    # the auto Why/Create sections reflect the (thinner) row-148 answers; the
    # richer row-120 "allies" quote is noted in the preserved site section.
    148: ("Livia Kalossaka", "livia-kalossaka"),
}


def render_member_page(row, members_csv_url, discord_to_name, name_to_discord, messages):
    name = (row.get("name") or "").strip() or "(unnamed)"
    override = NAME_DISPLAY_OVERRIDES.get(row.get("_csv_row"))
    if override:
        name = override[0]
    discord = (row.get("discord username") or "").strip()
    if not discord:
        # fall back to our verified mapping
        discord = name_to_discord.get(name.lower(), "")
    # Repair known typos so the messages.json search hits
    discord = DISCORD_TYPO_FIX.get(discord.lower(), discord)
    github = (row.get("github username") or "").strip()
    email = (row.get("email") or "").strip()
    join_choice = (row.get("I would like to...") or "").strip()
    site_links = (row.get("drop some links you think we should click (eg. your personal website, a blog post you really love, your favourite sites on the internet)") or "").strip()
    why = (row.get("why do you want to join the collective?") or "").strip()
    create = (row.get("what would you like to create as part of the collective?") or "").strip()
    public_ok = (row.get("are you ok with us putting your name and website onto our public list of members?") or "").strip()
    extra = (row.get("here is a space to write anything you like. enjoy") or "").strip()
    timestamp = (row.get("Timestamp") or "").strip()

    members_url = members_csv_url.get(name.lower(), "")

    quotes, by_channel = find_member_messages(messages, discord)
    own_box_channel = f"{slugify(name.split()[0])}-box" if name and " " not in slugify(name.split()[0]) else None

    # Frontmatter
    fm_sources = [
        f"raw/application_responses.csv row {row['_csv_row']}",
    ]
    if members_url:
        fm_sources.append("raw/members.csv")
    if discord and quotes:
        fm_sources.append(f"raw/messages.json (author: {discord})")

    body = []
    body.append(f"# {name}")
    body.append("")
    facts = []
    if members_url:
        facts.append(f"- **Site:** [{members_url}]({members_url})  *(from raw/members.csv)*")
    if site_links:
        # truncate long link lists
        site_short = site_links[:300] + ("…" if len(site_links) > 300 else "")
        facts.append(f"- **Links shared:** {site_short}")
    if discord:
        facts.append(f"- **Discord:** `{discord}`")
    if github:
        facts.append(f"- **GitHub:** `{github}`")
    if join_choice:
        facts.append(f"- **Form choice:** {join_choice}")
    if public_ok:
        facts.append(f"- **Public listing:** {public_ok}")
    if timestamp:
        facts.append(f"- **Application date:** {timestamp}")
    if facts:
        body.append("\n".join(facts))
        body.append("")

    if why:
        body.append("## Why they joined (their own words)")
        body.append("")
        body.append(f"> *{why.strip()}*")
        body.append("")
        body.append(f"[src: raw/application_responses.csv row {row['_csv_row']}, column \"why do you want to join the collective?\"]")
        body.append("")

    if create:
        body.append("## What they want to create (their own words)")
        body.append("")
        body.append(f"> *{create.strip()}*")
        body.append("")
        body.append(f"[src: raw/application_responses.csv row {row['_csv_row']}, column \"what would you like to create as part of the collective?\"]")
        body.append("")

    if extra:
        body.append("## Extra")
        body.append("")
        body.append(f"> *{extra.strip()}*")
        body.append("")

    if by_channel:
        body.append("## Activity in Discord")
        body.append("")
        body.append(f"`{discord}` has posted in {sum(by_channel.values())} messages across {len(by_channel)} channels. Most active in:")
        body.append("")
        for ch, n in by_channel.most_common(8):
            body.append(f"- `#{ch}` — {n} messages")
        body.append("")
        if quotes:
            body.append("## Representative things they've said")
            body.append("")
            for m in quotes[:5]:
                content = m["content"].strip().replace("\n", " ")
                body.append(f"> *\"{content}\"*  *(from `#{m['channel_name']}`)*")
                body.append("")

    body.append("## Notes for the interviewer")
    body.append("")
    if not (why or create or quotes):
        body.append("- The wiki has very little material on this person beyond their application row. Ask them about themselves; do not pretend to know more than you do.")
    else:
        body.append("- Quotes above are from material the person made public (Discord messages, application form). Do not paraphrase or extend.")
        body.append("- If they reference a project — see `wiki/projects/` and the channels listed above.")
    body.append("")

    page = "---\n"
    page += f"title: \"Member: {name}\"\n"
    page += "type: member\n"
    page += "sources:\n"
    for s in fm_sources:
        page += f"  - {s}\n"
    page += "last_updated: 2026-05-08\n"
    page += "---\n\n"
    page += "\n".join(body)
    return page


# Hand-curated section headers we want to preserve across re-runs.
PRESERVE_SECTIONS = (
    "## What they think out loud",
    "## Projects he leads",
    "## Projects she leads",
    "## Projects they lead",
    "## Writings he's authored",
    "## Writings she's authored",
    "## Writings they've authored",
    "## Role in the social topology",
    "## Identity",  # for pages that point to a canonical member page
    "## What they make / what's on their site",  # site enrichment from URL fetches
)


def merge_preserved_sections(existing: str, fresh: str) -> str:
    """If `existing` has any section starting with one of PRESERVE_SECTIONS,
    splice that section into `fresh` directly before "## Notes for the interviewer"
    (or at the end if that header isn't present). Re-running the builder is then
    safe — hand-curated synthesis is preserved.
    """
    if not existing:
        return fresh
    preserved_blocks = []
    lines = existing.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if any(line.startswith(prefix) for prefix in PRESERVE_SECTIONS):
            # Capture until the next "## " header at the same level
            block = [line]
            i += 1
            while i < len(lines) and not lines[i].startswith("## "):
                block.append(lines[i])
                i += 1
            # Strip trailing blanks
            while block and not block[-1].strip():
                block.pop()
            preserved_blocks.append("\n".join(block))
        else:
            i += 1

    if not preserved_blocks:
        return fresh

    insertion = "\n\n".join(preserved_blocks)
    notes_marker = "## Notes for the interviewer"
    if notes_marker in fresh:
        idx = fresh.index(notes_marker)
        return fresh[:idx] + insertion + "\n\n" + fresh[idx:]
    return fresh.rstrip() + "\n\n" + insertion + "\n"


def main():
    application = load_application_responses()
    members_csv = load_members_csv()
    messages = load_messages()
    discord_to_name = build_discord_to_name(application)
    name_to_discord = build_name_to_discord(discord_to_name)

    WIKI_MEMBERS.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_preserved = 0
    skipped = 0
    seen_slugs = {}  # slug -> count for collision handling

    for row in application:
        name = (row.get("name") or "").strip()
        if not name:
            # "keep informed" entries with no name; skip — nothing to put on a page
            skipped += 1
            continue

        override = NAME_DISPLAY_OVERRIDES.get(row.get("_csv_row"))
        if override:
            slug = override[1]
        else:
            slug = slugify(name)
        seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
        if seen_slugs[slug] > 1:
            slug = f"{slug}-{seen_slugs[slug]}"

        out = WIKI_MEMBERS / f"{slug}.md"
        existing = out.read_text(encoding="utf-8") if out.exists() else ""

        page = render_member_page(row, members_csv, discord_to_name, name_to_discord, messages)
        merged = merge_preserved_sections(existing, page)
        if merged != page:
            n_preserved += 1
        out.write_text(merged, encoding="utf-8")
        n_written += 1

    print(f"wrote {n_written} member pages ({n_preserved} preserved hand-curated sections), skipped {skipped} responses with no name")


if __name__ == "__main__":
    main()
