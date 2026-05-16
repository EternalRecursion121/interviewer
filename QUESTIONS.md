# Open questions for Sam

Things I wasn't sure about while building this wiki. Answer inline (delete or rewrite the question) and I'll act on them next session.

## Scope & purpose

1. **Who can read this wiki?** Just the interviewer, or all participants via a chatbot, or also organizers? The anti-hallucination protocol assumes a participant-facing audience — if it's organizer-only, I can relax some quote-rigor requirements.
   - _Your answer:_

2. **Does the interviewer write back to the wiki, or just read from it?** Right now the CLAUDE.md says it reads. The Affine fellowship description you pasted ("After the session, updates the wiki with the new information learned") implies it writes. If it writes, I should add structured slots for interview transcripts (e.g. `raw/interviews/<slug>/2026-05-15.md`) and a section schema for "interview notes" on participant pages.
   - _Your answer:_

3. **Is there a wiki-update review step?** If the interviewer writes back, should a human approve before changes land? This affects whether participant pages should be auto-generated (overwritable) or hand-editable.
   - _Your answer:_

## Data sources

4. **Are there other raw sources coming?** You mentioned participant intros — got those. Anything else (Slack/Discord export, schedule, talk recordings, project pages)? If yes, I'll wait for them before doing more synthesis.
   - _Your answer:_

5. **Is `samueljratnam@gmail.com` you (Samuel)?** The intros file has a "Samuel" entry with no content, just a photo placeholder. Should I add a participant page for you with whatever you'd like?
   - _Your answer:_

6. **Should the tech-tree sheet be re-synced over the course of the seminar?** The organizers may update it; I have `raw/fetch_sheet.sh` so re-running is one command. Want me to set up a cron / scheduled job, or do this manually?
   - _Your answer:_

## Cross-linking

7. **Are the auto-matched "Related concepts" on participant pages useful, or do they create more noise than signal?** I'm fuzzy-matching ~50 alias terms (e.g. "wireheading" → Wireheading concept). False positives possible. Glance at any participant page's "Related concepts" section and tell me if it's worth keeping.
   - _Your answer:_

8. **Should concept pages get participant backlinks?** ("People interested in Agency: Haru, Cara, Victor...") Currently they don't — concept pages are read-only generated. I can add a separate post-processing step that appends backlinks.
   - _Your answer:_

## Format & format-adjacent

9. **OK to keep the auto-generated participant pages "frozen"?** The CLAUDE.md anti-hallucination protocol assumes pages are write-once and only updated through new sources (intros, interviews). If you want participants to be able to edit their own pages, the schema needs rethinking.
   - _Your answer:_

10. **Are there sensitivity concerns about any of the intro content?** Some entries contain personal disclosures (cult upbringing, mental health framings, etc.). Right now everything from the intros file is reproduced verbatim. If you want to redact anything, mark it here.
    - _Your answer:_

11. **The pointers file** (`raw/Links for pointers at the core of the alignment problem.md`) — is this curated by you, by an organizer, or by someone else? The attribution matters for citation hygiene.
    - _Your answer:_

## Volume / pacing

12. **How big should this get?** With 23 participants × ~15-minute interviews × probable transcripts, we're looking at a wiki that could easily reach 100+ pages. Want a hard cap, or let it grow?
    - _Your answer:_
