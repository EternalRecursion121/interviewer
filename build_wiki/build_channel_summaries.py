"""
Build wiki/channels/<channel>.md from raw/messages.json.

Deterministic structured extraction. Each page contains:
  - frontmatter with source pointer
  - top contributors with message counts
  - links shared (deduplicated)
  - representative substantive messages quoted with attribution

No LLM calls. Pages are intended as the *starting point* for an interviewer to
understand a channel; channel pages for high-traffic channels (#general,
#idealists-conference, #magazine, etc.) are then hand-curated to add synthesis.
The hand-curated version should preserve the dump as a section so quotes remain
auditable.
"""
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "raw"
WIKI_CHANNELS = REPO / "wiki" / "channels"

URL_RE = re.compile(r"https?://[^\s)\]>]+")


def load_messages():
    with open(RAW / "messages.json") as f:
        return json.load(f)


def extract_links(messages):
    seen = []
    seen_set = set()
    for m in messages:
        for url in URL_RE.findall(m.get("content") or ""):
            url = url.rstrip(".,;:!?")
            if url in seen_set:
                continue
            seen_set.add(url)
            seen.append((url, m.get("author_name") or "?"))
    return seen


def pick_quotes(messages, max_quotes=12):
    """Pick representative substantive messages: longish, varied authors,
    spread across the channel's lifetime."""
    sub = [m for m in messages if 80 <= len(m.get("content") or "") <= 600]
    sub.sort(key=lambda m: m.get("timestamp", ""))
    seen_authors = set()
    out = []
    for m in sub:
        a = m.get("author_name")
        if a in seen_authors and len(out) >= 6:
            continue
        out.append(m)
        seen_authors.add(a)
        if len(out) >= max_quotes:
            break
    return out


def render_channel_page(channel, msgs):
    authors = Counter(m["author_name"] for m in msgs)
    timestamps = sorted(m["timestamp"] for m in msgs if m.get("timestamp"))
    links = extract_links(msgs)
    quotes = pick_quotes(msgs)

    body = []
    body.append(f"# `#{channel}`")
    body.append("")
    body.append(f"- **Total messages:** {len(msgs)}")
    body.append(f"- **Distinct authors:** {len(authors)}")
    if timestamps:
        body.append(f"- **First message:** {timestamps[0]}")
        body.append(f"- **Most recent:** {timestamps[-1]}")
    body.append("")

    if authors:
        body.append("## Top contributors")
        body.append("")
        for a, n in authors.most_common(10):
            body.append(f"- `{a}` — {n} messages")
        body.append("")

    if links:
        body.append("## Links shared in this channel")
        body.append("")
        body.append(f"({len(links)} unique URLs — capping at first 25.)")
        body.append("")
        for url, author in links[:25]:
            body.append(f"- {url}  *(shared by `{author}`)*")
        body.append("")

    if quotes:
        body.append("## Representative messages (chronological)")
        body.append("")
        body.append("Quotes are direct copies of the message content. Long messages are truncated with `…`.")
        body.append("")
        for m in quotes:
            content = (m["content"] or "").strip().replace("\n", " ")
            if len(content) > 500:
                content = content[:500] + "…"
            ts = (m.get("timestamp") or "")[:10]
            body.append(f"**`{m['author_name']}` · {ts} · `#{channel}`**")
            body.append("")
            body.append(f"> {content}")
            body.append("")

    body.append("## Notes for the interviewer")
    body.append("")
    body.append(f"- This is a dump-style page. To answer 'what was discussed in `#{channel}`', read the quotes above and follow contributors back to their member pages in `wiki/members/`.")
    body.append("- High-traffic channels are also given a hand-curated synthesis at the top of the page; this dump remains for auditing.")

    page = "---\n"
    page += f"title: \"Channel: #{channel}\"\n"
    page += "type: channel\n"
    page += "sources:\n"
    page += f"  - raw/messages.json#{channel}\n"
    page += "last_updated: 2026-05-08\n"
    page += "---\n\n"
    page += "\n".join(body)
    return page


def main():
    WIKI_CHANNELS.mkdir(parents=True, exist_ok=True)
    msgs = load_messages()
    by_channel = {}
    for m in msgs:
        by_channel.setdefault(m["channel_name"], []).append(m)

    n = 0
    for ch, ch_msgs in sorted(by_channel.items()):
        page = render_channel_page(ch, ch_msgs)
        out = WIKI_CHANNELS / f"{ch}.md"
        out.write_text(page, encoding="utf-8")
        n += 1
    print(f"wrote {n} channel pages")


if __name__ == "__main__":
    main()
