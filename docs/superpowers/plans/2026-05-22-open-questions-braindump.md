# Open-Questions Braindump Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, collapsed-by-default "open questions" section to the stage-1 interview form, letting participants braindump on four governance questions that then arm stage 2.

**Architecture:** A nested native `<details>`/`<summary>` UI block in the SvelteKit interview page collects four optional braindumps; they ride along in the existing stage-1 POST as an `open_questions` block, are normalized by `server/stage1.py`, and surface in both the stage-2 breadth map and the reflector's notes input.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 / pytest (interviewer backend, `/root/interviewer`, branch `two-stage-interview`); SvelteKit / Svelte 5 runes / TypeScript (frontend, `/root/idealists-site`, branch `mobile-enter-newline`).

**Spec:** `docs/superpowers/specs/2026-05-22-open-questions-braindump-design.md`

**Two repos / two branches.** Tasks 1–5 are in `/root/interviewer` on the already-checked-out branch `two-stage-interview`. Tasks 6–7 are in `/root/idealists-site` on the already-checked-out branch `mobile-enter-newline`. Do not create branches; do not switch branches. These branches back open PRs (#1 and #9) — new commits update them in place.

**Commit identity.** A repo guardrail blocks commits authored under a human identity. Every commit command in this plan therefore uses an explicit Claude identity: `git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit ...`. Keep the `Co-Authored-By` trailer shown in each commit step.

**Backend test command:** `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`

---

## File Structure

**Backend (`/root/interviewer`):**
- `server/stage1.py` — pure stage-1 helpers. Gains an `OPEN_QUESTIONS` constant + a `_clean_open_questions` helper; `normalize_stage1`, `render_breadth_map`, `format_stage1_for_notes` all learn the new block.
- `server/app.py` — adds a `Stage1OpenQuestions` Pydantic model and an `open_questions` field on `Stage1Payload`. `_apply_stage1` is unchanged (it already round-trips the whole payload through `normalize_stage1`).
- `server/tests/test_stage1.py` — new test cases.
- `server/smoke_test.py` — the form-armed smoke path gains an open-question answer.
- `server/prompts/notes.md` — one prose change so the reflector maps the braindumps to `## Positions on open questions`.

**Frontend (`/root/idealists-site`):**
- `src/lib/interviewer-client.ts` — adds a `Stage1OpenQuestions` interface + `open_questions` field on `Stage1`.
- `src/routes/interview/+page.svelte` — adds the `OPEN_QUESTIONS` constant, the `s1OpenQuestions` form state, the `buildStage1()` assembly, the nested `<details>` markup, and scoped CSS.

---

## Task 1: stage1.py — open-questions normalization

**Files:**
- Modify: `/root/interviewer/server/stage1.py`
- Test: `/root/interviewer/server/tests/test_stage1.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_stage1.py`:

```python
def test_normalize_open_questions_populated():
    out = normalize_stage1(
        {"open_questions": {
            "membership": "  vouching  ", "growth": "stay small",
            "roles": "a rotating crew", "action": "ship weekly"}}
    )
    assert out is not None
    assert out["open_questions"] == {
        "membership": "vouching", "growth": "stay small",
        "roles": "a rotating crew", "action": "ship weekly"}


def test_normalize_open_questions_partial():
    out = normalize_stage1(
        {"open_questions": {"membership": "vouching", "growth": "  ",
                            "roles": "", "action": None}}
    )
    assert out["open_questions"] == {
        "membership": "vouching", "growth": None, "roles": None, "action": None}


def test_normalize_open_questions_all_blank_is_none():
    out = normalize_stage1(
        {"value": "x", "open_questions": {"membership": " ", "growth": "", "roles": None}}
    )
    assert out["open_questions"] is None


def test_normalize_open_questions_non_dict_is_none():
    out = normalize_stage1({"value": "x", "open_questions": "not a dict"})
    assert out["open_questions"] is None
    # a non-dict open_questions with nothing else is still an empty payload
    assert normalize_stage1({"open_questions": "not a dict"}) is None


def test_normalize_open_questions_alone_is_not_empty():
    out = normalize_stage1({"open_questions": {"roles": "rotating committee"}})
    assert out is not None
    assert out["open_questions"] == {
        "membership": None, "growth": None,
        "roles": "rotating committee", "action": None}
```

Also update the existing exact-match test `test_normalize_strips_and_keeps_present_fields` — its `assert out == {...}` will now be missing the new key. Add one line to the expected dict, immediately after the `"newsletter": {...}` line:

```python
        "newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": None},
        "open_questions": None,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`
Expected: the five new `test_normalize_open_questions_*` tests FAIL (KeyError on `out["open_questions"]`), and `test_normalize_strips_and_keeps_present_fields` FAILS on the dict comparison.

- [ ] **Step 3: Implement the constant and helper**

In `server/stage1.py`, after the `TEXT_FIELDS` line (line 25), add:

```python
# The open governance questions the stage-1 form lets participants braindump
# on — a trimmed subset of wiki/open-questions.md. Q4 ("what's stopping you")
# and Q5 ("what could we do better") are omitted because broad stage-1 prompts
# 4 and 2 already cover that ground. Each tuple is
# (slug, wiki Q-number, short question text): the slug keys the data, the
# Q-number attributes the braindump to the right `## Positions on open
# questions` bucket. wiki/open-questions.md is canonical — keep this in sync
# by hand.
OPEN_QUESTIONS = (
    ("membership", "Q1", "How should new membership be handled?"),
    ("growth", "Q2", "Should the collective grow — and if so, how?"),
    ("roles", "Q3", "What roles of responsibility should exist, and who'd want them?"),
    ("action", "Q6", "How do we shift from talking to actually doing?"),
)
OPEN_QUESTION_KEYS = tuple(slug for slug, _, _ in OPEN_QUESTIONS)
```

After the `_coerce_minutes` function (after line 40), add the helper:

```python
def _clean_open_questions(v) -> dict | None:
    """Clean a raw open_questions dict to {slug: str|None}, or None if all blank."""
    if not isinstance(v, dict):
        return None
    cleaned = {k: _clean(v.get(k)) for k in OPEN_QUESTION_KEYS}
    return cleaned if any(cleaned.values()) else None
```

- [ ] **Step 4: Wire it into `normalize_stage1`**

In `normalize_stage1`, after the `newsletter` block (after line 61), add:

```python
    open_questions = _clean_open_questions(raw.get("open_questions"))
```

Change the `out` dict to include the new key:

```python
    out = {
        **text,
        "time_minutes": time_minutes,
        "no_time_limit": no_time_limit,
        "newsletter": newsletter,
        "open_questions": open_questions,
    }
```

Change the "empty" guard to also require `open_questions is None`:

```python
    if (
        all(out[f] is None for f in TEXT_FIELDS)
        and time_minutes is None
        and not no_time_limit
        and newsletter is None
        and open_questions is None
    ):
        return None
    return out
```

Update the module docstring's canonical-shape comment (the block at lines 4–18) to add the new field after `newsletter`:

```python
        "newsletter": {                 # None unless they gave at least an email
            "email": str | None,
            "frequency": str | None,
            "interested_in": str | None,
        } | None,
        "open_questions": {             # None unless ≥1 braindump is non-empty
            "membership": str | None,
            "growth": str | None,
            "roles": str | None,
            "action": str | None,
        } | None,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`
Expected: all tests PASS (the pre-existing tests plus the six touched/added in this task).

- [ ] **Step 6: Commit**

```bash
cd /root/interviewer && git add server/stage1.py server/tests/test_stage1.py
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
stage1: normalize the open_questions braindump block

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: stage1.py — open questions in the breadth map

**Files:**
- Modify: `/root/interviewer/server/stage1.py` (`render_breadth_map`)
- Test: `/root/interviewer/server/tests/test_stage1.py`

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_stage1.py`:

```python
def test_render_breadth_map_includes_open_questions():
    bm = render_breadth_map(
        {"value": "the people", "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": None, "no_time_limit": False,
         "newsletter": None,
         "open_questions": {"membership": None, "growth": None,
                            "roles": "a rotating committee", "action": None}}
    )
    assert "a rotating committee" in bm
    assert "roles" in bm.lower()
    assert "do NOT surface them cold" in bm


def test_render_breadth_map_open_questions_alone_still_renders():
    bm = render_breadth_map(
        {"value": None, "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": 20, "no_time_limit": False,
         "newsletter": None,
         "open_questions": {"membership": "vouching", "growth": None,
                            "roles": None, "action": None}}
    )
    assert bm.startswith("<stage1_breadth_map>")
    assert "vouching" in bm
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -k breadth_map -v`
Expected: the two new tests FAIL (`"a rotating committee"`/`"vouching"` not in output).

- [ ] **Step 3: Rewrite `render_breadth_map`**

Replace the whole `render_breadth_map` function body (currently lines 110–132) with:

```python
def render_breadth_map(stage1: dict | None) -> str:
    """The <stage1_breadth_map> block injected into stage 2's opening turn.

    Returns "" when there is nothing substantive to show (the time-only or
    skipped case) so the caller can fall back to the legacy opener.
    """
    if not stage1:
        return ""
    lines = []
    for key, label in _MAP_FIELDS:
        val = stage1.get(key)
        if val:
            lines.append(f'- {label}: "{val}"')

    oq = stage1.get("open_questions") or {}
    oq_answered = [(text, oq[slug]) for slug, _, text in OPEN_QUESTIONS if oq.get(slug)]
    has_newsletter = bool(stage1.get("newsletter"))

    if not lines and not oq_answered and not has_newsletter:
        return ""

    if oq_answered:
        lines.append(
            "- Open questions they already wrote thoughts on. Go deeper on "
            "these or skip them — do NOT surface them cold. The open questions "
            "they left blank are still fair game:"
        )
        lines.extend(f'  - {text}: "{val}"' for text, val in oq_answered)

    if has_newsletter:
        lines.append(
            "- Newsletter: already captured via the form — do NOT ask about "
            "the newsletter in the conversation."
        )
    body = "\n".join(lines)
    return f"<stage1_breadth_map>\n{_MAP_PREAMBLE}\n\n{body}\n</stage1_breadth_map>"
```

This is a behaviour-preserving restructure for the non-open-questions case: the early-return now also accounts for `oq_answered`, and the newsletter line moved below the (new) open-questions block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`
Expected: all tests PASS — including the pre-existing `test_render_breadth_map_empty` and `test_render_breadth_map_includes_only_present_fields`, which pass dicts with no `open_questions` key and must still behave identically.

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer && git add server/stage1.py server/tests/test_stage1.py
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
stage1: surface open-question braindumps in the breadth map

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: stage1.py — open questions in the reflector notes input

**Files:**
- Modify: `/root/interviewer/server/stage1.py` (`format_stage1_for_notes`)
- Test: `/root/interviewer/server/tests/test_stage1.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_stage1.py`:

```python
def test_format_stage1_for_notes_includes_open_questions():
    s = format_stage1_for_notes(
        {"value": "x", "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": None, "no_time_limit": False,
         "newsletter": None,
         "open_questions": {"membership": "a vouching model", "growth": None,
                            "roles": None, "action": None}}
    )
    assert "Open question Q1" in s
    assert "a vouching model" in s
    assert "Positions on open questions" in s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py::test_format_stage1_for_notes_includes_open_questions -v`
Expected: FAIL (`"Open question Q1"` not in output).

- [ ] **Step 3: Extend `format_stage1_for_notes`**

In `format_stage1_for_notes`, after the newsletter `if nl:` block and before `return "\n".join(lines)`, add:

```python
    oq = stage1.get("open_questions")
    if oq:
        for slug, qnum, text in OPEN_QUESTIONS:
            val = oq.get(slug)
            if val:
                lines.append(
                    f"- Open question {qnum} ({text}): {val} "
                    "— form-sourced; fold into `## Positions on open questions`"
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`
Expected: all tests PASS — the pre-existing `test_format_stage1_for_notes_plain_block` passes a dict with no `open_questions` key and must be unaffected.

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer && git add server/stage1.py server/tests/test_stage1.py
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
stage1: fold open-question braindumps into the reflector notes input

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: app.py — Pydantic models for the open_questions block

**Files:**
- Modify: `/root/interviewer/server/app.py:63-76`
- Test: `/root/interviewer/server/tests/test_stage1.py`

- [ ] **Step 1: Write the failing test**

Append to `server/tests/test_stage1.py`. This test guards the seam between the app-layer Pydantic model and `normalize_stage1` — a field-name mismatch is the realistic bug here:

```python
def test_stage1_payload_model_carries_open_questions():
    from app import Stage1Payload
    payload = Stage1Payload(open_questions={"membership": "vouching", "roles": "rotating"})
    out = normalize_stage1(payload.model_dump())
    assert out is not None
    assert out["open_questions"] == {
        "membership": "vouching", "growth": None,
        "roles": "rotating", "action": None}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py::test_stage1_payload_model_carries_open_questions -v`
Expected: FAIL — `Stage1Payload` rejects the unknown `open_questions` kwarg, or `model_dump()` omits it so `out["open_questions"]` is `None`.

- [ ] **Step 3: Add the model and field**

In `server/app.py`, immediately after the `Stage1Newsletter` class (after line 66) and before `class Stage1Payload`, insert:

```python
class Stage1OpenQuestions(BaseModel):
    membership: Optional[str] = None
    growth: Optional[str] = None
    roles: Optional[str] = None
    action: Optional[str] = None
```

In `class Stage1Payload`, add a final field after the `newsletter` line:

```python
    newsletter: Optional[Stage1Newsletter] = None
    open_questions: Optional[Stage1OpenQuestions] = None
```

`_apply_stage1` needs no change — it already does `req.stage1.model_dump()` and hands the whole dict to `normalize_stage1`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer && git add server/app.py server/tests/test_stage1.py
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
app: accept the stage-1 open_questions block on the session request

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: smoke_test.py + notes.md — exercise and document the new block

**Files:**
- Modify: `/root/interviewer/server/smoke_test.py:26-36`
- Modify: `/root/interviewer/server/prompts/notes.md:28-36`

- [ ] **Step 1: Add an open question to the smoke payload**

In `server/smoke_test.py`, the `normalize_stage1({...})` call currently ends with `"newsletter": None,`. Add an `open_questions` entry after it:

```python
            "newsletter": None,
            "open_questions": {
                "roles": "a small rotating crew for events and the website",
            },
```

- [ ] **Step 2: Verify the smoke file still parses**

Run: `cd /root/interviewer && python -m py_compile server/smoke_test.py`
Expected: no output, exit 0.

- [ ] **Step 3: Update the reflector prompt**

In `server/prompts/notes.md`, replace the paragraph at lines 28–36 (the one beginning "The input may begin with a `# Stage 1 form` block") in full with:

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
```

- [ ] **Step 4: Run the backend test suite as a regression check**

Run: `cd /root/interviewer/server && uv run pytest tests/test_stage1.py -v`
Expected: all tests PASS (this task changes no logic; the run confirms nothing regressed).

- [ ] **Step 5: Commit**

```bash
cd /root/interviewer && git add server/smoke_test.py server/prompts/notes.md
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
stage1: exercise open_questions in the smoke test, document it for the reflector

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: interviewer-client.ts — TypeScript types for the open_questions block

**Files:**
- Modify: `/root/idealists-site/src/lib/interviewer-client.ts:18-32`

This task and Task 7 are in the **`/root/idealists-site`** repo on branch **`mobile-enter-newline`**. There is no frontend unit-test harness; verification is `npm run check`.

- [ ] **Step 1: Add the interface and field**

In `src/lib/interviewer-client.ts`, immediately after the `Stage1Newsletter` interface (after line 22), insert:

```ts
export interface Stage1OpenQuestions {
	membership?: string | null;
	growth?: string | null;
	roles?: string | null;
	action?: string | null;
}
```

In the `Stage1` interface, add a final field after `newsletter`:

```ts
	newsletter?: Stage1Newsletter | null;
	open_questions?: Stage1OpenQuestions | null;
}
```

- [ ] **Step 2: Verify the type-check is clean**

Run: `cd /root/idealists-site && npm run check`
Expected: no NEW errors or warnings introduced by this change. The route has a known pre-existing baseline (~8 errors / ~32 warnings) unrelated to this work; compare against that — the count must not rise.

- [ ] **Step 3: Commit**

```bash
cd /root/idealists-site && git add src/lib/interviewer-client.ts
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
interviewer-client: type the stage-1 open_questions block

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: +page.svelte — the open-questions form section

**Files:**
- Modify: `/root/idealists-site/src/routes/interview/+page.svelte` — script (`~line 42`), `buildStage1` (`~line 81-103`), form markup (`~line 879`), `<style>` (before `</style>` at `~line 2232`).

- [ ] **Step 1: Add the questions constant and form state**

In the `<script>` block, immediately after the `const TIME_CHOICES = [15, 20, 30, 45, 60];` line (line 42), add the constant. The `label` and `context` copy below is final — use it verbatim:

```ts
	const OPEN_QUESTIONS = [
		{
			key: 'membership',
			label: 'how should new membership be handled?',
			context:
				"samuel reads every application solo and decides who's invited. it's worked for ~130 applications, but it isn't scalable or democratic."
		},
		{
			key: 'growth',
			label: 'should the collective grow — and if so, how?',
			context:
				'growth so far is referral-driven. is more reach worth wanting? if so, how — and at what cost to coherence?'
		},
		{
			key: 'roles',
			label: "what roles of responsibility should exist, and who'd want them?",
			context:
				'the collective has no formal roles — things happen because someone decides to do them.'
		},
		{
			key: 'action',
			label: 'how do we shift from talking to actually doing?',
			context:
				"long threads, a deferred unconference, drafts, projects 'in planning'. what's the practical lever?"
		}
	] as const;
```

In the "Stage-1 form state" block, after `let s1Involvement = $state('');` (line 36), add:

```ts
	let s1OpenQuestions = $state({ membership: '', growth: '', roles: '', action: '' });
```

- [ ] **Step 2: Assemble the block in `buildStage1()`**

In `buildStage1()`, after the `newsletter` const (after line 93) and before `return {`, add:

```ts
		const oq = {
			membership: t(s1OpenQuestions.membership),
			growth: t(s1OpenQuestions.growth),
			roles: t(s1OpenQuestions.roles),
			action: t(s1OpenQuestions.action)
		};
		const open_questions = Object.values(oq).some((v) => v !== null) ? oq : null;
```

Add `open_questions` to the returned object, after `newsletter`:

```ts
		return {
			value: t(s1Value),
			falling_short: t(s1FallingShort),
			ideas: t(s1Ideas),
			involvement: t(s1Involvement),
			time_minutes: s1NoTimeLimit ? null : s1TimeMinutes,
			no_time_limit: s1NoTimeLimit,
			newsletter,
			open_questions
		};
```

- [ ] **Step 3: Add the nested `<details>` markup**

In the `{:else if phase === 'form'}` block, the involvement field's closing `</label>` is at line 879, and the newsletter toggle `<label class="field newsletter-toggle">` starts at line 881. Insert this block between them (after line 879, before line 881):

```svelte
				<details class="s1-section">
					<summary>
						<span class="field-label">open questions</span>
						<span class="s1-hint">optional</span>
					</summary>
					<p class="s1-section-lede">braindump on as many as you like.</p>
					{#each OPEN_QUESTIONS as q}
						<details class="s1-q">
							<summary>{q.label}</summary>
							<p class="s1-q-context">{q.context}</p>
							<textarea
								class="s1-input"
								rows="2"
								bind:value={s1OpenQuestions[q.key]}
								disabled={busy}
							></textarea>
						</details>
					{/each}
				</details>
```

- [ ] **Step 4: Add scoped CSS**

In the `<style>` block, immediately before the closing `</style>` (line 2232), add:

```css
	.s1-section {
		border-top: 1px solid var(--rule, rgba(0, 0, 0, 0.15));
		padding-top: 0.9rem;
	}
	.s1-section > summary,
	.s1-q > summary {
		cursor: pointer;
		user-select: none;
	}
	.s1-section > summary {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}
	.s1-hint {
		font-family: var(--font-mono);
		font-size: 0.65rem;
		text-transform: lowercase;
		letter-spacing: 0.1em;
		opacity: 0.4;
	}
	.s1-section-lede {
		font-family: var(--font-mono);
		font-size: 0.7rem;
		letter-spacing: 0.06em;
		opacity: 0.55;
		margin: 0.7rem 0 0.2rem;
	}
	.s1-q {
		margin-top: 0.7rem;
		padding-left: 1rem;
		border-left: 1px solid var(--rule, rgba(0, 0, 0, 0.12));
	}
	.s1-q > summary {
		font-family: var(--font-mono);
		font-size: 0.7rem;
		text-transform: lowercase;
		letter-spacing: 0.08em;
		opacity: 0.7;
		color: var(--heading);
	}
	.s1-q-context {
		font-size: 0.85rem;
		opacity: 0.5;
		line-height: 1.55;
		margin: 0.5rem 0;
	}
	.s1-q .s1-input {
		margin-top: 0.2rem;
	}
```

- [ ] **Step 5: Verify the type-check is clean**

Run: `cd /root/idealists-site && npm run check`
Expected: no NEW errors or warnings versus the pre-existing baseline (~8 errors / ~32 warnings). If `npm run check` flags `bind:value={s1OpenQuestions[q.key]}`, that is a real issue to fix, not baseline noise — `q.key` is a literal union from the `as const` array and `s1OpenQuestions` has exactly those keys, so the index access is well-typed; investigate rather than suppress.

- [ ] **Step 6: Build to confirm the route compiles**

Run: `cd /root/idealists-site && npm run build`
Expected: build succeeds. (Manual visual QA — expand/collapse nesting, submit, skip — is for the user's review pass; it cannot be automated here.)

- [ ] **Step 7: Commit**

```bash
cd /root/idealists-site && git add src/routes/interview/+page.svelte
git -c user.name="Claude" -c user.email="noreply@anthropic.com" commit -m "$(cat <<'EOF'
interview: optional open-questions braindump section on the stage-1 form

A collapsed-by-default <details> section whose four governance questions
are each individually collapsible — feels optional, not overwhelming.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification (after all tasks)

- [ ] Backend: `cd /root/interviewer/server && uv run pytest tests/ -v` — all tests pass.
- [ ] Frontend: `cd /root/idealists-site && npm run check` — no regression past the known baseline; `npm run build` succeeds.
- [ ] `cd /root/interviewer && git log --oneline two-stage-interview` and `cd /root/idealists-site && git log --oneline mobile-enter-newline` — confirm the new commits are present on each branch.
