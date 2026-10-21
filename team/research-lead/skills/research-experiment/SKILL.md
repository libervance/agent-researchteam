---
name: research-experiment
description: Takes one experiment from "this claim needs evidence" to evidence in the paper — pick the claim and budget with the user, a research-experimenter design task writes a pre-registered protocol, a research-reviewer checks it before compute is spent, the user approves (always), the experimenter launches capped jobs and collects every run against the pre-written criteria, and research-lead updates the ledger. Use when the user asks to run, plan, design or propose an experiment, to test a claim, to act on an EVIDENCE-NEEDED item from a review round, to fill a \pending result, to check on or approve a running experiment, or asks what to test next.
version: 1.0.0
metadata:
  hermes:
    tags: [research, experiments, orchestration]
    category: research-papers
    requires_toolsets: [terminal]
---

# One experiment, from claim to evidence

```
pick claim + budget (you + user) → x<k>-design → x<k>-check → USER APPROVES → x<k>-launch
      → jobs run on the compute box → x<k>-collect → x<k>-writeup → (next research-round)
```

The protocol is fixed before any result exists and the user approves it before any compute
is spent. **Always ask the user; never approve on their behalf**, whatever the budget.

```bash
PB=("__PYTHON__" "__RESEARCH_BOARD__")   # bash array (paths may contain spaces); P = the paper folder, K = the experiment number
```

Over Mattermost, as always: dispatch, reply briefly, end the turn. The runners post
progress in the experiment's thread and ping the user when their input is needed.

## Step 0 — Locate

1. **Paper** `$P`, pulled (`"${PB[@]}" list $P`). The board must be bound to a channel (`setup`).
2. **Code repo.** `$P/CLAUDE.md` must name the experiment code repo (Evidence conventions →
   **Code repo**). Missing → ask the user for the URL, add it, publish.
3. **Experiment id.** `K` = one more than the highest `experiments/x<K>/`. An experiment
   already in flight (tasks `x<K>-*` not done): resume it at its step, do not start another
   for the same claim.
4. **Entry point:**

   | Request | Start at |
   |---|---|
   | "what should we test next?" / "run an experiment for C3" / EVIDENCE-NEEDED item | Step 1 |
   | "approve x2" / "change the protocol: …" | Step 3 |
   | "how is x2 going?" | `"${PB[@]}" list $P` + the thread; answer in a few lines |
   | an amendment is waiting (a launch/collect task blocked on one) | Step 5 |

## Step 1 — Pick the claim and the budget (with the user)

Candidates, from the files, not from memory:
- `claims.md` rows `unsupported` / `partial` and their **Experiment plan** rows;
- the latest `reviews/round-<N>/meta.md` items tagged EVIDENCE-NEEDED (and CLAIM-CHANGING
  ones an experiment could settle);
- `\pending{C<n>}` left in the draft.

Propose at most three, ranked by what would most move the paper (a headline claim over a
side claim; a chair's top item over a referee's aside), each with one line on why and a
rough cost class (minutes / hours / days of GPU). The user picks one and gives a
**budget cap in GPU-hours**. That choice is theirs — do not start design without it.

## Step 2 — Design, then protocol check

```bash
TH=$("${PB[@]}" thread $P "Experiment x$K — C<n>: <claim, short>")
```

**Design** — `--id x$K-design --assignee research-experimenter --skills exp-design,lit-search
--expects experiments/x$K/protocol.md --thread $TH`:

> Design task, experiment **x<K>**. Claim under test: **C<n>** (ledger row in `claims.md`,
> and its Experiment plan row). Source: <the chair/referee item, quoted verbatim | "user
> request: …">. Budget cap: **<B> GPU-hours** on this device. Write
> `experiments/x<K>/protocol.md` from the `exp-design` template. Smoke tests only; no
> result-bearing runs.

**Protocol check** — `--id x$K-check --assignee research-reviewer --skills protocol-review,lit-search --gate human
--after x$K-design --expects reviews/protocols/x$K.md --thread $TH --notify-done "Protocol
x<K> is ready for your approval: experiments/x<K>/protocol.md, review in
reviews/protocols/x<K>.md. Tell research-lead whether you approve x<K> or want changes."`:

> Protocol check, experiment **x<K>**. Load the `protocol-review` skill. Review
> `experiments/x<K>/protocol.md`; write `reviews/protocols/x<K>.md`.

Create both at once; the check waits for the design. End your turn.

## Step 3 — The user decides (always)

When the user comes back (the check's done post pinged them), pull and give them, in a few
lines: the claim, the runs (count, seeds), GPU-hours, the three criteria verbatim, and the
reviewer's verdict with its top must-change item. Then:

- **"approve"** — if the reviewer said *redesign* or listed must-change items, say so
  plainly and ask once more. On a clear approval:
  `"${PB[@]}" approve $P x$K --by @<user>`. The protocol is now frozen.
- **changes requested** (by the user, or the user adopting the reviewer's) — a new design
  task `x$K-design-rev<r>` quoting the requested changes verbatim, plus a new check
  `x$K-check-rev<r>` after it; back to this step when it pings.
- **drop it** — say so in the thread; no further tasks.

Never edit the protocol yourself and never approve a protocol that is not on the remote.

## Step 4 — Launch and collect

Right after approval, create both:

**Launch** — `--id x$K-launch --assignee research-experimenter --skills exp-run
--expects experiments/x$K/runs.md --thread $TH`:

> Launch task, experiment **x<K>**. Load the `exp-run` skill (launch mode). Protocol
> `experiments/x<K>/protocol.md` is approved (`approval.md`). Launch every run exactly as
> specified and write `experiments/x<K>/runs.md`.

**Collect** — `--id x$K-collect --assignee research-experimenter --skills exp-run --after
x$K-launch --ready-when "jobs-done x$K" --expects experiments/x$K/result.md --thread $TH
--notify-done "Experiment x<K> finished — verdict in experiments/x<K>/result.md. Tell me to
write it up, or what else to do."`:

> Collect task, experiment **x<K>**. Load the `exp-run` skill (collect mode). Gather every
> run into `evidence/`, compute the analysis per the protocol, and write
> `experiments/x<K>/result.md`.

The collect task waits on the compute box until every job has finished; its runner posts
job progress in the thread meanwhile. End your turn.

## Step 5 — Amendments and retries

A launch or collect task that ends `blocked — amendment <m> …` needs the user. Show them
`experiments/x<K>/amendments.md` entry `<m>` (what, why, effect on analysis and budget).
On approval: `"${PB[@]}" approve $P x$K --amendment <m> --by @<user>`, then
`"${PB[@]}" edit $P <task> --status ready`. On refusal: tell the experimenter in the task
(`--append "Amendment <m> refused: <user's reason>. <what to do instead>"`) and set it ready.

A collect task blocked because it launched queued runs, or relaunched runs per the
protocol's retry policy: set it ready again (`"${PB[@]}" edit $P x$K-collect --status ready`) — it
waits for the new jobs by itself. That is routine; no approval needed.

## Step 6 — Write-up

When the user says so (after reading `result.md`): one `research-lead` task
`--id x$K-writeup --thread $TH --expects claims.md`:

> Experiment **x<K>** finished: `experiments/x<K>/result.md`, evidence in
> `evidence/<date>-x<K>/`. Update the ledger row(s) and the Experiment plan per the
> verdict, fill `\pending{C<n>}` from `analysis.json`, rebuild, report.

Then offer the next step: another experiment, or a review round (`research-round`) if the
evidence was for a review finding.

## Rules

- The user picks the claim and the budget, and approves every protocol and amendment.
- You never write or edit `protocol.md`, `amendments.md`, `result.md` or `evidence/`; you
  only record approvals with `"${PB[@]}" approve`, which is how the freeze starts.
- A NOT MET or inconclusive verdict is reported as plainly as a MET one. Do not propose a
  re-run "with more seeds" as a way around it — a new experiment is a new protocol, and its
  reason is stated to the user.

## Test scenarios

- **From a review:** round-2 `meta.md` has EVIDENCE-NEEDED "no seed variance for Table 3".
  Step 1 proposes it first; user picks it, 20 GPU-hours → design + check → user approves →
  launch starts 5 seeds × 2 configs capped at 2 h → collect waits, posting "jobs 6/10
  finished" → collect writes result: supports MET → write-up on request.
- **Redesign:** the check says *redesign* (baseline tuned with 1/10 of the method's
  budget). User asks for the fix → `x3-design-rev1` + `x3-check-rev1` → approve.
- **Amendment:** the launch hits OOM at the protocol's batch size → blocks with amendment 1
  (halve batch, double steps, same budget) → user approves → launch set ready → runs.
- **Lost jobs:** the compute box reboots; runs without DONE become `lost`; the collect task
  starts (no job is running) and reports them as lost in `result.md`.
