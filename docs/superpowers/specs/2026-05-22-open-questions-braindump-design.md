# Open-Questions Braindump — Design

- **Date:** 2026-05-22
- **Status:** approved for planning
- **Repos affected:** `/root/interviewer` (server + tests), `/root/idealists-site` (interview frontend)
- **Extends:** the two-stage interview (`docs/superpowers/specs/2026-05-17-two-stage-interview-design.md`, PRs #1 / #9). New commits land on the existing branches `two-stage-interview` and `mobile-enter-newline`; no new PRs.

## Problem

The collective has six documented open governance questions (`wiki/open-questions.md`, Q1–Q6). Stage 2 surfaces 1–2 of them conversationally and the reflector captures positions under `## Positions on open questions`. But a single conversation can only reach a couple, and a structurally-minded participant may have thoughts on questions the conversation never touches. There is currently no low-pressure place to leave those thoughts up front.

## Solution

Add an optional, collapsed-by-default **"open questions"** section to the stage-1 form: a braindump area whose questions are themselves individually collapsed. A participant who doesn't care sees one collapsed line; a participant who does can expand the section and then expand whichever questions pull at them. Answers feed the stage-2 breadth map and the reflector's `## Positions on open questions` section.

## Scope of the question set

Four of the six wiki questions, **renumbered 1–4 for display** but keyed internally by semantic slug so the data still maps to the canonical wiki question:

| Form # | Display question | Wiki ID | Data key |
|---|---|---|---|
| 1 | how should new membership be handled? | Q1 | `membership` |
| 2 | should the collective grow — and if so, how? | Q2 | `growth` |
| 3 | what roles of responsibility should exist, and who'd want them? | Q3 | `roles` |
| 4 | how do we shift from talking to actually doing? | Q6 | `action` |

Wiki **Q4** ("what's stopping members from participating more") and **Q5** ("what could we do better — what do you actively not like") are deliberately **omitted**: broad stage-1 prompt 4 ("would you like to get more involved?") and prompt 2 ("where do you think we're falling short?") already cover that ground, and repeating them would make the form feel like it's asking twice.

Semantic keys (`membership`/`growth`/`roles`/`action`) rather than `q1`/`q6` avoid a data shape that reads as "why does q6 follow q3".

## UI

A native `<details>`/`<summary>` section, **everything collapsed by default**, placed between the involvement prompt and the newsletter toggle:

```
how long do you want the conversation to be?    [chips]
what do you value about the collective?          [textarea]
where do you think we're falling short?           [textarea]
any ideas for things you wish existed?            [textarea]
would you like to get more involved?              [textarea]

▸ open questions                       optional
   └─ (expanded:)
      braindump on as many as you like.
      ▸ how should new membership be handled?
      ▸ should the collective grow — and if so, how?
         └─ (expanded:)  <context blurb>   [textarea, rows=2]
      ▸ what roles of responsibility should exist, and who'd want them?
      ▸ how do we shift from talking to actually doing?

☐ i'd like a personalised newsletter
[ start the conversation ]    [ skip straight to it ]
```

- The outer `<details class="s1-section">` summary reads **"open questions"** with a muted **"optional"** hint span. No other framing copy on the summary line.
- When the section is expanded, a single lede line: **"braindump on as many as you like."**
- Each of the four questions is an inner `<details class="s1-q">`, collapsed by default. Its `<summary>` is the display question; expanding it reveals a one-line factual context blurb and a `rows="2"` textarea (`class="s1-input"`, matching the existing stage-1 fields).
- Native `<details>` is used over a JS/`$state` accordion: zero JS, keyboard-accessible, and it is exactly the expand-section-then-expand-question nesting required.

### Context blurbs (final copy — implementer uses verbatim)

Condensed from `wiki/open-questions.md`, lowercase to match the form:

1. **membership:** "samuel reads every application solo and decides who's invited. it's worked for ~130 applications, but it isn't scalable or democratic."
2. **growth:** "growth so far is referral-driven. is more reach worth wanting? if so, how — and at what cost to coherence?"
3. **roles:** "the collective has no formal roles — things happen because someone decides to do them."
4. **action:** "long threads, a deferred unconference, drafts, projects 'in planning'. what's the practical lever?"

## Data shape

A new optional `open_questions` block on the stage-1 payload, sitting alongside `value` / `falling_short` / `ideas` / `involvement`:

```
open_questions: {
    membership: str | None,
    growth: str | None,
    roles: str | None,
    action: str | None,
} | None
```

Each field is whitespace-trimmed; empty → `None`. The whole block is `None` when all four are blank — the same skipped-means-skipped rule the existing text fields use, so a fully-collapsed section contributes nothing to the record. `open_questions` being non-`None` does **not** by itself make a stage-1 payload non-empty unless at least one field is set (it never will be otherwise, by construction).

## Data flow

1. Frontend collects the four braindumps in four new `$state` strings; `buildStage1()` assembles the `open_questions` block (`null` if all blank).
2. The block rides along in the existing stage-1 POST — no new endpoint.
3. Backend `normalize_stage1` cleans it into the canonical shape.
4. `render_breadth_map` adds the answered open questions to the `<stage1_breadth_map>` injected into stage 2's opening turn.
5. `format_stage1_for_notes` adds them to the reflector input, tagged with their canonical wiki question, so the reflector folds them into `## Positions on open questions`.

## Backend changes (`/root/interviewer`)

### `server/stage1.py`

- Update the module-docstring canonical-shape comment to include `open_questions`.
- Add a constant mapping the four slugs to `(wiki Q-number, canonical question text)` — the single source of truth for labels in both rendering functions.
- `normalize_stage1`: clean a raw `open_questions` dict into `{slug: str|None}`; if all four are `None`, set `open_questions` to `None`. Fold `open_questions` into the existing "is the whole payload empty?" check.
- `render_breadth_map`: after the existing fields, emit any answered open questions as `- Open question (membership): "<text>"` lines, plus an instruction in the same spirit as the existing preamble — *they've already left thoughts on these specific open questions, so go deeper there or skip them, don't surface them cold; the open questions they did not answer are still fair game.* If no open questions were answered, emit nothing for them. The function still returns `""` only when there is nothing substantive at all.
- `format_stage1_for_notes`: emit answered open questions under their canonical wiki label (e.g. `- Open question Q3 (roles): <text>`), so the reflector can attribute them.

### `server/app.py`

- Add a `Stage1OpenQuestions` Pydantic model with four optional `str` fields (`membership`, `growth`, `roles`, `action`).
- Add an optional `open_questions: Stage1OpenQuestions | None` field to `Stage1Payload`.
- No change to `_apply_stage1` logic beyond the payload now carrying the extra block — `normalize_stage1` already owns the cleaning.

## Frontend changes (`/root/idealists-site`)

### `src/lib/interviewer-client.ts`

- Add an `open_questions?` field to the `Stage1` interface, typed as an object of four optional `string` fields (or `null`).

### `src/routes/interview/+page.svelte`

- Four new `$state('')` strings for the braindump textareas.
- `buildStage1()`: assemble the `open_questions` object via the existing `t()` trim helper; set it to `null` when all four are blank.
- Markup: the nested `<details>` section described in **UI**, inserted between the involvement `<label class="field">` and the newsletter toggle.
- Scoped CSS for `.s1-section` / `.s1-q` / the summary hint / the context blurb — matching the existing stage-1 visual language (lowercase, the `.field` rhythm). Textareas reuse the existing `.s1-input` class.

## Notes / reflector changes (`server/prompts/notes.md`)

`notes.md` already tells the reflector a form question "may seed `Positions on open questions` — but mark them as form-sourced". Add one sentence making the new mapping explicit: the stage-1 `open_questions` braindumps map directly onto wiki Q1/Q2/Q3/Q6 and should be quoted verbatim under `## Positions on open questions`, marked form-sourced. No change to `system.md` — the breadth map is self-describing and injected into the opening turn.

## Error handling

- Empty / whitespace-only braindumps are treated as skipped, never stored as empty strings (the existing `t()` / `_clean` behaviour).
- A malformed or absent `open_questions` block degrades to `None` — `normalize_stage1` must not raise on a non-dict value.
- No new failure surface on submit: the block travels inside the existing stage-1 POST, which already proceeds to the conversation on POST error.

## Testing / verification

- **Backend (pytest, `server/`):** extend the stage-1 tests —
  - `normalize_stage1` with `open_questions` fully populated, partially populated, and all-blank (→ `open_questions` is `None`);
  - the all-fields-skipped payload still normalizes to `None` overall;
  - a non-dict `open_questions` value normalizes to `None` without raising;
  - `render_breadth_map` includes the open-question lines and instruction when answered, and omits them when not;
  - `format_stage1_for_notes` includes answered open questions under their canonical Q-labels.
- **Backend smoke (`server/smoke_test.py`):** extend the form-armed path to populate one open question and confirm the breadth map carries it.
- **Frontend:** `npm run check` clean for the modified route (no regression past the known baseline); manual pass of expand/collapse nesting, submit, and skip.

## Risks

- **Form-length creep.** The stage-1 form risks feeling heavier. Mitigated by collapsed-by-default nesting: the section is one line until opted into, and the spec's two-stage design already leans on optionality + one-click full skip.
- **Drift from the wiki.** The four questions are hard-coded in the frontend rather than served from `wiki/open-questions.md`. Accepted: the wiki list is deliberately short and slow-changing (its own process note says edits are manual and rare). A frontend comment points to `wiki/open-questions.md` as canonical; if the wiki list changes, the form is updated by hand.
- **Inherited dependency.** The two-stage design's notes-pipeline reliability risk still applies — open-question braindumps are only as durable as the reflector output that consumes them. Out of scope here, same as in the parent spec.
