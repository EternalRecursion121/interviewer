# unprocessed/ — the inbox

Raw material that hasn't been folded into the wiki yet. Three streams land here:

```
unprocessed/
  uploads/      one dir per upload batch: <UTC>__<label>/… + _manifest.json
  transcripts/  interview transcripts (JSON), one per session
  notes/        reflector notes (Markdown); a .draft.md sibling = participant edited it
```

Nothing in here is authoritative. The wiki is authoritative. This is the inbox
between "something happened" and "the wiki knows about it".

## The contract: integrate → processed

When the operator says **"integrate the unprocessed stuff"** (or similar), a
Claude session performs the *integrate pass*:

1. **Read** everything under `unprocessed/` (every upload batch, transcript, note).
2. For each item, decide what it touches per the wiki schema in
   [`../CLAUDE.md`](../CLAUDE.md) — a new concept? a participant update? a talk?
   a contradiction with an existing claim? — and **write/revise the relevant
   wiki pages with proper citations**, obeying the anti-hallucination protocol
   (no claim without a traceable source; quote, don't paraphrase beliefs;
   when in doubt, write less).
   - The original input *is* the citation source. Cite it as
     `[src: unprocessed/<...>]` while integrating; once moved (step 4) update
     the citation to `[src: processed/<...>]` so links stay valid.
3. **Append a log entry** to `wiki/log.md` with prefix
   `## [YYYY-MM-DD] integrate | <what was folded in>`.
4. **Move** each fully-consumed input from `unprocessed/<stream>/<item>` to
   `processed/<stream>/<item>` (preserving the relative path), so there's an
   audit trail and the inbox only ever holds *not-yet-integrated* material.
   - If an item is only *partially* usable, integrate what's usable, leave the
     item in `unprocessed/`, and note in the log why it wasn't fully consumed.
5. Update `wiki/index.md` if a new page was created.

Rules:
- This is not automated. It is a deliberate, operator-triggered Claude pass —
  the same care as a wiki ingest. Never auto-run it from the server.
- Never edit anything under `processed/` — it's a frozen archive of consumed
  inputs.
- Transcripts/notes can contain things the participant didn't consent to share
  publicly. Integrate the *signal* (what they care about / want to know / are
  worried about, positions, connections) into synthesis pages; do not paste
  verbatim private remarks into public wiki pages unless the wiki schema's
  citation + consent norms allow it. When unsure, leave it in `unprocessed/`
  and flag it in the log for a human.
