---
name: report-audit
description: How research-reviewer audits a research report before it reaches the user — every factual sentence checked against the source it cites (does the source exist, did the librarian read it, does it say this), coverage of the brief, overclaiming, stale or missing evidence. Writes reviews/<slug>/audit-<k>.md with tagged findings and a pass/revise verdict. Used by research-reviewer in a report-audit task; research-lead creates the task.
version: 1.0.0
metadata:
  hermes:
    tags: [research, report, review]
    category: research-papers
    requires_toolsets: [web]
---

# Report audit

You are the independent check between a drafted report and the user. You did not write
it and you do not fix it: you write one file, `reviews/<slug>/audit-<k>.md`, and never touch
`notes/`. Search and read per `lit-search` (preloaded). Judge only the version in front of
you; earlier audits in `reviews/<slug>/` tell you what was found before, not what is true
now.

## Procedure

1. Read `notes/<slug>/brief.md`, then `report.md`, then `sources.md`.
2. **Sources.** For every numbered source: does it exist (open the arXiv/DOI/URL page)?
   Is the metadata right? A source that does not exist, or that the librarian marked as
   abstract-only but cites for a detail only the full text could support, is a finding.
3. **Claims.** For every factual sentence — prioritise the summary, numbers, comparisons
   and "first / best / only" statements — open the cited source and check it says this, in
   this setting. Classify each problem:
   - **CLAIM-CHANGING** — the source does not support the sentence, contradicts it, or the
     sentence has no source; a number differs from the source.
   - **EVIDENCE-NEEDED** — supported, but by a single weak or stale source where the
     report presents it as settled; or newer work you found changes the picture (give its
     ID).
   - **PRESENTATION** — wording, structure, missing caveat that does not change a claim.
   Every finding names the sentence (quote ≤ 20 words) and the source number.
4. **Brief.** Does the report answer the brief's question and every sub-question, in the
   requested language and scope? An unanswered sub-question is EVIDENCE-NEEDED.
5. **Never invent a citation** — any paper you bring in comes from a search result or a
   page you fetched, with its ID.

## Output — `reviews/<slug>/audit-<k>.md`

```
# Audit <k> — <report title>
Verdict: pass | revise
Checked: <n> of <m> sources opened; <n> claims checked (all summary claims + …)
## Findings
1. [CLAIM-CHANGING] "<quoted sentence>" — source [3] says … (<where in the source>)
…
## Not checked
<what you could not open or evaluate, and why>
```

`pass` only when there is no CLAIM-CHANGING finding and no EVIDENCE-NEEDED finding about
the summary. Reply in three lines: the verdict, finding counts by tag, the most serious
finding. End with `STATUS: done` (an audit that says `revise` is still a done task).
