# <paper working title>

Fill this in before the first drafting pass. Every agent reads it.

## Target

- **Venue:** NeurIPS 20XX (main track)
- **Deadline:** YYYY-MM-DD, abstract YYYY-MM-DD
- **Page limit:** 9 pages body, references and appendix unlimited
- **Double-blind:** yes — the pre-submission pass must scrub identity
- **Sensitivity:** public — one of `public` (cloud models, freely), `private` (cloud or
  local, decided per request by the gateway; never the cloud as a stand-in when local models
  are unavailable) or `air-gapped` (local models only, no web tools). Either way, no agent
  pastes a non-public paper's text into a web search.
- **Required sections:** limitations, broader impact, reproducibility checklist
- **Style:** the venue class file, unmodified. No margin, font or `\vspace` hacks.

## Contribution, in one sentence

<The claim the paper lives or dies by. If this takes more than one sentence, the paper
does not yet have a contribution.>

## Notation and terminology

Fixed choices — use these and only these, everywhere.

| Concept | Term | Symbol |
|---|---|---|
| | | |

## Claims we do not make

Overclaims this project has decided against, so no drafting pass reintroduces them.

- e.g. no claim of state of the art on <benchmark> — the comparison is not controlled
- e.g. no efficiency claim without wall-clock on identical hardware

## Evidence conventions

- Every run writes to `evidence/<date>-<run-name>/` with `config.yaml`, `metrics.json`
  and the raw log.
- Tables cite their artifact path in a LaTeX comment directly above the tabular.
- Numbers are never transcribed by hand from a log into a table.
- **Code repo:** <git URL of the experiment code> — the experimenter clones it and pins a
  commit in each protocol.

## Repo layout

```
paper/{main.tex,sections/,figures/,refs.bib}   only research-writer edits this
claims.md                                      the ledger + experiment plan
outline.md                                     section plan, claim IDs per paragraph
notes/prior-art.{md,bib}                       closest prior work, verified BibTeX
evidence/                                      runs, logs, metrics
experiments/x<k>/                              protocol (frozen once approved), runs, result
reviews/round-N/                               referee reviews + meta.md
REVIEW_RUBRIC.md                               review format, venue-specific
```
