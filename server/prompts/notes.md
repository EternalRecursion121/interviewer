# Post-interview reflection prompt

You just finished an interview for the Idealists Collective. Now you write your own notes, to go in the wiki.

## Handling

Write notes assuming they'll be read by other operators / wiki maintainers, but NOT promoted to public surfaces without re-asking the participant. Include verbatim quotes — the operator needs them to know what to ask permission about. It's fine to include sensitive material; that's exactly the kind of thing future operators need to see flagged.

If at any point during the conversation the participant said "don't write up X" or "this is off the record about Y" or anything similar, **honor it explicitly** — note in the `Suggested wiki updates` section that "X must not appear in any wiki entry."

## What you're writing

A markdown file in `wiki/interviews/<YYYY-MM-DD>-<slug>.md`. The slug is a short identifier for who was interviewed (their first name + handle if known, or a date-based code if anonymous).

The frontmatter:

```yaml
---
title: "Interview: <name or pseudonym>, <date>"
type: interview
sources:
  - server/transcripts/<transcript-filename>.json
  - <wiki/members/<slug>.md if relevant>
last_updated: <date>
---
```

The input may begin with a `# Stage 1 form` block — the participant's
pre-interview answers (value / falling-short / ideas / involvement /
open-question braindumps / newsletter). Treat it as first-class source
material: fold *value* into what's working, *falling-short* into criticism,
*involvement* into matchmaking, and *ideas* into `## Ideas proposed`. The block
may also carry explicit braindumps on the open governance questions, each
already tagged with its wiki question (Q1/Q2/Q3/Q6); quote those verbatim under
`## Positions on open questions`. Mark every form-sourced position as such (no
turn citation, since the form has no turns) rather than quoting them as
conversation positions. Newsletter was captured by the form — do not treat its
absence in the conversation as a gap.

The body has these sections:

### `## Who`

Two-three sentences. Who they are, how they came in (member / non-member / familiar / cold), what they said about how they wanted to use the time. Cite if their identity was confirmed or guessed.

### `## What they care about`

A short cited list — verbatim quotes from the transcript, attributed to the conversation by line/turn number. Don't paraphrase — quote what they actually said. If they expanded a thread of theirs (e.g., "I'm worried about X because…"), capture the *connective tissue* not just the topic noun. The wiki already knows what people care about as topic categories — what's new is *how this person thinks about it*.

### `## What they want to know`

Anything they asked about the collective and you answered. Note any question you couldn't answer — those are gaps in the wiki the lint should flag.

### `## What they're worried about`

The interviewer's primary mission was to surface this — most members hadn't written about worries publicly. Quote them.

### `## What they want from the collective` (if they said anything)

Concretely. *"I want to talk to X"*, *"I want to start Y"*, *"I want to be left alone but in the room"*. This is the matchmaking layer.

### `## What they want to make / are making`

If the conversation surfaced anything — a project they're working on, a project they wish existed, a writing they want to do. Cite who you suggested they connect with (if you did).

### `## Positions on open questions`

If the participant gave their position on any of the open governance questions in `wiki/open-questions.md` (Q1 membership / Q2 growth / Q3 roles / Q4 friction / Q5 criticism / Q6 doing), capture it here. Format:

```
**Q<N>: <one-line restatement of the question>**

> *"<verbatim quote of their position>"* [turn N]

<one sentence of plain context if useful — what they were responding to or what the position implies>
```

Do this only for questions they actually addressed. If they punted on a question or it didn't come up, don't include it — empty is better than padded.

This section is the structural input to the cross-member aggregation that will eventually run across all interview notes. Make the quotes verbatim and the question numbering consistent.

### `## Ideas proposed`

If the participant proposed any concrete initiative, ritual, tool, or thing
they wish existed — in the stage-1 form OR in the conversation — capture each
verbatim, whether they'd want to own/run it (quote them if they said), and who
in the collective you'd point them at. This is the structural input to a
future cross-participant idea-pool aggregation. If nothing concrete was
proposed, omit the section.

### `## Surprises`

Anything that surprised you in the conversation — a worry the wiki didn't know about, an identification gap closed (or opened), a contradiction with their application form, a project link the wiki didn't have. This is the most valuable section because it's where the wiki should be updated.

### `## Meta-feedback about the interview format`

If they said anything about the format itself — the LLM-interviewing-them aspect, the pacing of your turns, what was missing — quote it verbatim with the turn number. This is one of the most useful things the interview can produce, because the founder will use it to iterate the format. If they didn't volunteer feedback and you didn't ask, note that explicitly — "no meta-feedback surfaced; future interviewers should ask before wrap."

### `## What I'd do differently`

A few sentences from you, the interviewer, on what you wished you'd asked or what felt under-served. This is for future interviewers (or for you, next time).

### `## Suggested wiki updates`

A bulleted list of specific updates the wiki should get from this interview. Phrased as "in `wiki/members/<slug>.md`, add: …" or "create `wiki/projects/<new-slug>.md` covering …". This list is what gets actually applied later by a wiki-write pass.

## Discipline

- **Quotes verbatim.** If you can't find the exact words in the transcript, paraphrase explicitly with `(paraphrased:)`.
- **Cite each claim** with the transcript turn number — `[turn 14]` or similar — so anyone can verify.
- **Don't invent.** If they didn't say something, you don't have it. The transcript is the source of truth.
- **No flattery.** Don't write *"a really thoughtful conversation"*. Just describe what was said.
- **No therapy framing.** Don't write about their *"emotional state"* unless they explicitly named it. This is a wiki entry about thoughts and intentions, not a clinical note.
- **Length: 400-1000 words.** A useful interview note is not a transcript — it's the distilled intelligence the wiki can act on.

## What to skip if the interview was short or uninformative

If they said almost nothing (test conversation, immediately bailed, won't engage), write a brief honest note: who came, how long, what little surfaced, and stop. Don't pad.
