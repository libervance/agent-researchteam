---
name: research-report
description: Produces an evidence-backed research report on a topic — the lead writes a brief, research-librarian researches and drafts it from sources it actually read, research-reviewer audits every claim against those sources, the librarian revises on findings, and the lead delivers the audited report to the user's thread as a Word file. Use when the user asks for a report, survey, briefing, overview or "what is known about X" as a document (e.g. "@research-lead ○○에 대한 보고서 작성해줘"). Not for writing a paper (research-start) or a one-line literature question (one research-librarian task).
version: 1.0.0
metadata:
  hermes:
    tags: [research, report, literature]
    category: research-papers
---

# Research report

A report is a document the user can forward: every factual sentence traces to a source the
librarian read, and an independent audit has checked it before the user sees it. You
coordinate; you never write or fix the report yourself, and you never audit it.

```bash
PB=("__PYTHON__" "__RESEARCH_BOARD__")   # bash array (paths may contain spaces)
R=reports                                 # the shared reports folder in your workspace
```

Task bodies go in `.scratch/<id>.md` (relative to your workspace) and are passed with
`--body-file`. `new` is idempotent on `--id`, so a resumed run never double-dispatches.
Over Mattermost, never wait inside a turn: dispatch, reply in two lines, end the turn. The
runners post progress in the thread. The private lead coordinator reads each completed audit
and resumes the lead's work on the board before creating a revision or delivering the report.

## Step 0 — Where to work

- The default folder is `reports/` in your workspace (installed with its own board; public).
  If it is missing, run `"${PB[@]}" project-create reports`, set its `CLAUDE.md` title to
  "Reports" and `**Sensitivity:** public`, then publish `CLAUDE.md`.
- If the user says the topic or their material is confidential, run
  `"${PB[@]}" project-create report-<slug>`, set and publish its `CLAUDE.md` sensitivity as
  `private` (or `air-gapped`) before creating a task — never put it in `reports/`. Without
  local models the runners will refuse it and say so; tell the user that instead of
  working around it.
- `<slug>`: short kebab-case of the topic, plus `-2`, `-3` if it exists
  (`ls $R/notes/`). Everything for this report lives under `notes/<slug>/` and
  `reviews/<slug>/`.

## Step 1 — Brief (you)

Ask at most one question, and only if the request cannot be scoped without it (audience,
time window, or a must-include source). Otherwise proceed. Write `$R/notes/<slug>/brief.md`:

- the user's request verbatim, and the language to write the report in (the user's);
- the question the report answers, in one sentence, and 3–6 sub-questions;
- scope: time window, what is out of scope, expected length (default 2–4 pages);
- any sources the user named.

`"${PB[@]}" publish $R -m "brief: <slug>" notes/<slug>/brief.md`, then open the thread:
`TH=$("${PB[@]}" thread $R "Report — <topic>")` (if `setup` was never run for this folder,
run it first with the channel the user is in).

## Step 2 — Research and draft (research-librarian)

`--id rep-<slug>-draft --assignee research-librarian --skills lit-review
--expects notes/<slug>/report.md,notes/<slug>/sources.md --thread $TH`, body:

> Discovery mode, written report. Read `notes/<slug>/brief.md` and answer it as a report in
> `notes/<slug>/report.md`, in the language the brief names: a title (`# …`), a short
> summary of the answer, one section per sub-question, and what remains open. Every factual
> sentence carries a bracketed source number. Write `notes/<slug>/sources.md`: one line per
> number — authors, title, year, venue, arXiv ID / DOI / URL, and which part you read
> (full text, abstract only). Cite only what you opened; a search hit you did not read is
> not a source. Say plainly where the evidence is thin or disputed.

## Step 3 — Audit (research-reviewer)

`--id rep-<slug>-audit-1 --assignee research-reviewer --skills report-audit --after
rep-<slug>-draft --expects reviews/<slug>/audit-1.md --thread $TH --notify-done
"Audit complete. The lead is checking the verdict and will continue this report."`, body (fixed — add
nothing about who asked or why):

> Report audit. Audit `notes/<slug>/report.md` against `notes/<slug>/sources.md` and the
> brief `notes/<slug>/brief.md`. Write `reviews/<slug>/audit-1.md`.

Reply to the user: researching and drafting, then an independent audit; the thread will
show progress and the lead will continue after the audit without another user message.

## Step 4 — Read the verdict

When `rep-<slug>-audit-<k>` is done, read `reviews/<slug>/audit-<k>.md` (pull first).

- **`Verdict: pass`** → Step 5.
- **`Verdict: revise`** and k < 3 → a revision, then a fresh audit of the new version:
  `--id rep-<slug>-rev-<k> --assignee research-librarian --skills lit-review --after
  rep-<slug>-audit-<k> --expects notes/<slug>/response-<k>.md --thread $TH`, body:
  > Revise `notes/<slug>/report.md` to resolve every CLAIM-CHANGING and EVIDENCE-NEEDED
  > finding in `reviews/<slug>/audit-<k>.md` (PRESENTATION ones where cheap). Fix by
  > finding and reading a better source, or by narrowing or removing the claim — never by
  > softening wording alone. Update `sources.md`. Write `notes/<slug>/response-<k>.md`:
  > one line per finding — what changed, or why it stands.

  then `rep-<slug>-audit-<k+1>` exactly as in Step 3 with the new number, `--after
  rep-<slug>-rev-<k>`. A pass on an earlier version never counts for a revised one.
- **`Verdict: revise` after audit 3** → stop. Tell the user the report did not pass, with
  the open findings, and ask whether to deliver it marked as unaudited, narrow the scope,
  or drop it. Their call.
- **blocked / failed** → say so plainly with the reason from `"${PB[@]}" show`; retry only
  once the cause is fixed (`"${PB[@]}" edit $R <id> --status ready`).

## Step 5 — Deliver (you)

`"${PB[@]}" deliver $R notes/<slug>/report.md:docx --thread $TH --label "<title> — audited
report"` attaches the Word file to the thread, downloads it again and checks SHA-256; also
attach `notes/<slug>/sources.md`. Then reply in a few lines: the one-sentence answer, the
audit outcome (passed on audit k; findings fixed), and that the Word file is in the thread.
The report is audited by the team — it is not the user's sign-off and not a publication.
