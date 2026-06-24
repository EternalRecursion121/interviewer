#!/usr/bin/env python3
"""Generate wiki/participants/*.md from raw/AFFINE Seminar - Names & Faces.txt.

Deterministic — re-running overwrites generated pages.

Anti-hallucination rule: every fact on a participant page must come from the
intros file. We do not embellish, summarize beyond reformatting, or invent.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "raw" / "AFFINE Seminar - Names & Faces.txt"
WIKI_ROOT = ROOT / "wiki"
WIKI = WIKI_ROOT / "participants"
CONCEPTS_DIR = ROOT / "wiki" / "concepts"


def role_to_dir(role_section: str) -> str:
    """People are split across three layers by role. Keep in sync with
    server/tools.py PEOPLE_DIRS and the migration script."""
    if role_section in ("mentor", "external-speaker"):
        return "mentors"
    if role_section in ("participant", "visitor"):
        return "participants"
    return "team"  # event-team + any ops/volunteer/lead/job-title role
TOPICS_CSV = ROOT / "raw" / "sheet" / "Topics.csv"
TODAY = date.today().isoformat()

# Hand-curated aliases that map participant-intro phrasing to concept names from
# the AFFINE tech tree. Keep only mappings that are unambiguous.
CONCEPT_ALIASES: dict[str, list[str]] = {
    # alias (lowercased) → list of concept names (exact, as in Topics.csv) it should link to
    "alignment problem": ["Alignment's Many Meanings"],
    "ai safety": ["AI Takeover Risk"],
    "ai x-risk": ["AI Takeover Risk"],
    "x-risk": ["AI Takeover Risk"],
    "existential risk": ["AI Takeover Risk"],
    "active inference": ["Active Inference"],
    "predictive processing": ["Active Inference"],
    "multiple agency": ["Multiple Agency"],
    "multi-agent": ["Multiple Agency"],
    "multi agent": ["Multiple Agency"],
    "agency": ["Agency"],
    "individuality": ["Agency"],
    "agi": ["AGI/ASI's various meanings"],
    "asi": ["AGI/ASI's various meanings"],
    "superintelligence": ["AGI/ASI's various meanings"],
    "wireheading": ["Wireheading"],
    "goodhart": ["Goodhart"],
    "goodharting": ["Goodhart"],
    "deep deceptiveness": ["Deep Deceptiveness"],
    "deception": ["Deep Deceptiveness"],
    "interpretability": ["Outer / Inner Alignment"],  # rough — best concept page is none, fallback
    "mech-interp": ["Outer / Inner Alignment"],
    "mech interp": ["Outer / Inner Alignment"],
    "mechanistic interpretability": ["Outer / Inner Alignment"],
    "value formation": ["Value formation"],
    "values": ["Value"],
    "value drift": ["Value formation"],
    "decision theory": ["Decision theory"],
    "corrigibility": ["Corrigibility"],
    "outer alignment": ["Outer / Inner Alignment"],
    "inner alignment": ["Outer / Inner Alignment"],
    "mesa-optimization": ["Mesa-Optimization"],
    "mesa optimization": ["Mesa-Optimization"],
    "natural abstraction": ["Natural Abstraction"],
    "abstraction": ["Value of abstraction"],
    "ontology": ["Ontology"],
    "ontological crisis": ["Ontological Crisis"],
    "recursive self-improvement": ["Recursive self-improvement"],
    "sharp left turn": ["Sharp Left Turn"],
    "infra-bayesianism": ["Infra-Bayesianism"],
    "embedded agency": ["Embedded Agency"],
    "coherent extrapolated volition": ["Coherent Extrapolated Volition"],
    "cev": ["Coherent Extrapolated Volition"],
    "debate": ["Debate"],
    "control": ["Control (in the technical sense) and its limits"],
    "agi alignment": ["Alignment's Many Meanings"],
    "intelligence": ["Intelligence"],
    "general intelligence": ["General intelligence"],
    "reinforcement learning": ["Reinforcement Learning"],
    "rl": ["Reinforcement Learning"],
    "selection": ["Selection and Control"],
    "simulators": ["Simulators"],
    "tool ai": ["Tool AI"],
    "substrate needs convergence": ["Instrumental Convergence"],
    "instrumental convergence": ["Instrumental Convergence"],
    "obfuscation": ["Obfuscation / steganography"],
    "steganography": ["Obfuscation / steganography"],
    "pointers problem": ["The Pointers Problem"],
    "value of abstraction": ["Value of abstraction"],
    "shutdown problem": ["Corrigibility"],
    "ai takeover": ["AI Takeover Risk"],
    "robust": ["Robustness to Scale"],
    "self-improvement": ["Recursive self-improvement"],
    "compositional generalization": ["Natural Abstraction"],
    "anthropics": ["Anthropics"],
    "anthropic capture": ["Anthropic Capture"],
}

# Section dividers in the source — these mark the start of a new role group.
SECTION_HEADERS = {
    "Event Team": "event-team",
    "Mentors": "mentor",
    "Visitors": "visitor",
}
# Anything before the first known section is a regular participant.
DEFAULT_ROLE = "participant"

FIELD_PATTERNS = [
    # (emoji, key) — emoji starts the line, optional ":" or "?:" after a label
    ("🌿", "brings_me_here"),
    ("🫴", "can_offer"),
    ("🤲", "looking_for"),
    ("🔥", "lights_me_up"),
    ("✨", "crazy_fact"),
    ("🌐", "links"),
]

PLACEHOLDER_LINE = "[Drop in a photo here"
TEMPLATE_NAME_LINE = "[Your name]"
META_PREFIX_RE = re.compile(r"^(Based in|At Hostačov|Pronouns)", re.IGNORECASE)


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"\([^)]*\)", "", s)  # drop parenthetical role tags
    # Decompose accented chars to base + combining mark, then drop the marks.
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def split_blocks(text: str) -> list[list[str]]:
    """Split the file into blocks separated by one or more blank lines."""
    # Google Docs exports use \x0b (vertical tab) as a soft line break inside the
    # same paragraph. splitlines() treats \x0b as a line separator, which would
    # falsely break "Name\x0b\nBased in:" into two blocks. Normalize first.
    text = text.replace("\x0b", "")
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def is_section_header(block: list[str]) -> str | None:
    if len(block) == 1 and block[0].strip() in SECTION_HEADERS:
        return SECTION_HEADERS[block[0].strip()]
    return None


def is_placeholder_block(block: list[str]) -> bool:
    """True if block is a 'copy this slide' template or a name-only stub."""
    joined = "\n".join(block)
    if TEMPLATE_NAME_LINE in joined:
        return True
    # Bare name with no field markers and no Based in/At Hostačov.
    if not any(any(f[0] in line for f in FIELD_PATTERNS) for line in block) and not any(
        META_PREFIX_RE.search(line) for line in block
    ):
        return True
    return False


def find_field(line: str) -> tuple[str, str] | None:
    """If line starts with one of the known emoji, return (key, value)."""
    for emoji, key in FIELD_PATTERNS:
        if line.lstrip().startswith(emoji):
            rest = line.lstrip()[len(emoji) :]
            # strip the descriptive prefix and common separators
            rest = re.sub(
                r"^\s*(What brings me here|What I can offer|What I am looking for\??|What connects me here|What am I looking for\??|Topics? (that )?(light|excite)s? me up|A topic that lights me up|One (crazy|unusual) fact about me)\s*[-:–]?\s*",
                "",
                rest,
                flags=re.IGNORECASE,
            )
            rest = rest.lstrip(" -–:?").strip()
            return key, rest
    return None


def parse_meta_line(line: str) -> dict[str, str]:
    """Parse the 'Based in: X · Pronouns: Y At Hostačov: Z' line. All fields optional."""
    out: dict[str, str] = {}
    # Sometimes the three keys are squashed without any visible separator.
    # Insert a separator before each known key so split works uniformly.
    s = line
    for key in ("At Hostačov", "Pronouns"):
        s = re.sub(rf"(?<=\S)(\s*)({re.escape(key)})", r" · \2", s)
    parts = re.split(r"\s*·\s*", s)
    for p in parts:
        m = re.match(r"\s*Based in\s*:?\s*(.+?)\s*$", p, re.IGNORECASE)
        if m:
            out["based_in"] = strip_brackets(m.group(1))
            continue
        m = re.match(r"\s*Pronouns(?:\s*\(optional\))?\s*:?\s*(.+?)\s*$", p, re.IGNORECASE)
        if m:
            out["pronouns"] = strip_brackets(m.group(1))
            continue
        m = re.match(r"\s*At Hostačov\s*:?\s*(.+?)\s*$", p, re.IGNORECASE)
        if m:
            out["dates"] = strip_brackets(m.group(1))
            continue
    return out


def strip_brackets(s: str) -> str:
    s = s.strip()
    if s.startswith("[") and s.endswith("]") and len(s) >= 2:
        s = s[1:-1].strip()
    return s


def parse_participant(block: list[str], role: str, src_start_line: int) -> dict | None:
    """Parse one block into a structured participant dict, or None to skip."""
    if is_placeholder_block(block):
        return None

    # Name is the first non-empty line. Sometimes the role is on its own next line
    # (e.g. "Sofie Meyer" / "Humans Lead"). We treat a second non-meta, non-emoji
    # line before the meta line as a role suffix.
    name_line = block[0].strip()
    name_line = re.sub(r"\s+", " ", name_line)

    # Detect inline role markers. The name line can take several forms:
    #   "Grace Roberts (volunteer)Role: Online Seminar Lead"   → role = Online Seminar Lead
    #   "Grace Roberts (volunteer)"                              → role = volunteer
    #   "Jiri Nadvornik - operations"                            → role = operations
    #   "Hugh Herrington V (Sean)"                               → no role (nickname; keep in name)
    #   "Sofie Meyer"  + "Humans Lead" on its own next line     → handled separately below
    role_inline: str | None = None
    name = name_line.rstrip(".")  # "Ryan Thomas." → "Ryan Thomas"

    # An explicit "Role:" anywhere on the line takes precedence
    m = re.search(r"\bRole\s*:\s*(.+)$", name, re.IGNORECASE)
    if m:
        role_inline = m.group(1).strip()
        name = name[: m.start()].strip()

    # Parenthetical: keep if it looks like a nickname (single Capitalized word),
    # otherwise treat as role.
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", name)
    if m:
        candidate_role = m.group(2).strip()
        looks_like_nickname = (
            candidate_role
            and " " not in candidate_role
            and candidate_role[:1].isupper()
            and candidate_role.lower() not in {"volunteer", "mentor", "visitor"}
        )
        if looks_like_nickname:
            # Keep the parenthetical in the displayed name
            pass
        else:
            name = m.group(1).strip()
            if role_inline is None:
                role_inline = candidate_role
        # second parenthetical chain (rare)
        name = re.sub(r"\s+\(\s*\)\s*$", "", name)

    # Trailing "- operations"-style suffix
    m = re.match(r"^(.*?)\s+[-–]\s+([a-z][^-]+?)\s*$", name)
    if m and role_inline is None:
        name = m.group(1).strip()
        role_inline = m.group(2).strip()

    fields: dict[str, str] = {}
    meta: dict[str, str] = {}
    role_line_extra: str | None = None
    other_lines: list[str] = []

    # Walk the rest, accumulating fields. Continuation lines (no leading emoji and
    # not a Based-in/At-Hostačov line) get appended to the most recent field.
    last_key: str | None = None
    for line in block[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        if META_PREFIX_RE.search(stripped):
            meta.update(parse_meta_line(stripped))
            last_key = None
            continue
        f = find_field(stripped)
        if f is not None:
            key, value = f
            if key in fields:
                fields[key] = fields[key] + "\n" + value
            else:
                fields[key] = value
            last_key = key
            continue
        # Lines that look like URLs or "Site: ..." attach to a `links` field.
        if re.match(r"^(https?://|Site\s*:|More about me|🌐)", stripped, re.IGNORECASE):
            cleaned = re.sub(r"^(Site\s*:|More about me\s*:?|🌐\s*)", "", stripped, flags=re.IGNORECASE).strip()
            fields["links"] = (fields.get("links", "") + "\n" + cleaned).strip()
            last_key = "links"
            continue
        # A short non-meta, non-field line right after the name is likely a role tag
        # (e.g. "Humans Lead", "Online Seminar Lead").
        if last_key is None and len(stripped) < 80 and role_line_extra is None:
            role_line_extra = stripped
            continue
        # Otherwise, treat as a continuation of the last field.
        if last_key is not None:
            fields[last_key] = fields[last_key] + " " + stripped
        else:
            other_lines.append(stripped)

    if not fields and not meta:
        # No real content
        return None

    if role_line_extra and not role_inline:
        role_inline = role_line_extra

    return {
        "name": name,
        "role_inline": role_inline,
        "role_section": role,
        "meta": meta,
        "fields": fields,
        "other_lines": other_lines,
        "src_line": src_start_line,
    }


def load_concept_slugs() -> dict[str, str]:
    """Map concept name (from Topics.csv) → slug (matching wiki/concepts/<slug>.md)."""
    if not TOPICS_CSV.exists():
        return {}
    out: dict[str, str] = {}
    with TOPICS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            s = name.lower()
            s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
            out[name] = s
    return out


def match_concepts(text: str, concept_slugs: dict[str, str]) -> list[tuple[str, str]]:
    """Find tech-tree concepts mentioned in text. Returns (display_name, slug) pairs."""
    found: dict[str, str] = {}
    lower = text.lower()

    # Pass 1: direct concept-name matches (case-insensitive, word-bounded).
    for cname, cslug in concept_slugs.items():
        cname_l = cname.lower()
        if not cname_l:
            continue
        # build a tolerant pattern: any non-word run between tokens
        tokens = re.findall(r"[a-z0-9']+", cname_l)
        if not tokens:
            continue
        # Require at least one multi-character token to avoid trivial 1-char matches.
        if not any(len(t) > 2 for t in tokens):
            continue
        pat = r"\b" + r"[^a-z0-9']{0,3}".join(re.escape(t) for t in tokens) + r"\b"
        if re.search(pat, lower):
            found[cname] = cslug

    # Pass 2: alias hits.
    for alias, names in CONCEPT_ALIASES.items():
        pat = r"\b" + re.escape(alias) + r"\b"
        if re.search(pat, lower):
            for cname in names:
                if cname in concept_slugs:
                    found[cname] = concept_slugs[cname]

    return sorted(found.items(), key=lambda kv: kv[0].lower())


def render_participant(p: dict, concept_slugs: dict[str, str]) -> str:
    name = p["name"]
    slug = slugify(name)

    role_section = p["role_section"]
    role_inline = p["role_inline"]
    role_display = role_inline or role_section

    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: {name}')
    lines.append("type: participant")
    lines.append(f"role: {role_display}")
    lines.append("sources:")
    lines.append(f'  - "raw/AFFINE Seminar - Names & Faces.txt"  # block starting line {p["src_line"]}')
    lines.append(f"last_updated: {TODAY}")
    lines.append("# INTRO block below is auto-generated by build_wiki/build_participants.py; other blocks are hand-managed.")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")

    role_bits = []
    if role_inline:
        role_bits.append(f"**Role:** {role_inline}")
    elif role_section != DEFAULT_ROLE:
        role_bits.append(f"**Role:** {role_section.replace('-', ' ')}")
    if role_bits:
        lines.append(" · ".join(role_bits))
        lines.append("")

    meta = p["meta"]
    meta_bits = []
    if meta.get("based_in"):
        meta_bits.append(f"**Based in:** {meta['based_in']}")
    if meta.get("pronouns"):
        meta_bits.append(f"**Pronouns:** {meta['pronouns']}")
    if meta.get("dates"):
        meta_bits.append(f"**At Hostačov:** {meta['dates']}")
    if meta_bits:
        lines.append(" · ".join(meta_bits))
        lines.append("")

    sections = [
        ("brings_me_here", "🌿 What brings me here"),
        ("can_offer", "🫴 What I can offer"),
        ("looking_for", "🤲 What I am looking for"),
        ("lights_me_up", "🔥 A topic that lights me up"),
        ("crazy_fact", "✨ One crazy fact about me"),
        ("links", "🌐 Links"),
    ]
    for key, heading in sections:
        if key not in p["fields"]:
            continue
        value = p["fields"][key].strip()
        if not value:
            continue
        lines.append(f"### {heading}")
        lines.append("")
        for v in value.split("\n"):
            v = v.strip()
            if v:
                lines.append(v)
        lines.append("")

    if p["other_lines"]:
        lines.append("### Other")
        lines.append("")
        for v in p["other_lines"]:
            lines.append(v)
        lines.append("")

    # Related concepts: fuzzy-match the participant's intro text against the tech tree.
    intro_text = " ".join(p["fields"].values()) + " " + " ".join(p["other_lines"])
    matched = match_concepts(intro_text, concept_slugs)
    if matched:
        lines.append("### Related concepts in the AFFINE tech tree")
        lines.append("")
        lines.append("_Auto-matched from this participant's intro. Inexact — verify in conversation._")
        lines.append("")
        for cname, cslug in matched:
            lines.append(f"- [{cname}](../concepts/{cslug}.md)")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f'_Source: [`raw/AFFINE Seminar - Names & Faces.txt`](../../raw/AFFINE%20Seminar%20-%20Names%20%26%20Faces.txt), block starting around line {p["src_line"]}._'
    )
    lines.append("")
    return "\n".join(lines), slug


def write_participants_index(parsed: list[dict]) -> None:
    """Generate one index per people layer.

    People are split across three sibling dirs by role (see role_to_dir):
      participants/  fellows + visitors      -> participants/index.md (generated)
      team/          event team + ops/leads  -> team/index.md         (generated)
      mentors/       mentors + ext-speakers  -> mentors/index.md is HAND-CURATED
                     (alongside matchmaker.md) and is intentionally NOT written
                     here; the migration keeps its links correct.
    """
    import re as _re

    pretty = {
        DEFAULT_ROLE: "Participants",
        "visitor": "Visitors",
        "event-team": "Event Team",
    }
    extras_labels = {
        DEFAULT_ROLE: "Additional participants (intro added after the deck)",
        "visitor": "Additional visitors",
        "event-team": "Additional event team",
        "mentor": "Additional mentors",
        "external-speaker": "External speakers / facilitators (no intro form)",
    }
    soft_roles = {DEFAULT_ROLE, "mentor", "event-team", "visitor"}

    # Every raw-derived slug, so per-dir extra scans can skip them.
    all_intro_slugs = {slugify(p["name"]) for p in parsed}

    layers = [
        ("participants", "Participants index", "Participants",
         "Seminar fellows (and visitors, treated as participants). Pages "
         "reproduce what each person wrote about themselves plus what later "
         "sources add.", [DEFAULT_ROLE, "visitor"]),
        ("team", "Event team index", "Event team",
         "Organizers, operations, and facilitators. Surface these for "
         "logistics, well-being, or community-design questions — NOT as "
         "research collaborators.", ["event-team"]),
    ]

    for dirname, title, heading, blurb, section_order in layers:
        by_section: dict[str, list[dict]] = {}
        for p in parsed:
            if role_to_dir(p["role_section"]) != dirname:
                continue
            by_section.setdefault(p["role_section"], []).append(p)

        lines = [
            "---",
            f"title: {title}",
            "type: overview",
            "sources:",
            '  - "raw/AFFINE Seminar - Names & Faces.txt"',
            f"last_updated: {TODAY}",
            "generated: true",
            "---",
            "",
            f"# {heading}",
            "",
            blurb,
            "",
        ]

        for section in section_order:
            members = by_section.get(section, [])
            if not members:
                continue
            lines.append(f"## {pretty[section]} ({len(members)})")
            lines.append("")
            for p in sorted(members, key=lambda p: p["name"].lower()):
                slug = slugify(p["name"])
                bits = []
                if p["meta"].get("based_in"):
                    bits.append(p["meta"]["based_in"])
                if p["role_inline"]:
                    bits.append(p["role_inline"])
                tag = " — " + " · ".join(bits) if bits else ""
                lines.append(f"- [{p['name']}]({slug}.md){tag}")
            lines.append("")

        # Hand-managed extra pages physically in this dir (not from the deck).
        extras_by_role: dict[str, list[tuple[str, str]]] = {}
        ddir = WIKI_ROOT / dirname
        if ddir.exists():
            for path in sorted(ddir.glob("*.md")):
                if path.name in {"index.md", "auto-match-review.md", "matchmaker.md"}:
                    continue
                if path.stem in all_intro_slugs:
                    continue
                md = path.read_text(encoding="utf-8")
                m = _re.search(r"^title:\s*(.+?)\s*$", md, _re.M)
                display = m.group(1) if m else path.stem
                rm = _re.search(r"^role:\s*(.+?)\s*$", md, _re.M)
                role = (rm.group(1) if rm else "external").strip()
                extras_by_role.setdefault(role, []).append((display, path.stem))

        for role in sorted(extras_by_role):
            ppl = extras_by_role[role]
            label = extras_labels.get(role, f"Other ({role})")
            lines.append(f"## {label} ({len(ppl)})")
            lines.append("")
            if role not in soft_roles:
                lines.append("_No self-intro on the AFFINE form. The interviewer should treat the absence as significant — ask open questions rather than reflecting back stated motivations._")
                lines.append("")
            for display, slug in sorted(ppl, key=lambda x: x[0].lower()):
                lines.append(f"- [{display}]({slug}.md)")
            lines.append("")

        (WIKI_ROOT / dirname / "index.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    text = SRC.read_text(encoding="utf-8")
    blocks = split_blocks(text)

    # Track source line numbers for citations.
    line_index: list[int] = []
    cur = 1
    for raw_line in text.splitlines(True):
        line_index.append(cur)
        cur += 1

    # Walk blocks, tracking the current role section.
    role = DEFAULT_ROLE
    parsed: list[dict] = []
    cursor = 0  # rough source line tracker
    for block in blocks:
        sec = is_section_header(block)
        if sec is not None:
            role = sec
            cursor += len(block) + 1
            continue
        # Find first line of this block in source
        first_line = block[0]
        src_start = text.find(first_line, cursor)
        if src_start < 0:
            src_start = cursor
        src_line_no = text.count("\n", 0, src_start) + 1
        p = parse_participant(block, role, src_line_no)
        if p is not None:
            parsed.append(p)
        cursor = src_start + len(first_line)

    concept_slugs = load_concept_slugs()

    for d in ("participants", "mentors", "team"):
        (WIKI_ROOT / d).mkdir(parents=True, exist_ok=True)
    slugs_seen: dict[str, str] = {}
    for p in parsed:
        rendered, slug = render_participant(p, concept_slugs)
        if slug in slugs_seen and slugs_seen[slug] != p["name"]:
            i = 2
            while f"{slug}-{i}" in slugs_seen:
                i += 1
            slug = f"{slug}-{i}"
        slugs_seen[slug] = p["name"]
        out_dir = WIKI_ROOT / role_to_dir(p["role_section"])
        upsert_intro(out_dir / f"{slug}.md", rendered)

    write_participants_index(parsed)
    print(f"Generated {len(parsed)} participant intro blocks + index.")


INTRO_START = "<!-- INTRO START -->"
INTRO_END = "<!-- INTRO END -->"


def upsert_intro(path: Path, rendered_full: str) -> None:
    """Write rendered_full to path, wrapping its body in INTRO markers and
    preserving any hand-managed content (enrichment, discord, mentor, backlinks)
    that lives after the INTRO_END marker in an existing file."""
    import re

    m = re.match(r"^(---\n.*?\n---\n+)(.*)", rendered_full, re.S)
    if m:
        frontmatter, body = m.group(1), m.group(2)
    else:
        frontmatter, body = "", rendered_full
    intro_block = f"{INTRO_START}\n{body.rstrip()}\n{INTRO_END}\n"

    if not path.exists():
        path.write_text(frontmatter + intro_block, encoding="utf-8")
        return

    existing = path.read_text(encoding="utf-8")
    if INTRO_START in existing and INTRO_END in existing:
        new = re.sub(
            rf"{re.escape(INTRO_START)}.*?{re.escape(INTRO_END)}",
            intro_block.rstrip(),
            existing,
            flags=re.S,
        )
        path.write_text(new, encoding="utf-8")
    else:
        path.write_text(frontmatter + intro_block, encoding="utf-8")


if __name__ == "__main__":
    main()
