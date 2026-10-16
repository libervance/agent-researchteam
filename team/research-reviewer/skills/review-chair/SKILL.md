---
name: review-chair
description: How research-reviewer acts as area chair over a finished review round — reconcile the referee and bibliography reports into consensus, resolved conflicts, a ranked revision plan tagged CLAIM-CHANGING / EVIDENCE-NEEDED / PRESENTATION, carried-over findings, and a call. Writes reviews/round-<N>/meta.md. Used by research-reviewer, chair mode; research-lead creates a board task for that agent rather than running this itself.
version: 1.0.0
metadata:
  hermes:
    tags: [review]
    category: research-papers
---

# Chair mode

Read `reviews/round-<N>/*.md` and the paper — nothing else, and no author
correspondence. For carried-over items, also `reviews/round-<N-1>/meta.md` and the
"Declined findings" table of `claims.md`.

**You are not a fourth reviewer: do not add new criticism.** Your job is triage. If a review
is missing from the round, say so and do not infer its content.

Write `reviews/round-<N>/meta.md`:

- **Consensus** — where the reviewers agree. These are real; the author does not get to
  argue them away.
- **Conflicts** — where they disagree, and which reading the paper actually supports. Say
  which reviewer is wrong and why. Do not average them, and do not report a conflict you
  could have resolved by looking at the paper.
- **Ranked revision plan** — each item tagged CLAIM-CHANGING / EVIDENCE-NEEDED /
  PRESENTATION, with the location to change and what specifically would settle it. Ordered
  by what would move the decision, not by reviewer order or severity of tone.
- **Carried over** — findings still open from round N-1, and any the author declined with a
  reason recorded in `claims.md`. State whether the reason holds. A finding that reappears
  in three rounds means the claim is wrong, not the wording.
- **Call** — accept / reject / borderline, and the single thing that would flip it.
