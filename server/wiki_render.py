"""Render wiki markdown pages to HTML for the browser.

- Splits YAML frontmatter from the body.
- Renders markdown (tables, fenced code, sane lists, table-of-contents).
- Rewrites internal `.md` links (relative to the page) into `/wiki/...` URLs.
- Leaves http(s), anchor, and out-of-wiki links alone.
"""
from __future__ import annotations

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


_LAYER_BLURB = {
    "concepts": "The alignment tech tree, page by page — prerequisites, "
                "dependents, curated readings, and who in the cohort touches each.",
    "participants": "Everyone in the AFFINE 2026 cohort — fellows, mentors, "
                    "visitors, organizers. One canonical page each.",
    "themes": "Synthesis pages: who cares about what, clustered across the cohort.",
    "talks": "The seminar's talks — speakers, arguments, the concepts each one touches.",
    "tags": "The five branches of the tree, with commentary companions.",
    "mentors": "The mentor catalog and the theme → mentor matchmaker.",
    "sources": "Pointers to the raw material the wiki is built from.",
}


def list_dir(dir_rel: str) -> tuple[dict, str] | None:
    """Auto-generate a listing page for a wiki subdirectory (no index.md needed).

    Returns (frontmatter-ish dict, html) so the caller can render it like any
    other page. `dir_rel` is wiki-relative, e.g. 'concepts'.
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

    entries = []
    for p in sorted(d.glob("*.md")):
        if p.stem in ("index",):
            continue
        try:
            fm, _ = _split_frontmatter(p.read_text(encoding="utf-8"))
        except OSError:
            fm = {}
        title = str(fm.get("title") or p.stem.replace("-", " ").title())
        href = f"/wiki/{rel}/{p.stem}"
        sub = str(fm.get("type") or "")
        entries.append((title, href, sub))

    name = rel.split("/")[-1]
    blurb = _LAYER_BLURB.get(name, f"Every page under <code>{name}/</code>.")
    items = "\n".join(
        f'<li><a href="{href}">{title}</a>'
        f'{f" <span class=ldim>· {sub}</span>" if sub else ""}</li>'
        for title, href, sub in entries
    )
    html_out = (
        f'<p class="layer-blurb">{blurb}</p>'
        f'<p class="layer-count">{len(entries)} pages</p>'
        f'<ul class="layer-list">{items}</ul>'
    )
    return {"title": name.capitalize(), "type": "layer"}, html_out


def render_page(page_rel: str) -> tuple[dict, str] | None:
    """Return (frontmatter, html) for a wiki page, or None if it doesn't exist.

    `page_rel` is wiki-relative, with or without `.md` (e.g. 'concepts/goodhart').
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
    html = _HREF_RE.sub(lambda m: m.group(1) + _rewrite_href(m.group(2), rel) + m.group(3), html)
    return fm, html
