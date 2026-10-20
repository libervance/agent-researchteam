---
name: research-round
description: Runs one review round on a CS/AI paper — a research-writer task drafts or revises, three research-reviewer referee tasks (novelty, methods, clarity) plus a research-librarian bibliography audit run in parallel on their own devices, then a research-reviewer chair task writes the ranked revision plan; all through the paper's git task board. Use whenever the user asks to review, referee, critique, pressure-test or get a meta-review of a paper draft; to run the next round / another round; to execute or apply the revision plan from the last meta.md; to re-run one reviewer or only the bibliography audit; or to check whether a paper is ready to submit. Not for a standalone literature search (one research-librarian task) or a one-off LaTeX fix (one research-writer task).
version: 1.0.0
metadata:
  hermes:
    tags: [research, review, orchestration]
    category: research-papers
    requires_toolsets: [terminal]
---

# Paper review round

One invocation = one round, ending at a checkpoint. The user reads the chair's `meta.md`
before any revision happens, because deciding which findings to fight is the author's call,
not the orchestrator's.

**Execution mode:** tasks on the paper's git board, one per role, each picked up by the
runner on that agent's device. Workers never talk to each other. Everything passes
through files in the paper repo — the reviews are the record the next round's chair reads.

```bash
PB=("__PYTHON__" "__RESEARCH_BOARD__")   # bash array (paths may contain spaces); P = the paper folder (your clone), N = the round
```

Write each task body to a file in your workspace's scratch folder (`.scratch/<id>.md`, a relative path) and pass `--body-file`, so quoting
never mangles it.

## Step 0 — Locate the paper and the round

1. **Paper folder.** A clone in the workspace with a git remote. If the user did not name
   one and more than one exists, ask. `"${PB[@]}" list $P` pulls it and shows the board.
2. **Readiness.** No paper folder, a `$P/CLAUDE.md` still containing `<paper working title>`
   or `NeurIPS 20XX`, or no drafted sections under `$P/paper/sections/` means there is
   nothing to review yet — switch to the `research-start` skill, which scopes and drafts the
   paper and hands back here. An early read on a partial draft (`\pending{…}` placeholders)
   is fine: run only the novelty and clarity referees and skip the writer and the chair.
3. **Round N.** `ls $P/reviews/` — N is one more than the highest complete `round-K/`
   (complete = has `meta.md`). A board that already has `r<K>-*` tasks without a done
   `r<K>-chair` is a round in flight or partial: resume it (look at `"${PB[@]}" list`, act per Error
   handling) — do not start a new one.
4. **Pick the entry point** from what the user asked:

   | Request | Tasks to create |
   |---|---|
   | First review of a draft / "review my paper" | writer (pre-review check) → 4 reviews → chair |
   | "Apply / execute the revision plan" | writer (execute `round-<N-1>/meta.md`) → 4 reviews → chair |
   | "Run the next round" after revisions are done | 4 reviews → chair |
   | "Re-run the methods review" / "just the bib audit" | that one task with a `-rerun<k>` id, then a new chair |

5. **Stop rule, checked before starting a new round.** If `round-<N-1>/meta.md` has no
   `CLAIM-CHANGING` item, the loop is done — tell the user and offer the writer's
   pre-submission pass instead (one `research-writer` task, `--skills presubmission`). If N
   would be 4, stop: a finding that survived three rounds means the claim is wrong, not the
   wording. Report which findings persisted and let the user decide whether to cut the claim.

## Step 1 — Create the whole round at once

First open the round's thread, so every runner reports into one place:

```bash
TH=$("${PB[@]}" thread $P "Round <N> — <P>: writer → 3 referees + bib audit → chair")
```

Pass `--thread $TH` to every task below. (If the paper has no `.tasks/board.conf` yet, ask
the user for the paper's Mattermost channel and run `"${PB[@]}" setup $P --channel <team>/<channel>
--mention @<user>` once. Without it the round still runs, just silently.)

The `after:` gates make the order: reviews start only when the writer is `done`, the chair
only when all four reviews are `done`. A writer that cannot build ends `blocked`, and
nothing downstream starts — reviewing a stale PDF would waste four agents.

**Writer** — `--id r<N>-writer --assignee research-writer --expects paper/main.pdf --deliver
paper/main.pdf` (the runner attaches the built PDF to the round thread, verified):

> Read `CLAUDE.md` first. <Task: "Execute `reviews/round-<N-1>/meta.md` in its ranked order" |
> "Bring the draft to review-ready">. Build the PDF clean at `paper/main.pdf` (run the
> `manuscript-check` procedure) and confirm the abstract and introduction assert only
> `supported` ledger rows. If the build fails, end with `STATUS: blocked` and the error.

**Three referees** — `--assignee research-reviewer --skills lit-search --after r<N>-writer`,
ids `r<N>-novelty` / `r<N>-methods` / `r<N>-clarity`, `--expects
reviews/round-<N>/<persona>.md`:

> Read `CLAUDE.md` for the venue only. Review `paper/main.pdf` as referee, persona
> **<novelty|methods|clarity>**, round **<N>**. Follow `REVIEW_RUBRIC.md` exactly and write
> `reviews/round-<N>/<persona>.md`. Verify every headline number against `evidence/`.

**Bibliography audit** — `--id r<N>-bibliography --assignee research-librarian --skills
lit-search,bib-audit --after r<N>-writer --expects reviews/round-<N>/bibliography.md`:

> Bibliography audit mode (load the `bib-audit` skill), round **<N>**. Audit `paper/` and
> `paper/refs.bib`; write `reviews/round-<N>/bibliography.md`.

**Chair** — `--id r<N>-chair --assignee research-reviewer --skills review-chair --gate human --after
r<N>-novelty,r<N>-methods,r<N>-clarity,r<N>-bibliography --expects reviews/round-<N>/meta.md
--deliver reviews/round-<N>/meta.md:docx` (the checkpoint arrives in the thread as a Word file):

> Chair mode (load the `review-chair` skill), round **<N>**. Read
> `reviews/round-<N>/*.md`, `paper/main.pdf`, and — for carried-over findings —
> `reviews/round-<N-1>/meta.md` and the "Declined findings" table of `claims.md`. Write
> `reviews/round-<N>/meta.md`.

When the round has no writer task ("run the next round"), drop `--after r<N>-writer` from
the reviews. For an early read, create only the novelty and clarity tasks, with no `--after`.

**Never add** what the authors were going for, what changed since last round, which
findings the writer addressed, or the user's opinion of the draft. That omission is what
makes the review worth reading — a reviewer who knows the intent reviews the intent. (The
`CLAUDE.md` venue section is the one sanctioned exception; the reviewer is told to read it
for the venue only.) The runner hides `.tasks/` and git history from reviewers, so the
writer's report cannot leak — as long as the bodies above stay exactly as written.

The reviewers and the chair each run as a fresh process in a profile with no memory, so the
chair has not seen the drafting.

## Step 2 — Hand back, or wait

**Over Mattermost (the usual case): do not wait.** Reply in a few lines: round N dispatched,
the six task ids, the thread link, "the runners will post progress there and ping you at
the checkpoint". End your turn. When the user comes back ("status?", "what did the chair
say?"), `"${PB[@]}" list $P` and answer from the board; once `r<N>-chair` is `done`, go to Step 3.

**In a terminal session:** you may wait — `"${PB[@]}" wait $P r<N>-writer`, then `"${PB[@]}" wait $P
r<N>-chair`; each call polls for up to 150 s and returns, so call it again while tasks are
still running, telling the user briefly where the round stands between calls.

If a `ready` task shows no progress for a long time, its device's runner is not running —
tell the user which role's runner to start.

## Step 3 — Checkpoint (stop here)

When `r<N>-chair` is `done` (the runner has already posted the call and tag counts to the
thread and pinged the user), `git -C $P pull` and, when the user asks, report briefly: the chair's
call, the count of items by tag (CLAIM-CHANGING / EVIDENCE-NEEDED / PRESENTATION), the top
item, any missing review, and the path to `reviews/round-<N>/meta.md`. Then stop. The next
invocation ("apply the plan") starts the next round with a writer task.

Do not summarize the reviews at length or editorialize on them — the user reads `meta.md`.

If the plan has EVIDENCE-NEEDED items (or CLAIM-CHANGING ones an experiment could settle),
say so in one line and offer the `research-experiment` skill for them before the next writer
pass — a revision that needs new evidence cannot be written until the evidence exists.

## Error handling

- **Writer `blocked`:** `"${PB[@]}" show $P r<N>-writer` and report the reason (build error, needs
  research, needs the user). Once it is resolved, `"${PB[@]}" edit $P r<N>-writer --status ready`.
- **A review `failed` or `blocked`:** read the reason. A usage limit, auth or rate-limit
  failure will not change on an immediate retry — report it and when it may reset. Otherwise
  retry once: `"${PB[@]}" edit $P <id> --status ready`. If it fails again, proceed without it:
  `"${PB[@]}" edit $P r<N>-chair --after <the reviews that are done> --append "The <persona> review
  is missing; do not infer its content."`, and name the missing persona in the Step 3 report.
- **The user pinged on a block replies in the thread** ("S2 is back, retry"): that reply
  reaches you, not the worker. Act on it with `"${PB[@]}" edit … --status ready`.
- **A task stuck `running` for hours:** its device probably died. Ask the user; a restarted
  runner releases its own stale claims automatically, or `"${PB[@]}" edit $P <id> --status ready`.
- **Never edit `paper/` yourself during a round.** A coordinator who fixes the manuscript
  collapses critique and fix — route every change through a `research-writer` task.
- **Never fill a gap yourself.** If a review is missing, do not write one from your own
  reading; that would put a coordinator's view — which has seen the drafting — into a record
  meant to be blind.

## Test scenarios

- **Normal:** `demo/` has a draft and no `reviews/`. "Review my paper in demo" → N=1 → six
  tasks created in one go → writer done → four reviews run on their devices (referees in
  parallel if the reviewer device runs several slots) → chair done → checkpoint report.
- **Partial resume:** the board shows `r2-methods` `failed` (usage limit) and `r2-chair`
  waiting on it. Re-invoking later retries only `r2-methods`; the chair runs when it is done.
- **Stop rule:** `round-3/meta.md` exists with a CLAIM-CHANGING item and the user says "next
  round". Step 0 refuses N=4 and reports the persisting findings instead.
- **Build failure:** the writer ends `blocked` with a LaTeX error. No review starts; the lead
  reports the error.
- **Blindness check:** `"${PB[@]}" show $P r<N>-methods` shows a body identical to the skeleton.
