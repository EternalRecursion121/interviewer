"""Render wiki markdown pages to HTML for the browser.

- Splits YAML frontmatter from the body.
- Renders markdown (tables, fenced code, sane lists, table-of-contents).
- Rewrites internal `.md` links (relative to the page) into `/wiki/...` URLs.
- Leaves http(s), anchor, and out-of-wiki links alone.
- Surfaces the useful frontmatter (role / tags / updated / sources) as a
  tasteful meta header instead of silently dropping it.
- Styles `[src: ...]` citations into a subtle inline chip — the text and any
  links inside stay intact (citation-first integrity), they just stop
  shouting.
- Builds an "on this page" table of contents for long pages from the heading
  ids the toc extension already emits.
"""
from __future__ import annotations

import html as _html
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

import markdown
import yaml

from config import WIKI_DIR

_MD = markdown.Markdown(
    extensions=["extra", "sane_lists", "toc", "admonition", "nl2br"],
    output_format="html5",
)

_HREF_RE = re.compile(r'(<a\s[^>]*?href=")([^"]+)(")', re.IGNORECASE)

# `[src: ...]` — possibly containing a rendered <a> for URL citations. We wrap
# the whole token (text + any inner link) in a chip so it reads as a quiet
# margin note rather than inline noise. Non-greedy up to the first closing
# bracket that isn't part of an inner tag.
_SRC_RE = re.compile(r"\[src:\s*(.+?)\]", re.IGNORECASE | re.DOTALL)

# Heading the toc extension emits, e.g. <h2 id="why-this-matters">Why ...</h2>
_HEADING_RE = re.compile(
    r'<h([23])\s+id="([^"]+)">(.*?)</h\1>', re.IGNORECASE | re.DOTALL
)
_TAG_RE = re.compile(r"<[^>]+>")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end].strip()
            body = text[end + 4:].lstrip("\n")
            try:
                fm = yaml.safe_load(raw) or {}
                if not isinstance(fm, dict):
                    fm = {}
            except yaml.YAMLError:
                fm = {}
            return fm, body
    return {}, text


def _rewrite_href(href: str, page_rel: str) -> str:
    """Rewrite a single href found in the rendered HTML.

    `page_rel` is the wiki-relative path of the current page, e.g.
    'concepts/goodhart.md'.
    """
    parts = urlsplit(href)
    if parts.scheme or href.startswith("//"):
        return href  # external
    if href.startswith("#"):
        return href  # in-page anchor
    if href.startswith("/"):
        return href  # already absolute on our site

    path_part = unquote(parts.path)
    anchor = f"#{parts.fragment}" if parts.fragment else ""

    if not path_part:
        return href

    base_dir = PurePosixPath(page_rel).parent
    target = (base_dir / path_part)
    # Normalize .. and .
    resolved = PurePosixPath()
    for seg in target.parts:
        if seg == "..":
            resolved = resolved.parent
        elif seg in (".", ""):
            continue
        else:
            resolved = resolved / seg
    rel = str(resolved)

    if rel.endswith(".md"):
        return f"/wiki/{rel[:-3]}{anchor}"
    # Links into raw/ or other non-md, non-wiki targets: not browsable here.
    if rel.startswith("../") or rel.startswith("raw/") or rel.startswith("../raw"):
        return href
    return f"/wiki/{rel}{anchor}"


def _style_citations(html: str) -> str:
    """Wrap `[src: ...]` tokens in a quiet chip without touching their text.

    Traceability is the whole point of this wiki — we keep every character
    (and any inner <a>), we just stop it from competing with prose.
    """

    def repl(m: re.Match) -> str:
        inner = m.group(1).strip()
        return (
            '<span class="cite" title="citation — traces to a raw source">'
            '<span class="cite-k">src</span>'
            f'<span class="cite-v">{inner}</span></span>'
        )

    return _SRC_RE.sub(repl, html)


def _build_toc(html: str) -> list[tuple[int, str, str]]:
    """Pull (level, id, text) for every h2/h3 with an id, in document order."""
    out: list[tuple[int, str, str]] = []
    for m in _HEADING_RE.finditer(html):
        level = int(m.group(1))
        anchor = m.group(2)
        text = _TAG_RE.sub("", m.group(3))
        text = _html.unescape(text).strip()
        if text:
            out.append((level, anchor, text))
    return out


def _add_heading_anchors(html: str) -> str:
    """Give h2/h3 a hover anchor link so headings are addressable."""

    def repl(m: re.Match) -> str:
        level, anchor, inner = m.group(1), m.group(2), m.group(3)
        return (
            f'<h{level} id="{anchor}">{inner}'
            f'<a class="h-anchor" href="#{anchor}" '
            f'aria-label="link to this section">#</a></h{level}>'
        )

    return _HEADING_RE.sub(repl, html)


def _meta_chips(fm: dict, page_rel: str) -> str:
    """Render the useful frontmatter as small chips under the title.

    Surfaces role / tags / updated / source-count — the data `render_page`
    used to drop on the floor. Calm and scannable, never load-bearing.
    """
    chips: list[str] = []

    role = fm.get("role")
    if role:
        r = str(role).replace("-", " ").capitalize()
        chips.append(
            f'<span class="chip chip-role">{_html.escape(r)}</span>'
        )

    pod = fm.get("pod")
    if pod:
        chips.append(
            f'<span class="chip">pod · {_html.escape(str(pod))}</span>'
        )

    tags = fm.get("tags")
    if isinstance(tags, (list, tuple)):
        for t in tags:
            if t is None:
                continue
            chips.append(
                f'<span class="chip chip-tag">{_html.escape(str(t))}</span>'
            )
    elif tags:
        chips.append(
            f'<span class="chip chip-tag">{_html.escape(str(tags))}</span>'
        )

    srcs = fm.get("sources")
    if isinstance(srcs, (list, tuple)):
        n = len([s for s in srcs if s])
        if n:
            noun = "source" if n == 1 else "sources"
            chips.append(
                f'<span class="chip chip-src" '
                f'title="{_html.escape(", ".join(str(s) for s in srcs if s))}">'
                f'{n} {noun}</span>'
            )
    elif srcs:
        chips.append(
            f'<span class="chip chip-src">'
            f'{_html.escape(str(srcs))}</span>'
        )

    if not chips:
        return ""
    return f'<div class="meta-chips">{"".join(chips)}</div>'


_LAYER_BLURB = {
    "concepts": "The alignment tech tree, page by page — prerequisites, "
                "dependents, curated readings, and who in the cohort touches each.",
    "participants": "The seminar fellows (and visitors, treated as participants) "
                    "— the interviewer's primary audience. One canonical page each.",
    "themes": "Synthesis pages: who cares about what, clustered across the cohort.",
    "talks": "The seminar's talks — speakers, arguments, the concepts each one touches.",
    "tags": "The five branches of the tree, with commentary companions.",
    "mentors": "Invited alignment researchers and external speakers — who fellows "
               "go to for technical feedback. Plus the theme → mentor matchmaker.",
    "team": "Organizers, operations, and facilitators — surface for logistics, "
            "well-being, or community-design questions, not as research peers.",
    "sources": "Pointers to the raw material the wiki is built from.",
}

# Layers where a per-page role is worth showing inline in the listing.
_PEOPLE_LAYERS = {"participants", "mentors", "team"}


def list_dir(dir_rel: str) -> tuple[dict, str] | None:
    """Auto-generate a listing page for a wiki subdirectory (no index.md needed).

    Returns (frontmatter-ish dict, html) so the caller can render it like any
    other page. `dir_rel` is wiki-relative, e.g. 'concepts'.

    For people layers the row carries the person's role; the list is grouped
    alphabetically (A, B, C ...) so a 30-name layer is scannable, and a small
    client-side filter box (pure JS, see app.css/inline script) narrows it.
    """
    rel = dir_rel.strip().strip("/")
    if not rel:
        return None
    d = (WIKI_DIR / rel).resolve()
    try:
        d.relative_to(WIKI_DIR.resolve())
    except ValueError:
        return None
    if not d.is_dir():
        return None

    name = rel.split("/")[-1]
    is_people = name in _PEOPLE_LAYERS

    entries: list[tuple[str, str, str]] = []
    for p in sorted(d.glob("*.md"), key=lambda x: x.stem.lower()):
        if p.stem in ("index",):
            continue
        try:
            fm, _ = _split_frontmatter(p.read_text(encoding="utf-8"))
        except OSError:
            fm = {}
        title = str(fm.get("title") or p.stem.replace("-", " ").title())
        href = f"/wiki/{rel}/{p.stem}"
        if is_people:
            sub = str(fm.get("role") or "")
        else:
            sub = str(fm.get("type") or "")
        sub = sub.replace("-", " ")
        if sub:
            sub = sub[0].upper() + sub[1:]
        entries.append((title, href, sub))

    blurb = _LAYER_BLURB.get(name, f"Every page under <code>{name}/</code>.")

    # Group alphabetically by first letter of the title.
    groups: dict[str, list[tuple[str, str, str]]] = {}
    for title, href, sub in entries:
        first = title.strip()[:1].upper()
        key = first if first.isalpha() else "#"
        groups.setdefault(key, []).append((title, href, sub))

    def _row(title: str, href: str, sub: str) -> str:
        meta = (
            f' <span class="ldim">{_html.escape(sub)}</span>'
            if sub else ""
        )
        return (
            f'<li class="layer-item" data-name="{_html.escape(title.lower())} '
            f'{_html.escape(sub.lower())}">'
            f'<a href="{href}">{_html.escape(title)}</a>{meta}</li>'
        )

    sections = []
    for key in sorted(groups):
        rows = "\n".join(_row(t, h, s) for t, h, s in groups[key])
        sections.append(
            f'<section class="layer-group" data-letter="{key}">'
            f'<h3 class="layer-letter">{key}</h3>'
            f'<ul class="layer-list">{rows}</ul></section>'
        )

    n = len(entries)
    noun = "page" if n == 1 else "pages"
    filter_box = (
        '<div class="layer-filter">'
        '<input type="search" id="layerFilter" '
        f'placeholder="Filter {n} {noun}…" '
        'autocomplete="off" aria-label="Filter this layer">'
        '<span class="layer-filter-empty" id="layerFilterEmpty" '
        'hidden>No matches</span>'
        '</div>'
    ) if n > 8 else ""

    html_out = (
        f'<p class="layer-blurb">{blurb}</p>'
        f'<p class="layer-count">{n} {noun}</p>'
        f'{filter_box}'
        f'<div class="layer-groups">{"".join(sections)}</div>'
    )
    return (
        {"title": name.capitalize(), "type": "layer", "_is_layer": True},
        html_out,
    )


def render_page(page_rel: str) -> tuple[dict, str] | None:
    """Return (frontmatter, html) for a wiki page, or None if it doesn't exist.

    `page_rel` is wiki-relative, with or without `.md` (e.g. 'concepts/goodhart').

    The returned frontmatter dict is enriched with two presentation-only keys
    the caller can use without changing the page content:
      `_toc`   — list of (level, anchor, text) for an "on this page" rail
      `_meta_chips` — pre-rendered HTML chips for role/tags/updated/sources
    """
    rel = page_rel.strip().strip("/")
    if not rel.endswith(".md"):
        rel += ".md"
    candidate = (WIKI_DIR / rel).resolve()
    try:
        candidate.relative_to(WIKI_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None

    text = candidate.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)

    _MD.reset()
    html = _MD.convert(body)
    html = _HREF_RE.sub(
        lambda m: m.group(1) + _rewrite_href(m.group(2), rel) + m.group(3),
        html,
    )

    toc = _build_toc(html)
    html = _add_heading_anchors(html)
    html = _style_citations(html)

    fm = dict(fm)
    fm["_toc"] = toc
    fm["_meta_chips"] = _meta_chips(fm, rel)
    return fm, html
