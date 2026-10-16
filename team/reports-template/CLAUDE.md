# Reports

The team's shared folder for audited research reports (the `research-report` skill). Every
agent reads this first.

- **Sensitivity:** public — reports here may use cloud models and web search freely. A
  confidential topic gets its own folder (`report-<slug>`, marked `private` or
  `air-gapped`), never this one.

## Layout

```
notes/<slug>/brief.md         research-lead: the request, question, sub-questions, scope
notes/<slug>/report.md        research-librarian: the report, every claim numbered [n]
notes/<slug>/sources.md       research-librarian: one line per [n], with ID and what was read
notes/<slug>/response-<k>.md  research-librarian: what changed after audit k
reviews/<slug>/audit-<k>.md   research-reviewer: findings and verdict for the version it read
```

A pass counts only for the version it audited; the ledger (`.tasks/ledger.jsonl`) records
the commit each audit read.
