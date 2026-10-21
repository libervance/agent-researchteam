---
name: research-start
description: Takes a CS/AI paper from nothing to a review-ready first draft in this workspace — scaffold the paper folder, pin down venue and the one-sentence contribution against the closest prior art, plan the claims and the experiments that would establish them, outline, then draft section by section through research-lead tasks on the paper's git board. Works whether the user already has results or only an idea. Use when the user wants to start / write / set up a new paper, write up results, turn an idea into a paper, plan experiments for a paper, outline a paper, draft or continue drafting sections, or resume an unfinished first draft. Not for reviewing an existing draft or running a revision round (use research-round), and not for a standalone literature question (one research-librarian task).
version: 1.0.0
metadata:
  hermes:
    tags: [research, writing, orchestration]
    category: research-papers
    requires_toolsets: [terminal]
---

# Paper from scratch

Five stages, each ending in a file on disk, so any session can resume from what exists:

| Stage | Output | Who |
|---|---|---|
| 1 Scope | `<paper>/CLAUDE.md` filled, `<paper>/notes/prior-art.md` | you with the user; a `research-librarian` task |
| 2 Claims and evidence plan | `<paper>/claims.md` rows + experiment plan | you with the user |
| 3 Outline | `<paper>/outline.md` | a `research-lead` task |
| 4 Draft | `<paper>/paper/sections/*.tex`, clean build | a chain of `research-lead` board tasks |
| 5 Handoff | review-ready draft | → `research-round` |

**Execution mode:** mixed. Stages 1–2 are a conversation between you (research-lead) and the
user — the contribution and the claims are the author's decisions, not a worker's. Stage 1's
literature search and Stage 3 are single board tasks. Stage 4 is a chain of `research-lead`
tasks, one per section, each `--after` the previous; the writer reads the earlier sections
and the previous task's report for voice and notation.

Board commands (`"${PB[@]}" new / list / wait / show / edit / publish`) and conventions — body in a
temp file, idempotent `--id`, waiting with `"${PB[@]}" wait` — are the same as in `research-round`:

```bash
PB=("__PYTHON__" "__RESEARCH_BOARD__")   # a bash array: paths may contain spaces
```

Open one Mattermost thread per stage that creates tasks (`TH=$("${PB[@]}" thread <paper> "Stage 1 — prior art")`,
likewise Stage 3 and Stage 4) and pass `--thread $TH` to its tasks. Over Mattermost, never wait
inside a turn: dispatch, reply briefly, end the turn — the runners report into the thread.

In coordinator/chat mode, schedule your authorship as `research-lead` board tasks. Everything
else in the paper folder (`CLAUDE.md`, `claims.md`, `notes/`) you may write during Stages
1–2; push it with `"${PB[@]}" publish <paper> -m "<msg>" <paths>` so the other devices see it.

## Step 0 — Where are we?

1. **Paper folder.** If the user named none and none fits, propose a short kebab-case name
   and run `"${PB[@]}" project-create <name>`. This creates the folder, board, local Git
   remote and Mattermost binding and registers the remote for this PC's runners. For work
   across devices, use `project-create <name> --remote <existing-shared-git-url>` and tell
   the user to register that URL on the other devices. If several
   papers exist, ask which.
2. **Resume point** — the first stage whose output is missing:
   - `<paper>/CLAUDE.md` still has `<paper working title>` or `NeurIPS 20XX` → Stage 1
   - `claims.md` rows are still the template's placeholder C1/C2 → Stage 2
   - no `outline.md` → Stage 3
   - `outline.md` lists sections with no `.tex` under `paper/sections/` → Stage 4, next one
   - all sections exist → Stage 5

   Also `"${PB[@]}" list <paper>`: a stage task still in flight is waited on, not re-created.
3. **Starting point.** Ask once, early: *do you have results, or an idea you still need to
   test?* It changes Stage 2, not the order. "Some results" is common — treat each claim by
   whether its evidence exists.

## Stage 1 — Scope

1. Interview briefly — one message, not a questionnaire: the idea in the user's words, the
   target venue and deadline, what exists (code, runs, data, a rough draft), and what they
   believe is new. Ask too where the unpublished work may go, and set `**Sensitivity:**` in
   `<paper>/CLAUDE.md` to `public` or `air-gapped`, or leave the template's default, before
   the first task is created — it decides where every later model call goes.
2. Create a `research-librarian` task on the **closest prior art to the candidate
   contribution**, not the whole field — `--id s1-prior-art --skills lit-search,lit-review --gate human
   --expects notes/prior-art.md,notes/prior-art.bib`:

   > Discovery mode (load the `lit-review` skill). Find the 5–10 papers closest to this
   > idea: <idea, mechanism-level>. For each, what it does and how it differs. Save the
   > report to `notes/prior-art.md` and verified BibTeX for every paper you name to
   > `notes/prior-art.bib`.

   While it runs, fill in what you can of `<paper>/CLAUDE.md` with the user.
3. With the user, write the **one-sentence contribution** in `<paper>/CLAUDE.md`, stated as
   the delta over the nearest paper in `prior-art.md`. If the search shows the idea is
   already done, say so plainly and help the user find the real delta or pivot — before any
   writing. A paper drafted on an already-published contribution wastes every later stage.
4. Fill the rest of `<paper>/CLAUDE.md` (target, notation, claims we do not make) with the
   user. Adjust `<paper>/REVIEW_RUBRIC.md` if the venue is not NeurIPS-style.

**Gate:** the user agrees with the contribution sentence.

## Stage 2 — Claims and evidence plan

List every claim the paper will make — headline claim first, then each supporting one
(including the adjectives: "faster", "robust", "scales"). Each becomes a row in
`<paper>/claims.md`, and each row has an entry in the **Experiment plan** table there:

- **Results in hand:** map each claim to its existing run. Move runs into
  `<paper>/evidence/<date>-<run-name>/` per the conventions in `<paper>/CLAUDE.md` if they
  are not there, and push them — reviewers on other devices verify numbers against them. Status `supported` only when the artifact actually establishes the claim;
  a run that shows a weaker version is `partial` — narrow the claim or plan the missing run.
- **Idea only:** each claim is `unsupported` with a planned experiment: setup, baselines,
  metric, seeds, and — written *before* running it — **the result that would refute the
  claim**. Fixing that in advance is what keeps the paper from being fitted to whatever
  comes out.

Push back on claims no feasible experiment could establish, and on a plan with no baseline
a referee would accept. Cutting a claim now costs a sentence; cutting it after a review round
costs a section.

For claims whose evidence does not exist yet, the plan here is the *what*; each becomes an
experiment through the `research-experiment` skill (design → protocol check → user approval →
run → collect), which turns a plan row into an executable, frozen protocol. Offer to start
the first one — the headline claim — as soon as the ledger is confirmed; drafting (Stages
3–4) proceeds in parallel with `\pending{C<n>}` placeholders.

**Gate:** the user confirms the ledger and plan. Publish `CLAUDE.md`, `claims.md`,
`REVIEW_RUBRIC.md` and `evidence/`. From here on update `claims.md` through your authorship board tasks.

## Stage 3 — Outline

Create a `research-lead` task, `--id s3-outline --expects outline.md --gate human`:

> Read `CLAUDE.md`, `claims.md` and `notes/prior-art.md`. Write `outline.md`: the section list with a page
> budget per section within the venue limit; per section, its paragraphs as one-line claims
> with the ledger ID each one carries; every planned table/figure with the evidence artifact
> it will come from (or `pending C<n>`). Do not write LaTeX yet.

Show the user the outline (after `git -C <paper> pull`). **Gate:** the user approves it.
For revisions, append the user's feedback to `s3-outline` and reset that same task with
`edit <paper> s3-outline --append <feedback> --status ready`. Its next result needs fresh approval.

## Stage 4 — Draft

Create the writer task chain below. If the user wants to co-write, collect their feedback
through your chat and put it in your authorship board tasks. Your lead gateway accepts user
instructions; the lead task runner writes the manuscript in the background.

**Order:** method → experiments → related work → introduction → conclusion → abstract. The
method is what the paper is; the introduction and abstract can only promise what the
sections before them deliver, so they are written last.

Create one `research-lead` task per section, `--id s4-<section>`, each `--after` the previous
section's task. You may create the whole chain at once:

> Draft section **<section>** from `outline.md`. Read the sections already in
> `paper/sections/` first and match their voice and notation, and the report in
> `.tasks/s4-<previous section>.md`. Copy verified entries from `notes/prior-art.bib` into
> `paper/refs.bib`; cite nothing that is not there. Build and report; list the claims left
> `\pending` and any outline problem you found.

For a claim still `unsupported`, the writer drafts the setup and leaves the result as
`\pending{C<n>}` (defined in the template's `main.tex`). Never let a plausible-looking number
stand in for a run that has not happened.

After each section lands: tell the user in two lines what was drafted and which claims are
pending. For feedback before approval, append it to the same section task and reset it with
`edit <paper> s4-<section> --append <feedback> --status ready`; keep later sections dependent
on that task. The revised result requires a fresh approval. When an experiment's
result lands (`research-experiment` Step 6), its write-up task updates the ledger and fills
`\pending{C<n>}`. For runs the user did outside the team, create a writer task: "C<n> now
has `evidence/<run>`; update the ledger and fill `\pending{C<n>}`".

## Stage 5 — Handoff to review

Ready for `research-round` when: the build is clean; no `\pending` remains in the abstract or
introduction; and every headline claim is `supported`. Then hand off: "run a review round on
`<paper>`" (invoke the `research-round` skill).

If experiments are still running, offer an **early read** instead — `research-round` with only
the novelty and clarity referees. The methods referee and a chair add nothing while the
results are placeholders.

## Error handling

- **`research-librarian` finds nothing close:** do not take that as proof of novelty. Create one
  more task asking for a pass with the field's older vocabulary and a citation walk; if still
  nothing, make sure `prior-art.md` records what was searched, so a referee's "missed prior
  work" can be checked against it.
- **A writer task blocks** (e.g. it needs a research-librarian pass, or the outline is wrong):
  `"${PB[@]}" show` for the reason, resolve it with the user or a `research-librarian` task, then
  `"${PB[@]}" edit <paper> <id> --append "<the answer>" --status ready`.
- **Chain interrupted** (a task failed and the rest wait on it): retry it, or create a task
  for the next section with no `.tex`; it resumes by reading the existing sections.
- **User wants to skip a stage** ("just write the intro"): allowed, but name what is being
  skipped — an intro drafted before Stage 2 will promise claims nobody has checked.

## Test scenarios

- **Idea only:** "I want to write a paper on X." → scaffold `x/`, Stage 1 interview,
  prior-art task, contribution agreed, ledger with every claim `unsupported` plus refutation
  criteria, outline task, method drafted, experiments section drafted with `\pending{C1..}`.
  Stage 5 offers an early read, not a full round.
- **Results in hand:** "I have results in ~/runs/foo, help me write it up for ICLR." →
  runs moved to `evidence/`, claims mapped, one claim marked `partial` and narrowed, full
  draft chain, handed to `research-round`.
- **Resume:** new session, `demo/outline.md` exists and `method.tex` and `experiments.tex`
  exist → Step 0 resumes at Stage 4 with related work.
- **Prior art already does it:** Stage 1 search surfaces a paper with the same mechanism →
  stop, report it, help find the delta; no outline task is created.
