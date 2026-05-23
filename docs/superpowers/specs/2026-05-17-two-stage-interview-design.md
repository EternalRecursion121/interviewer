# Two-Stage Interview — Design

- **Date:** 2026-05-17
- **Status:** approved for planning
- **Repos affected:** `/root/interviewer` (server prompts + backend), `/root/idealists-site` (interview frontend)

## Problem

The single biggest behavioral failure in the current interviewer (confirmed across the transcript corpus) is that it **tunnels into the first topic, drills it to death, and never achieves breadth** — and that over-drilling correlates directly with the conversations participants abandoned (`megelia_e9fd5299`, `pi-star`, `sudarsh`). The interviewer has no map of the terrain when it starts, so it discovers the terrain by digging the first hole it finds.

Separately, the founder's own test interview (`samuel_140c2218`) named the data the format was *not* collecting: *"what draws people to the collective, what criticism and feedback, what they'd want in a personal newsletter."* And end-of-interview newsletter capture consistently ran into the time budget awkwardly (`david_8bd4a8db` — multi-turn newsletter ping past the clock).

## Solution

Split the interview into two stages:

- **Stage 1 — a short, optional, form-like breadth pass.** A time question (how long they want stage 2 to run) plus five pointed collective-facing prompts (the fifth captures newsletter preferences). Captured even if the participant never starts stage 2. ~2 minutes, rough notes, every field skippable.
- **Stage 2 — the existing conversational interview, now armed by stage 1.** It receives the stage-1 answers as a breadth map in its opening context and is explicitly instructed not to re-ask them cold and not to tunnel — it opens hot on the most alive thread and follows its curiosity across threads (its judgment: one deep vein or many).

Stage 1 is collective-facing breadth (value / criticism / ideas / involvement / newsletter). Stage 2 stays person-facing depth (what they care about, what they're worried about), but no longer has to spend the front of the conversation discovering where to go.

## Goals

1. Give stage 2 a terrain map so it stops tunneling and achieves breadth.
2. Reliably collect the value / criticism / ideas / involvement / newsletter data the founder asked for, including from people who never finish stage 2.
3. Seed a durable idea pool (prompt 3) that accumulates across participants.
4. Remove newsletter capture from the stage-2 close.

## Non-goals

- Not changing stage 2's voice, tools, safety model, or wiki access.
- Not branching the form by membership/familiarity (optionality absorbs the cold-visitor case — see Risks).
- Not fixing the notes-pipeline reliability bug here (tracked as a dependency — see Risks).

## Stage 1 — the form

**All fields optional**, presented as quick written notes ("a sentence is plenty; rough notes, not essays; skip anything you want"), with a visible "skip to the conversation" affordance so a fully-skipped stage 1 is one click.

**Time (logistics field, first):** *how long do you want the conversation to be? we'll check in and you can keep going.* A quick-pick control — preset chips **15 / 20 / 30 / 45 / 60 min** (20 visually suggested as the usual) plus an optional custom-minutes input and a **"no fixed limit"** option. Structured, not free text, so the backend never has to parse natural-language time ("until 3pm", "half an hour"). The value is either an integer of minutes or "no fixed limit".

**The five prompts:**

1. **what do you value about the collective?**
2. **where do you think we're falling short?**
3. **any ideas for things we could do differently, or things you wish existed?**
4. **would you like to get more involved? if so, what would you actually want to do?**
5. **newsletter — want one? how often, what would you want in it, what email?**

Rationale per prompt and how it arms stage 2:

| # | Dimension | Arms stage 2 by… |
|---|-----------|------------------|
| 1 | value | a concrete hook for a hot opener; the wiki currently lacks a map of what people actually get from the collective. |
| 2 | criticism | surfacing the vein the application form never got; stage 2 pushes deeper (system prompt already says invite criticism more than once). |
| 3 | ideas | seeding the idea pool; stage 2 pressure-tests ("would you run it?") — the move that produced the strongest line in `david_8bd4a8db`. |
| 4 | involvement | matchmaking + the open governance questions (roles, who'd want them); stage 2 turns "yes, vaguely" into specifics. |
| 5 | newsletter | structured capture up front, even for non-completers; removes the rushed end-of-stage-2 ask. |

Join-motivation and tenure are deliberately **not** asked — they already exist in `raw/application_responses.csv` and via `member()`; re-asking would waste the budget.

## Data flow

0. **Ordering:** `welcome` → `form` (stage 1: time question + five prompts) → `conversation` (stage 2). The time question is now captured in the form; the backend initializes the session time budget from it, so stage 2 does **not** ask it on turn 1 and opens directly with the substantive hot opener. The open-invitation ("ask me anything first") stays in stage 2's opening turn.
1. Frontend collects stage-1 answers (a new `form` phase in `interview/+page.svelte`'s phase machine, between `welcome` and `conversation`).
2. On submit, frontend POSTs the answers to a new backend endpoint, which:
   - persists them alongside the session (a `stage1` block in the transcript record, so the reflector and any future aggregation can read it);
   - if the newsletter answer is non-empty, writes a newsletter-subscription record using the **existing** `newsletter_subscriptions/` writer (the same artifact `capture_newsletter_preference` produces today);
   - if the time answer is an integer of minutes, initializes the session time budget to it (equivalent to `update_time_budget` at t=0, so the `<time>` tag works from turn 1). If "no fixed limit" or skipped, no budget is set.
3. The backend injects a rendered **breadth map** into stage 2's opening context (the first system/user turn that today carries the opening-turn instructions).
4. Stage 2 runs as today, minus the newsletter machinery.
5. The reflector (`notes.md` pass) reads the stage-1 block and folds it into the note.

## Stage 2 changes (`server/prompts/system.md`)

- **New "Stage 1 breadth map" block** in the opening context: presents the five answers and instructs, in spirit: *"You already have a breadth map. Do not re-ask these cold. Open hot on the most alive thread and follow your curiosity across threads — one deep vein or many, your call. The failure mode this map exists to prevent is tunneling into the first topic and never achieving breadth."*
- **Graceful degradation:** if the map is empty/sparse (everything skipped — typical for a cold visitor), the instruction says to fall back to today's externally-grounded opener (member()/application). Stage 2 must work with a blank stage 1.
- **Remove the "Personalised newsletters" section** entirely. Remove the newsletter step from the default arc (step 8) and simplify the close (step 9). Remove `capture_newsletter_preference` from the stage-2 toolset.
- **Meta-feedback** stays in the stage-2 close (it's conversational, not form-able) but is no longer adjacent to a newsletter ask.
- **Time handling:** the opening-turn instruction must stop asking "how long do you have" (the budget is pre-set from the form) and open directly with the substantive hot opener. The `## Time` section keeps `update_time_budget` for *mid-conversation extensions* ("let's go another 30") and the check-in-at-budget behavior, but drops the initial-ask. If the form's time field was skipped (no budget set), stage 2 falls back to today's behavior and asks the time question on turn 1 — same graceful-degradation pattern as the empty breadth map.

## Notes/reflector changes (`server/prompts/notes.md`)

- Reflector ingests the stage-1 block and folds it in: value → what's working / what they get from it (and `Surprises` if it contradicts the wiki's map of the collective); falling-short → criticism + `Positions on open questions` Q5; involvement → Q3/Q4 + matchmaking; ideas → a new **`## Ideas proposed`** section (verbatim idea + would-they-own-it + who to connect them with), which is also the structural input to a future cross-participant idea-pool aggregation page.
- Note explicitly when a prompt was skipped (a skipped criticism prompt is itself signal).

## Frontend changes (`/root/idealists-site/src/routes/interview/+page.svelte`)

- Add a `form` phase to the `Phase` union and the state machine, rendered between `welcome` and `conversation`.
- Five optional textareas + a one-click "skip to conversation".
- POST answers to the new backend endpoint; on success transition to `conversation`.
- This is a separate commit/branch from the existing `mobile-enter-newline` work.

## Error handling

- Form submission failure must not block the interview: on POST error, log and proceed to `conversation` with an empty map (stage 2 degrades gracefully by design).
- Empty/whitespace-only answers are treated as skipped, not stored as empty strings.
- Newsletter record is only written when the newsletter answer contains at least an email; otherwise no subscription artifact (no malformed records).
- Time "no fixed limit" or skipped → no budget set. On skip, stage 2 asks the time question on turn 1 (fallback); on explicit "no fixed limit", stage 2 proceeds without a budget and does not nag (same as today's "whenever" / "no rush").

## Testing / verification

- Backend: unit-test the stage-1 persistence + breadth-map rendering (including the all-skipped → empty-map case) and that a newsletter answer produces the same subscription artifact shape as `capture_newsletter_preference`.
- Backend: a selected/custom minutes value initializes the budget; "no fixed limit" and skipped both leave it unset (and are distinguishable, since skip triggers the turn-1 ask and "no fixed limit" does not).
- Prompt: a stage-2 smoke run with a populated map confirming it opens on a stage-1 thread without re-asking it verbatim and without re-asking the time question; and a run with an empty form confirming fallback to the current opener *and* the turn-1 time ask.
- Frontend: `npm run check` clean for the modified route; manual pass of submit and skip paths.

## Risks / dependencies

- **Drop-off risk:** a form *before* the conversation could worsen the very drop-off problem. Mitigations: all optional, one-click full skip, "2 min / rough notes" framing, graceful degradation so a skip costs nothing.
- **Hard dependency — notes-pipeline reliability.** The analysis found ~28% of reflector outputs are garbage (the model continues the conversation in-character or dumps the transcript; `pi-star`'s ~85-min interview produced 173 bytes; the strongest meta-feedback in the corpus was lost). Stage-1 data flowing into notes is only valuable if notes are actually written. This is **out of scope for this spec but a prerequisite for the value to be realized** — recommend a separate spec/plan (strict reflector output contract + `write_notes` validation/retry) sequenced alongside or before implementation.
- **Notes destination mismatch** (`notes.md` says `wiki/interviews/`, code writes `server/notes/`) is pre-existing and noted in the same dependency.
- **Cold visitors** can't answer collective-facing prompts; optionality + graceful degradation handle this without a branched form (YAGNI).
