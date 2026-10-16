---
name: presubmission
description: The final pre-submission pass research-writer runs on a near-final paper — page limit as the venue counts it, double-blind scrub, required sections, unmodified style file, self-contained supplement — reported item by item as pass/fail. Used by research-writer; research-lead creates a board task for that agent rather than running this itself.
version: 1.0.0
metadata:
  hermes:
    tags: [latex, writing]
    category: research-papers
    requires_toolsets: [terminal]
---

# Pre-submission pass

Run `manuscript-check` first (auto-loaded); a paper that does not build clean is not near-final. Then
report each item below as **pass** or **fail**, with the location of every failure.

1. **Page limit**, under the venue's rules on what counts (references, appendix, ethics,
   checklist) — the limit is in `CLAUDE.md`.
2. **Double-blind scrub.** Run the scanner, then judge every hit by hand — not every hit is a
   violation, and not every violation is a pattern it knows:
   ```bash
   bash "__SKILLS_DIR__/presubmission/scripts/anon_scan.sh" .
   ```
   It looks for author and
   affiliation macros, acknowledgments and funding, repository/dataset URLs that identify
   the group, first-person references to prior work, and non-anonymous class options.
   Recast self-citations to third person: "Smith et al. showed", not "we previously showed".
   Also check PDF metadata and figure files for names.
3. **Required sections** present: limitations, ethics/broader impact, reproducibility
   statement, checklist — per `CLAUDE.md`.
4. **Style compliance:** the venue's class file unmodified; no shrunken margins or font
   sizes; no `\vspace` hacks to fit the limit.
5. **Supplementary material** builds and is self-contained.
