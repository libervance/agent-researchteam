# The research team (team/)

The personal-lab wizard (`Start-HermesResearchSetup.cmd`) installs a four-agent team that
writes and reviews CS/AI papers and produces audited research reports. It replaces the
four-role governed broker of 0.10–0.12. The platform around it — local Mattermost in Docker,
the pinned Hermes install, Codex sign-in, bot issuance, distributions — is unchanged.

User-facing guide (Korean): [research-guide.ko.md](research-guide.ko.md).

## Roles, and how they map to the old team

| Profile | Role | Old role | Writes |
|---|---|---|---|
| `research-lead` | Talks to the user over Mattermost; scopes; dispatches work on the board; enforces gates (outline approval, stop at each round's checkpoint, user approval of every experiment protocol). Also writes the manuscript, builds LaTeX, maintains claims and prepares rebuttals; never acts as its own independent reviewer | manager (`research-lead`) | `CLAUDE.md`, `claims.md`, `notes/`, `paper/`, `outline.md` |
| `research-librarian` | Literature discovery, report drafting from sources it read, bibliography audit | researcher (`research-scout`) | `notes/`, `reviews/` |
| `research-experimenter` | Pre-registered experiment protocols; capped detached jobs once approved; collection and criterion checks | analyst (`research-worker`) | `experiments/`, `evidence/` |
| `research-reviewer` | Blind referee (novelty / methods / clarity), area chair, protocol check, report audit; no memory | auditor (`research-reviewer`) | `reviews/` |

Scenarios:

| Old | New |
|---|---|
| S1 evidence-backed report (`@research-lead … 보고서 작성해줘`) | `research-report` skill: brief → librarian draft + sources → reviewer audit against the sources → revision → fresh audit of the new version (up to 3) → Word file delivered to the thread |
| S2 independent numeric verification (held: "verifier not connected") | `research-experiment`: protocol → reviewer protocol check → user approval → frozen protocol → capped jobs → collection against pre-written criteria; referees verify every headline number against `evidence/` |
| S3 publication (held: human confirmations) | `research-round` checkpoints and the writer's pre-submission pass; submission itself stays with the user |
| — | `research-start` (scope → claims/experiment plan → outline → draft) and `research-round` (writer → 3 blind referees + bibliography audit → chair) |

## How work moves

Every paper (and the shared `reports/` folder) is a git repo in the workspace whose remote
is a bare repo under `RuntimeRoot\research\boards`. A task is a file `.tasks/<id>.md`.
These remotes are local Git repositories, not GitHub repositories. An existing `origin`
can be used instead, but the wizard does not create GitHub repositories, configure their
permissions, or synchronize the local `papers` registry to other PCs.
`research_board.py project-create <name>` scaffolds, initializes, binds and registers a
paper in one repeatable step. Its default remote is local; `--remote <url>` uses an
existing shared remote. `research_board.py` is the board: the lead creates tasks (`new`, with `--after`
dependencies), a runner per role (`run`) claims a ready task by pushing `status: running`,
runs `hermes -p <role> chat -Q --query-file <prompt>` once with the role's skills
preloaded, commits only that role's output paths plus the task file and one ledger line,
and maintains one progress post per task in its Mattermost thread as its own bot. `init`
remains available for manual registration of existing repositories. Runners re-read
`research\papers` on every pass.

The lead alone has an interactive Mattermost gateway. The other three profiles run only
as background board tasks; their bot tokens let the runners post progress to Mattermost.
A private lead coordinator reads new ledger results and invokes a bounded lead turn against
the board. It can plan the next authorized task without an agent-to-agent Mattermost mention.
Human approvals and review checkpoints still wait for the user's response.

Hermes profiles explicitly allow 80 tool turns per attempt. A worker that hits that limit
or the task's wall-clock limit saves a `partial` result and a versioned checkpoint under
`.tasks/attempts/`. Read/write roles may resume once from their files and checkpoint;
experimenter tasks default to manual continuation so an experiment is not relaunched
outside its approved retry policy. Dependent tasks require `done`.
If a background lead turn reaches its own limit, its output is saved under
`research/run/lead-attempts/`; the coordinator advances that event and asks the user to
resume with the interactive lead. It does not treat a capped lead turn as completed work.

The setup writes `RESEARCH_PATHS.md` in the selected workspace. It lists the current
project folders and remotes, board and ledger locations, team runtime, logs, profiles,
and server deployment root. `research_board.py project-create` refreshes it for new projects;
`research_board.py locations --write` refreshes it on demand. The wizard shows the full
path to the guide after setup.

Blind roles (reviewer, librarian) run in an exported snapshot without `.git` or `.tasks/`.
An experiment's `protocol.md` is frozen once `approval.md` exists; an edit is reverted and
the task failed.

## What was kept from the governed broker

| Broker mechanism | Here |
|---|---|
| Persona files pinned by SHA-256, checked on every model call | `team/manifest.json` checked before install; `profile-manifest.json` (SOUL + skills of each runner profile) checked by the runner before every task — a drifted profile's task is blocked, not run |
| Append-only artifacts/audits/evidence (SQLite triggers), every version hashed | `.tasks/ledger.jsonl`: one line per finished task with the commit it worked on and the SHA-256 of every file it published; each line carries the hash of the previous line, so a rewrite is detected (`ledger --verify`) and reported in the thread. The newest line is protected by git history only |
| An audit pass counts only for the exact version audited | Each task records `base` (the commit it read); the round checkpoint names the reviewed commit; a report revision always gets a fresh audit |
| Transient model errors retried with backoff | Runner retries a run that fails on rate limit / overload / timeout / 5xx after 30 s and 2 min |
| Per-role time budget | Per-task time limit (wizard: 30–720 min) and kill of the whole process tree |
| Only allowed users trigger work; bot posts carry no authority | `MATTERMOST_ALLOWED_USERS` = the verified person; agents never take work from chat, only from the board |
| Service credentials filtered from child environment | Runner bot tokens and the router secret live with the team service; the runner strips them from the child environment. Lead retains its chat credentials in its profile; this is not OS-level isolation |
| Word report generated by the program, uploaded, downloaded again and SHA-256 compared | `report_docx.py` (same writer) via `deliver: <file.md>:docx`; PDFs and other files the same way; failed delivery is reported, never turned into a rewrite |
| Live four-role test before "ready" | `team_selftest.py`: one small real task per role through the running service, the lead answers via its own skills, ledger verified, delivery verified |
| Owned scheduled tasks, ownership checks, migration with maintenance hand-off and backup | Reused as-is for the two new tasks and for migrating a PC that has the broker team |

Not carried over: the program-run state machine and tool-less model turns. Agents here are
full Hermes agents (Git Bash terminal, files, web) because writing LaTeX and running
experiments need tools; containment comes from the board (output paths, blind snapshots,
frozen protocols, gates) rather than from a fixed action list.

## Models

`RuntimeRoot\research\gateway`: LiteLLM 1.105.1 in its own venv on `127.0.0.1:<port>`,
`research_gateway_litellm.py` auth/routing hooks, `routing.yaml` (tier per role, effort per
tier), and `litellm.config.yaml` rendered from the wizard's choices by `render_config.py`.
Each task's key is `rgw.<profile>.<sensitivity>.<secret>`, built by the runner from the
paper's `**Sensitivity:**` line: `public` → cloud, `private` → local (refused when no local
model is configured — never sent to the cloud instead), `air-gapped` → local only and no web.
Codex direct mode skips the router; the runner then refuses non-public papers itself.

## Windows specifics

- Hermes runs every terminal command in Git Bash. Skills call Python and the board by
  absolute forward-slash paths in bash arrays (`PB=("C:/…/python.exe" "C:/…/research_board.py")`).
- Prompts go through `--query-file` (no command-line length or quoting limits).
- Text files are read and written as UTF-8 with LF; board clones use `core.autocrlf=false`.
- Process checks use `OpenProcess`/`GetExitCodeProcess` (`os.kill(pid, 0)` terminates on
  Windows); timeouts kill the tree with `taskkill /T /F`; experiment jobs start detached and
  break away from the service's job object so they outlive restarts.
- The team service puts its children in a kill-on-close job object.

## Files

```
team/
  research-<role>/SOUL.md, config.overlay.yaml, skills/<skill>/SKILL.md (+ scripts)
  shared/research_board.py   board, runner, ledger, delivery
  shared/team_service.py     supervisor: router + runners, status file, restarts
  shared/team_selftest.py    the install-time live test
  shared/report_docx.py      Markdown → Word, no dependencies
  shared/merge_config.py     config overlay merge (Hermes's PyYAML)
  shared/team.hermes.md      team context dropped into every task
  gateway/                   router hooks, routing, config template + renderer, tests
  template/                  new-paper template;  reports-template/  the reports board
  manifest.json              SHA-256 of all of the above (build_manifest.py)
```

After editing anything under `team/`, run `python team/build_manifest.py`; CI fails while the
manifest is stale.

## Tested vs. assumed

Tested offline (CI and locally): the board end to end with a stub `hermes` and a mock
Mattermost (outputs filtering, blind snapshots, ledger chain and tamper detection, retries,
profile drift, private-paper refusal, frozen protocols, long prompts, verified delivery),
the team service (per-runner tokens, restarts, clean stop), router config rendering against
the routing policy, and the PowerShell installer with every process/network/Task Scheduler
boundary mocked (fresh install, reset, refusals, Codex mode, migration from the broker team,
live-test evidence gate).

Not yet run on a real Windows PC with live models: the full wizard flow, LiteLLM on Windows,
Git Bash command rendering inside real agent turns, and the live test itself. The wizard
only reports "ready" after that live test passes on the PC.

## Four-role update and graphical board (0.15.0)

The active roles are lead (including manuscript authoring), librarian, experimenter and reviewer.
Existing managed five-role teams update in place: four profiles and bot tokens are reused;
writer's profile, sessions, bot account and private token remain stored but no writer runner
is started. Historical writer tasks are serviced by lead, keeping task IDs and history.
The writer may remain visible in Mattermost; it is inactive. Its source skills are retained
for a possible future release. Librarian still writes literature/research-trend reports.

Open **연구 보드 열기** in the installer or double-click **Research Board.url** in the
research workspace. The service maintains that shortcut. The board runs only on the host
PC at a loopback address, refreshes every ten seconds, and shows projects, task states,
assignees, dependencies, attempts, saved results and approval requests. Select a task to
preview text outputs or open a PDF. It reads committed snapshots from the shared local
bare repository, so it does not require manually pulling the user's project clone.
External Git remotes show only the local snapshot and are labeled accordingly.

The page is read-only. It does not submit instructions or approvals. Outputs larger than
20 MB cannot be previewed. Binary formats other than PDF should be obtained from Mattermost
attachments. Task counts are progress indicators, not a percentage estimate of research difficulty.

### Notifications and confirmations

The coordinator sends lead-bot notices for completed, partial, failed and blocked board
results, with saved output paths, and requests decisions for checkpoints. It retries failed
notices and records delivery receipts. Runtime synchronization errors produce a separate
attention notice. The lead's instructions additionally require scope, location, assignments,
material findings, uncertainties, missing evidence, resource/scope changes and final handoff.
Semantic judgments still depend on the model; software cannot guarantee it identifies every
scientifically important finding. Mattermost/server outages delay notices until service returns.

New tasks default to `--gate human`. Use `--gate auto` only for internal steps in an already
approved phase. Milestones include scope/contribution, literature and gaps, experiment design,
interpretation, outline, draft, review decisions and final readiness. A done human-gated task
pauses all new tasks in that project, including tasks without explicit dependencies. Work
already running is allowed to finish. Explicitly reopened checkpoint revisions may run
while other checkpoints await approval, so requested corrections are not deadlocked. Other projects continue. Existing tasks retain their
stored gate; when resuming an old project, lead must review its remaining milestone gates.

To approve, review the outputs and send the exact `approve TASK-ID TOKEN` shown on the board
or in the lead's message, in that task's Mattermost thread. The coordinator verifies the
configured human account, channel, thread and version token. Bot replies, silence and a
bare "OK" cannot release the checkpoint. Editing a result invalidates its old approval.
For changes, ask lead to append your feedback and reset that same checkpoint task to ready;
the revised result will request a fresh decision. Experiment protocol approval is an
additional record and remains mandatory before launching experiments. Submission/publication
remain actions for the user.
