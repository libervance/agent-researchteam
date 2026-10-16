# Review rubric — NeurIPS-style

Every referee emits **exactly these sections, in this order**, so reviews diff against
each other and across rounds. Venue-specific: to retarget (ICLR, ACL ARR, CVPR), rewrite
this file only — the agents read it and do not hardcode a venue.

Write to `reviews/round-<N>/<persona>.md`.

---

## Summary

Two to four sentences: what the paper does and what it claims, in the authors' terms.
A summary the authors would agree with. No criticism here.

## Claims vs. evidence

One row per claim in the abstract and introduction.

| Claim | Asserted in | Evidence offered | Artifact traced | Verdict |
|---|---|---|---|---|
| | §/line | table/figure/theorem | path under `evidence/`, or NONE | supported / partial / unsupported / untraceable |

`untraceable` means you could not find the artifact, which is a finding in its own right.

## Strengths

Ranked, specific, with locations. What would be lost if this paper were rejected.
At least one entry unless the paper is unsalvageable.

## Weaknesses

Ranked, most decision-relevant first. Each entry: **tag** — location — the problem — what
would resolve it.

Tags: `CLAIM-CHANGING` (the conclusion does not follow) · `EVIDENCE-NEEDED` (plausible but
unestablished) · `PRESENTATION` (the work stands; the paper obscures it).

## Questions for the authors

Answerable questions whose answers would change your score. Not rhetorical, not a restated
weakness. Say for each what answer would move you.

## Scores

- **Soundness** (1–4): are the claims supported by the evidence? 1 poor · 2 fair · 3 good · 4 excellent
- **Presentation** (1–4): clarity, structure, reproducibility of the description
- **Contribution** (1–4): significance of what is new, given the prior art
- **Confidence** (1–5): 1 educated guess · 3 fairly confident · 5 absolutely certain

One sentence justifying each. A score with no matching entry above it is unjustified.

## Limitations and ethics

Do the authors state the real limitations, or only cosmetic ones? Any societal-impact,
dual-use, human-subjects, licensing or data-provenance concern the venue requires, plus
anything the authors omitted that a reader would want flagged.

## Could not evaluate

What you did not check and why — no code, missing appendix, proof not verified line by
line, subfield outside your competence. Be explicit; the chair weights your review by this.

## Recommendation

`strong accept` / `accept` / `weak accept` / `borderline` / `weak reject` / `reject` /
`strong reject`, followed by the one change that would most improve your recommendation.
