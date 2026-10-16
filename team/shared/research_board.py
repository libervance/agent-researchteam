#!/usr/bin/env python3
"""research_board — the research team's task board, carried inside each paper's git repo.

The agents share nothing but each paper's git remote, so that is the board: one task = one
file, <paper>/.tasks/<id>.md. On one PC the remotes are bare repos under
<team home>/boards/; across devices any git remote every device can push to works.

  Lead (interactive, in its clone of the paper; the workspace is its terminal cwd):
    research_board.py init   <folder>              # give a new paper (or report folder) its board
    research_board.py new    <paper> --id r1-methods --assignee research-reviewer --after r1-writer \
                                 --expects reviews/round-1/methods.md --body-file prompt.md
    research_board.py list   <paper>
    research_board.py show   <paper> <id>
    research_board.py wait   <paper> <id> [<id> ...] [--timeout 150]
    research_board.py edit   <paper> <id> [--after a,b] [--append TEXT] [--status ready]
    research_board.py publish <paper> -m MSG <path> [...]      # lead's own files (CLAUDE.md, claims.md, notes/)
    research_board.py ledger <paper> [--verify]                # what each task read and produced
    research_board.py deliver <paper> <path>[:docx] --thread TH   # attach a file to the thread, verified

    research_board.py setup  <paper> --channel <team>/<channel-name> [--mention @you]   # once per paper
    research_board.py thread <paper> "Round 2 — writer → 3 referees + bib audit → chair"
                                 # prints a post id; pass it to `new --thread` for the round's tasks
    research_board.py approve <paper> x1 --by @you [--amendment 1]   # record the user's approval

  Worker (one per role; start several --slot's for parallel referees):
    research_board.py run --role research-reviewer [--slot 1] [--papers-file F] [<git-url> ...]

A worker loop: fetch -> pick a `ready` task for its role whose `after` tasks are all `done`
-> claim it by pushing `status: running` (a rejected push means another worker won) -> run
`hermes -p <role> chat -Q -q <task body>` once -> commit only the role's output paths, the
task file and one ledger line -> push. With --papers-file the list of papers is re-read on
every pass, so a paper added with `init` is picked up without restarting the runners.

Blind roles (research-reviewer, research-librarian) run in an exported snapshot of the paper
with no .git and no .tasks/, so no commit message, task body or writer report reaches them.

Record (.tasks/ledger.jsonl, append-only): one line per finished task — role, status, the
commit the agent worked on, and the SHA-256 of every file it published. Each line carries the
hash of the line before it, so a rewritten history is detected (`ledger --verify`) and
reported instead of silently extended. A review therefore always names the exact version it
read; the task result and the round checkpoint repeat that commit.

Safeguards: before each task the runner checks the profile's SOUL.md and team skills against
the manifest written at install (profile-manifest.json next to this file); a changed file blocks the
task instead of running an agent with unknown instructions. A run that fails on a transient
model error (rate limit, overload, timeout, 5xx) is retried with backoff. The agent's process
never receives the bot token or the gateway secret.

Delivery: a task may carry `deliver: <path>[:docx], ...`. When it is done the runner attaches
each file to the task's thread as its own bot, downloads it again and compares SHA-256; a
Markdown report with `:docx` is converted to Word first (report_docx.py, no dependencies).
Delivery happens after the work is accepted, so a failed upload never turns into a rewrite.

Experiments: a task may carry `ready_when: jobs-done <exp-id>`; the runner then starts it only
once every job the experimenter launched for that experiment (under <team home>/jobs/, or
$RESEARCH_TEAM_JOBS) has finished, and posts job progress while it waits. An experiment's
protocol.md is frozen once the lead has recorded an approval.md next to it: the runner
restores any edit to it, or to any approval.md, and fails the task.

Progress goes to Mattermost when the paper has `.tasks/board.conf` (written by `setup`):
the runner posts claimed / still running / done / blocked / failed into the task's round
thread, as the bot of the worker doing the work, and @mentions the user on anything that
needs them and on the round checkpoint. Credentials: MATTERMOST_URL and MATTERMOST_TOKEN
from the environment, else from the Hermes profile's .env. Posting never blocks the board —
if Mattermost is down, the git board still works.

Model gateway (optional, ../gateway/): when RESEARCH_GATEWAY_SECRET is set (environment, else the
Hermes profile's .env), each task's hermes process gets RESEARCH_GATEWAY_API_KEY =
rgw.<profile>.<sensitivity>.<secret>, with the sensitivity read from the paper's CLAUDE.md
(`**Sensitivity:** public|private|air-gapped`; a missing line counts as public for now, an
unreadable CLAUDE.md as private).
The gateway decides which models each class may use (../gateway/routing.yaml). Before a
non-public task, the runner asks the gateway (model `research-probe`) whether it can serve it;
if local models are unavailable the task is marked blocked with that reason instead of run.
Without a gateway, a non-public paper is refused the same way: its models would be cloud ones.

Paths: RESEARCH_TEAM_HOME (default ~/.hermes-research-team), HERMES_HOME or HERMES_ROOT
(default ~/.hermes) for the profiles, RESEARCH_TEAM_HERMES or --hermes for the hermes command.
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess as sp
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

TASKS = ".tasks"
LEDGER = f"{TASKS}/ledger.jsonl"
FIELDS = ["id", "assignee", "status", "after", "ready_when", "expects", "skills", "thread", "notify_done",
          "deliver", "claimed_by", "base", "updated"]
TERMINAL = {"done", "blocked", "failed"}
# What each role may publish. Everything else a worker leaves behind is discarded.
OUTPUTS = {
    "research-writer": ["paper", "claims.md", "outline.md"],
    "research-reviewer": ["reviews"],
    "research-librarian": ["reviews", "notes"],
    "research-experimenter": ["experiments", "evidence"],
}
BLIND = {"research-reviewer", "research-librarian"}
# Skills every task of a role preloads (Hermes has no per-profile auto-load), plus the task's own.
ROLE_SKILLS = {
    "research-writer": ["manuscript-check"],
    "research-reviewer": ["lit-search"],
    "research-librarian": ["lit-search"],
    "research-experimenter": ["lit-search"],
}
BUILD_JUNK = ["aux", "log", "fls", "fdb_latexmk", "out", "synctex.gz", "blg", "toc", "bcf", "run.xml"]
GITIGNORE = [".DS_Store", "Thumbs.db", ".hermes.md"] + [f"*.{e}" for e in BUILD_JUNK]
HERE = Path(__file__).resolve().parent
TEAM_CONTEXT = HERE / "team.hermes.md"


def _team_home():
    """RESEARCH_TEAM_HOME, else the home the installer recorded next to this file, else the default."""
    if os.environ.get("RESEARCH_TEAM_HOME"):
        return Path(os.environ["RESEARCH_TEAM_HOME"])
    rec = HERE / "team-home.txt"
    if rec.is_file() and rec.read_text(encoding="utf-8").strip():
        return Path(rec.read_text(encoding="utf-8").strip())
    return Path.home() / ".hermes-research-team"


TEAM_HOME = _team_home()
JOBS = Path(os.environ.get("RESEARCH_TEAM_JOBS", TEAM_HOME / "jobs"))
# Written at install: SHA-256 of each profile's SOUL.md and team skills.
MANIFEST = Path(os.environ.get("RESEARCH_TEAM_MANIFEST", HERE / "profile-manifest.json"))
WINDOWS = os.name == "nt"
MAX_DELIVERY_BYTES = 25 * 1024 * 1024
RETRY_DELAYS = [30, 120]
TRANSIENT = re.compile(r"\b(429|500|502|503|504|529)\b|rate.?limit|overloaded|temporar(il)?y unavailable|"
                       r"timed? ?out|connection (reset|refused|aborted|error)|ECONNRESET|service unavailable", re.I)
# Never handed to an agent's process: the agent does not post as the bot or mint gateway keys.
CHILD_ENV_DROP = {"MATTERMOST_TOKEN", "MATTERMOST_URL", "RESEARCH_GATEWAY_SECRET"}
SENSITIVE_NOTE = {
    "private": """
Sensitivity: private — keep this paper's unpublished text, results and claims out of web
searches and fetched URLs; search the literature by topic terms only.
""",
    "air-gapped": """
Sensitivity: air-gapped — do not use any web search, web fetch or browser tool for this
task, and send nothing about the paper off this machine. If the task cannot be done without
the web, block and say so.
""",
}
FOOTER = """
---
Runner note: you are task `{id}`, running unattended as {role}. Your working directory is
the paper folder ({cwd}); every path in this task is relative to it. There is no human to
answer questions — if you cannot proceed, block. Do not run git; the runner commits your
output. End your reply with exactly one line:
`STATUS: done` or `STATUS: blocked — <reason>`.
"""


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def die(msg):
    sys.exit(f"research_board: {msg}")


def rd(path):
    """Text files are UTF-8 everywhere (Windows would otherwise use the ANSI code page)."""
    return Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def wr(path, text, append=False):
    with open(path, "a" if append else "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(repo, *args, check=True):
    r = sp.run(["git", "-C", str(repo), *args], capture_output=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def git_identity(repo, name):
    """Commits need an author; a fresh Windows user often has none configured."""
    if not git(repo, "config", "user.email", check=False).stdout.strip():
        git(repo, "config", "user.name", name)
        git(repo, "config", "user.email", f"{name}@research-team.local")
    git(repo, "config", "core.autocrlf", "false")  # task files must keep LF


def hermes_root():
    return Path(os.environ.get("HERMES_HOME") or os.environ.get("HERMES_ROOT") or Path.home() / ".hermes")


def repo_name(url):
    return re.sub(r"\.git$", "", re.split(r"[\\/:]", url.rstrip("/\\"))[-1])


# ---------- processes (POSIX and Windows) ----------

def pid_alive(pid):
    if WINDOWS:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def kill_tree(proc):
    """Stop an agent and everything its shell started."""
    if WINDOWS:
        sp.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, 9)
        except OSError:
            proc.kill()


def popen_group(cmd, **kw):
    if WINDOWS:
        kw["creationflags"] = kw.get("creationflags", 0) | sp.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return sp.Popen(cmd, **kw)


# ---------- task files ----------

def load(path):
    m = re.match(r"---\n(.*?)\n---\n?(.*)", rd(path), re.S)
    if not m:
        die(f"{path}: no front matter")
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip()
    return meta, m.group(2)


def save(path, meta, body):
    fm = "\n".join(f"{k}: {meta.get(k, '')}".rstrip() for k in FIELDS)
    path.parent.mkdir(exist_ok=True)
    wr(path, f"---\n{fm}\n---\n{body}")


def csv(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def tasks(repo):
    d = Path(repo) / TASKS
    return {p.stem: (p, *load(p)) for p in sorted(d.glob("*.md"))} if d.is_dir() else {}


def waiting_on(meta, board):
    return [a for a in csv(meta.get("after")) if a not in board or board[a][1].get("status") != "done"]


# ---------- git plumbing ----------

def sync(repo):
    """Lead clone: bring in the workers' pushes, keeping any local edits."""
    git(repo, "pull", "--rebase", "--autostash", "-q")


def stage(repo, paths, excludes=()):
    """Stage paths; return the staged file names (relative, '/'-separated)."""
    spec = [str(p) for p in paths if (Path(repo) / p).exists()] + [f":(exclude,glob)**/*.{e}" for e in excludes]
    if not any(not s.startswith(":(") for s in spec):
        return []
    git(repo, "add", "-A", "--", *spec)
    return [l for l in git(repo, "diff", "--cached", "--name-only").stdout.splitlines() if l.strip()]


def commit_push(repo, msg):
    if not git(repo, "diff", "--cached", "--quiet", check=False).returncode:
        return False
    git(repo, "commit", "-q", "-m", msg)
    for _ in range(5):
        if not git(repo, "push", "-q", check=False).returncode:
            return True
        if git(repo, "pull", "--rebase", "-q", check=False).returncode:
            git(repo, "rebase", "--abort", check=False)
            raise RuntimeError("rebase conflict while publishing — resolve by hand")
    raise RuntimeError("push kept failing")


def publish(repo, paths, msg, excludes=()):
    """Stage paths, commit, push; rebase and retry if another worker pushed first."""
    stage(repo, paths, excludes)
    return commit_push(repo, msg)


def reset_to_remote(repo):
    git(repo, "fetch", "-q", "origin")
    git(repo, "reset", "-q", "--hard", "@{u}")
    git(repo, "clean", "-fdq")


# ---------- ledger (append-only, hash-chained) ----------

def ledger_lines(repo):
    p = Path(repo) / LEDGER
    return [l for l in rd(p).splitlines() if l.strip()] if p.is_file() else []


def ledger_check(lines):
    """-> index of a line whose `prev` does not match the line before it (or that is not JSON),
    or None. A break that a later entry records (`chain_break_at_line`) counts as reported."""
    prev, broken = "", None
    for i, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        if broken is None and (entry is None or entry.get("prev", "") != prev):
            broken = i
        elif broken is not None and entry and entry.get("chain_break_at_line") == broken + 1:
            broken = None
        prev = hashlib.sha256(line.encode("utf-8")).hexdigest()
    return broken


def ledger_append(repo, entry):
    lines = ledger_lines(repo)
    broken = ledger_check(lines)
    entry = dict(entry)
    if broken is not None:
        entry["chain_break_at_line"] = broken + 1  # recorded, never repaired silently
    entry["prev"] = hashlib.sha256(lines[-1].encode("utf-8")).hexdigest() if lines else ""
    p = Path(repo) / LEDGER
    p.parent.mkdir(exist_ok=True)
    wr(p, json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n", append=True)
    return broken


# ---------- Mattermost ----------

def _dotenv(path):
    out = {}
    if path.is_file():
        for line in rd(path).splitlines():
            k, sep, v = line.strip().partition("=")
            if sep and not k.startswith("#"):
                out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def profile_env(profile):
    """The profile's own .env — the only one a Hermes profile reads (not the root .env)."""
    return _dotenv(hermes_root() / "profiles" / profile / ".env")


def sensitivity(clone):
    """The paper's `**Sensitivity:**` from its CLAUDE.md. No such line: public (the current
    default). No readable CLAUDE.md: private, since we cannot tell what the paper is."""
    try:
        text = rd(Path(clone) / "CLAUDE.md")
    except OSError:
        return "private"
    m = re.search(r"\*\*Sensitivity:\*\*\s*`?(public|private|air-gapped)\b", text, re.I)
    return m.group(1).lower() if m else "public"


def child_env(clone, profile):
    """Environment for one task's hermes process: the gateway key for this paper if a gateway
    is configured; never the bot token or the gateway secret."""
    env = {k: v for k, v in os.environ.items() if k not in CHILD_ENV_DROP}
    sens = sensitivity(clone)
    secret = os.environ.get("RESEARCH_GATEWAY_SECRET") or profile_env(profile).get("RESEARCH_GATEWAY_SECRET")
    if secret:
        env["RESEARCH_GATEWAY_API_KEY"] = f"rgw.{profile}.{sens}.{secret}"
    return env, sens, bool(secret)


def gateway_probe(env, profile):
    """Ask the gateway whether it can serve this task (model `research-probe`; no model is
    called). -> None if it can, or cannot be asked; else the reason it cannot."""
    url = env.get("RESEARCH_GATEWAY_URL") or profile_env(profile).get("RESEARCH_GATEWAY_URL")
    key = env.get("RESEARCH_GATEWAY_API_KEY")
    if not url or not key:
        return None
    req = urllib.request.Request(
        url.rstrip("/") + "/chat/completions", method="POST",
        data=json.dumps({"model": "research-probe", "max_tokens": 1,
                         "messages": [{"role": "user", "content": "probe"}]}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30).close()
        return None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error", {}).get("message", "")
        except ValueError:
            msg = ""
        if "research-gateway-probe: ok" in msg:
            return None
        return msg.removeprefix("research-gateway: ") or f"gateway answered HTTP {e.code}"
    except OSError as e:
        return f"model gateway unreachable at {url} ({e})"


def mm_creds(profile):
    """URL and bot token: environment, else the Hermes profile's own .env."""
    env = profile_env(profile)
    env.update({k: v for k, v in os.environ.items() if k.startswith("MATTERMOST_")})
    url, token = env.get("MATTERMOST_URL", "").rstrip("/"), env.get("MATTERMOST_TOKEN", "")
    return (url, token) if url and token else None


def mm_api(creds, method, path, payload=None):
    url, token = creds
    req = urllib.request.Request(f"{url}/api/v4{path}", method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def mm_upload(creds, channel, name, data, mime):
    """Upload one file; -> file id. Fails unless the server reports exactly this file."""
    url, token = creds
    boundary = "research" + uuid.uuid4().hex
    safe = re.sub(r'[^A-Za-z0-9._-]', "_", name)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"channel_id\"\r\n\r\n{channel}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{safe}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{url}/api/v4/files", data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        infos = json.load(r).get("file_infos", [])
    if len(infos) != 1 or infos[0].get("size") != len(data):
        raise RuntimeError("upload not confirmed by the server")
    return infos[0]["id"]


def mm_download(creds, file_id):
    url, token = creds
    req = urllib.request.Request(f"{url}/api/v4/files/{file_id}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read(MAX_DELIVERY_BYTES + 1)


def board_conf(repo):
    return _dotenv(Path(repo) / TASKS / "board.conf")


class Notifier:
    """Posts task events for one paper. Every failure is logged and swallowed."""

    def __init__(self, repo, profile):
        self.conf, self.creds = board_conf(repo), mm_creds(profile)
        self.channel = self.conf.get("mattermost_channel")
        self.mention = self.conf.get("mention", "")

    def post(self, text, thread="", ping=False, file_ids=None):
        if not (self.creds and self.channel):
            return None
        try:
            msg = f"{text} {self.mention}".rstrip() if ping else text
            payload = {"channel_id": self.channel, "message": msg, "root_id": thread or ""}
            if file_ids:
                payload["file_ids"] = file_ids
            return mm_api(self.creds, "POST", "/posts", payload)["id"]
        except Exception as e:  # never let chat break the board
            print(f"[{now()}] mattermost: {e}", file=sys.stderr, flush=True)
            return None

    def deliver(self, name, data, mime, thread, label):
        """Attach bytes to the thread, read them back, compare SHA-256. -> (ok, detail)."""
        if not (self.creds and self.channel):
            return False, "no Mattermost channel or bot token for this paper"
        digest = hashlib.sha256(data).hexdigest()
        try:
            fid = mm_upload(self.creds, self.channel, name, data, mime)
            if hashlib.sha256(mm_download(self.creds, fid)).hexdigest() != digest:
                return False, "the downloaded copy does not match (SHA-256)"
            if not self.post(f":page_facing_up: {label} — sha256 `{digest[:16]}…`, verified after upload", thread, file_ids=[fid]):
                return False, "uploaded and verified, but the post failed"
            return True, digest
        except Exception as e:
            return False, str(e)[:300]


def headline(report, limit=600):
    lines = [l.strip() for l in report.splitlines() if l.strip() and not re.match(r"^\W*STATUS:", l.strip(), re.I)]
    text = " · ".join(lines[:4])
    return text if len(text) <= limit else text[:limit - 1] + "…"


def checkpoint(meta_md):
    """One line from the chair's meta.md: the call and the plan's tag counts."""
    text = rd(meta_md) if meta_md.is_file() else ""
    counts = " · ".join(f"{t} {len(re.findall(t, text))}" for t in ("CLAIM-CHANGING", "EVIDENCE-NEEDED", "PRESENTATION"))
    call = ""
    m = re.search(r"^\W*(?:#+\s*)?\**Call\**\W*(.*)$", text, re.M | re.I)
    if m:
        call = m.group(1).strip() or next((l.strip() for l in text[m.end():].splitlines() if l.strip()), "")
    return f"Call: {call[:300] or '(see meta.md)'} — {counts}"


def fmt_age(sec):
    return f"{int(sec // 3600)}h {int(sec % 3600 // 60)}m"


# ---------- experiment jobs (same layout as exp-run/scripts/launch.py) ----------

def job_state(d):
    """done / failed / capped / running / lost for one run dir <JOBS>/<paper>/<exp>/<run>/."""
    if (d / "DONE").exists():
        code = rd(d / "exit_code").strip() if (d / "exit_code").exists() else "?"
        return "done" if code == "0" else ("capped" if code == "124" else "failed")
    try:
        return "running" if pid_alive(int(rd(d / "pid").strip())) else "lost"
    except (OSError, ValueError):
        return "lost"  # no DONE and no live process: machine rebooted or the job was killed


def jobs_summary(paper, exp):
    runs = sorted(x for x in (JOBS / paper / exp).glob("*") if x.is_dir()) if (JOBS / paper / exp).is_dir() else []
    states = [job_state(r) for r in runs]
    starts = [r.stat().st_mtime for r in runs]
    return {"total": len(runs), **{k: states.count(k) for k in ("done", "failed", "capped", "running", "lost")},
            "age": time.time() - min(starts) if starts else 0}


def condition_met(clone, cond):
    """Built-in wait conditions only — never shell from a task file. Returns (met, why, lost)."""
    if not cond:
        return True, "", 0
    kind, _, arg = cond.partition(" ")
    if kind == "jobs-done" and arg.strip():
        js = jobs_summary(clone.name, arg.strip())
        if js["total"] == 0:
            return False, "no jobs launched on this device", 0
        return js["running"] == 0, (f"jobs {js['total'] - js['running']}/{js['total']} finished"
                                    f" ({js['done']} ok, {js['failed']} failed, {js['capped']} hit the time cap,"
                                    f" {js['lost']} lost), running {fmt_age(js['age'])}"), js["lost"]
    return False, f"unknown ready_when condition: {cond}", 0


def guard_frozen(clone):
    """Undo edits to approval records and to approved protocols; return what was touched."""
    st = git(clone, "status", "--porcelain", "-uall").stdout.splitlines()
    touched = []
    for line in st:
        path = line[3:].split(" -> ")[-1].strip('"')
        m = re.match(r"experiments/([^/]+)/(approval\.md|protocol\.md)$", path)
        if not m:
            continue
        approved = git(clone, "cat-file", "-e", f"HEAD:experiments/{m.group(1)}/approval.md", check=False).returncode == 0
        if m.group(2) == "approval.md" or approved:
            touched.append(path)
            if git(clone, "cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0:
                git(clone, "checkout", "HEAD", "--", path)
            else:
                (clone / path).unlink(missing_ok=True)
    return touched


# ---------- profile integrity ----------

def profile_drift(profile):
    """Files of the profile that differ from the install manifest: [] when all match, None when
    there is no manifest (an install without one, e.g. an older Mac install)."""
    if not MANIFEST.is_file():
        return None
    try:
        expected = json.loads(rd(MANIFEST)).get("profiles", {}).get(profile)
    except ValueError:
        return ["manifest.json (unreadable)"]
    if expected is None:
        return [f"{profile} (not in manifest)"]
    root = hermes_root() / "profiles" / profile
    bad = [rel for rel, digest in expected.items()
           if not (root / rel).is_file() or sha256_file(root / rel) != digest]
    skills = root / "skills" / "research-team"
    if skills.is_dir():
        for f in skills.rglob("*"):
            rel = f.relative_to(root).as_posix()
            if f.is_file() and rel not in expected and "__pycache__" not in rel:
                bad.append(rel + " (not installed by the team)")
    return sorted(bad)


# ---------- lead commands ----------

def cmd_init(a):
    """Make a folder a paper with a task board: a git repo whose remote is a bare repo under
    <team home>/boards/, registered in the papers file the runners read."""
    d = Path(a.folder).resolve()
    if not d.is_dir():
        die(f"no folder {d}")
    if not (d / "CLAUDE.md").is_file() and not a.force:
        die(f"{d} has no CLAUDE.md — scaffold it from _template/ first (or pass --force)")
    if not (d / ".git").exists():
        git(d, "init", "-q", "-b", "main")
    git_identity(d, "research-lead")
    gi = d / ".gitignore"
    have = rd(gi).splitlines() if gi.is_file() else []
    missing = [p for p in GITIGNORE if p not in have]
    if missing:
        wr(gi, "\n".join(have + missing) + "\n")
    if git(d, "rev-parse", "-q", "--verify", "HEAD", check=False).returncode:
        git(d, "add", "-A")
        git(d, "commit", "-q", "-m", "initial import for the research team")
    r = git(d, "remote", "get-url", "origin", check=False)
    if r.returncode == 0:
        url = r.stdout.strip()
        print(f"{d.name}: using its existing remote {url}")
    else:
        boards = Path(a.boards) if a.boards else TEAM_HOME / "boards"
        boards.mkdir(parents=True, exist_ok=True)
        bare = boards / f"{d.name}.git"
        if not bare.exists():
            sp.run(["git", "init", "-q", "--bare", str(bare)], check=True)
        url = str(bare)
        git(d, "remote", "add", "origin", url)
        branch = git(d, "symbolic-ref", "--short", "HEAD").stdout.strip()
        git(d, "push", "-q", "-u", "origin", branch)
        sp.run(["git", f"--git-dir={bare}", "symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True)
        print(f"{d.name}: task board at {url}")
    papers = Path(a.papers_file) if a.papers_file else TEAM_HOME / "papers"
    papers.parent.mkdir(parents=True, exist_ok=True)
    known = rd(papers).splitlines() if papers.is_file() else []
    if url not in known:
        wr(papers, url + "\n", append=True)
        print(f"registered in {papers}; runners started with --papers-file pick it up on their next pass")


def cmd_new(a):
    repo = Path(a.paper)
    sync(repo)
    p = repo / TASKS / f"{a.id}.md"
    if p.exists():  # idempotent: re-running a skill step never duplicates a task
        print(f"{a.id}: exists, status {load(p)[0].get('status')}")
        return
    if a.assignee not in OUTPUTS:
        die(f"assignee must be one of {', '.join(OUTPUTS)}")
    for item in csv(a.deliver):
        path, _, kind = item.partition(":")
        if kind not in ("", "docx") or (kind == "docx" and not path.endswith(".md")):
            die(f"--deliver {item}: use <path> or <report.md>:docx")
    body = a.body if a.body is not None else (sys.stdin.read() if a.body_file == "-" else rd(a.body_file))
    meta = {"id": a.id, "assignee": a.assignee, "status": "ready", "after": a.after or "",
            "expects": a.expects or "", "skills": a.skills or "", "thread": a.thread or "",
            "ready_when": a.ready_when or "", "notify_done": a.notify_done or "", "deliver": a.deliver or "",
            "updated": now()}
    save(p, meta, body.strip() + "\n")
    publish(repo, [p.relative_to(repo)], f"board: new task {a.id} -> {a.assignee}")
    print(f"{a.id}: created for {a.assignee}" + (f", after {a.after}" if a.after else ""))


def cmd_list(a):
    repo = Path(a.paper)
    if not a.no_sync:
        sync(repo)
    board = tasks(repo)
    if not board:
        print("(no tasks)")
    for tid, (_, m, _) in board.items():
        st = m.get("status")
        w = waiting_on(m, board) if st == "ready" else []
        extra = f"  waiting on {', '.join(w)}" if w else ""
        if st == "ready" and not w and m.get("ready_when"):
            extra = f"  until {m['ready_when']} (checked on the worker's device)"
        who = f"  [{m['claimed_by']}]" if m.get("claimed_by") and st == "running" else ""
        base = f"  @{m['base'][:10]}" if m.get("base") and st in TERMINAL else ""
        print(f"{tid:28} {st:8} {m.get('assignee', ''):15} {m.get('updated', '')}{who}{base}{extra}")


def cmd_show(a):
    repo = Path(a.paper)
    sync(repo)
    p = repo / TASKS / f"{a.id}.md"
    print(rd(p) if p.exists() else f"{a.id}: no such task")


def cmd_wait(a):
    repo, t0 = Path(a.paper), time.time()
    while True:
        sync(repo)
        board = tasks(repo)
        st = {i: board[i][1].get("status") if i in board else "missing" for i in a.ids}
        if all(s in TERMINAL or s == "missing" for s in st.values()) or time.time() - t0 > a.timeout:
            for i, s in st.items():
                print(f"{i}: {s}")
            sys.exit(0 if all(s == "done" for s in st.values()) else 2)
        time.sleep(a.poll)


def cmd_edit(a):
    repo = Path(a.paper)
    sync(repo)
    p = repo / TASKS / f"{a.id}.md"
    if not p.exists():
        die(f"{a.id}: no such task")
    meta, body = load(p)
    if a.after is not None:
        meta["after"] = a.after
    if a.append:
        body = body.rstrip() + "\n\n" + a.append.strip() + "\n"
    if a.status:
        meta["status"] = a.status
        if a.status == "ready":
            meta["claimed_by"] = ""
            meta["base"] = ""
            body = re.split(r"\n## Result — ", body)[0].rstrip() + "\n"  # retry starts clean
    meta["updated"] = now()
    save(p, meta, body)
    publish(repo, [p.relative_to(repo)], f"board: edit {a.id}")
    print(f"{a.id}: updated")


def cmd_ledger(a):
    repo = Path(a.paper)
    if not a.no_sync:
        sync(repo)
    lines = ledger_lines(repo)
    broken = ledger_check(lines)
    if a.verify:
        if broken is None:
            print(f"ledger intact: {len(lines)} entries")
            return
        die(f"ledger chain broken at line {broken + 1} of {len(lines)} — someone rewrote it; see git log -p {LEDGER}")
    for line in lines:
        e = json.loads(line)
        outs = ", ".join(f"{k} {v[:8]}" for k, v in sorted(e.get("outputs", {}).items())[:6])
        more = len(e.get("outputs", {})) - 6
        print(f"{e.get('finished', '')}  {e.get('task', ''):24} {e.get('status', ''):8} {e.get('role', ''):22}"
              f" @{e.get('base', '')[:10]}  {outs}{f' (+{more})' if more > 0 else ''}")
    if broken is not None:
        print(f"WARNING: chain broken at line {broken + 1}")


def cmd_deliver(a):
    """The lead's delivery of a finished file (e.g. an audited report) to a thread."""
    repo = Path(a.paper)
    sync(repo)
    if git(repo, "status", "--porcelain", "--", *[i.partition(":")[0] for i in a.items]).stdout.strip():
        die("deliver only what is committed and pushed — the file has local changes")
    base = git(repo, "rev-parse", "HEAD").stdout.strip()
    note = Notifier(repo, a.profile)
    failed = 0
    for name, data, mime, label in deliveries({"id": "delivery", "label": a.label}, repo, base, a.items):
        if data is None:
            print(f"not found: {label}"); failed += 1
            continue
        if len(data) > MAX_DELIVERY_BYTES:
            print(f"too large to attach: {name}"); failed += 1
            continue
        ok, detail = note.deliver(name, data, mime, a.thread, f"{label} (`{name}`, commit {base[:12]})")
        print(f"{name}: " + (f"delivered and verified, sha256 {detail}" if ok else f"NOT delivered — {detail}"))
        failed += not ok
    sys.exit(1 if failed else 0)


def cmd_setup(a):
    """Bind a paper to a Mattermost channel (id, or team/channel-name resolved via the API)."""
    repo = Path(a.paper)
    sync(repo)
    channel = a.channel
    if "/" in channel:
        creds = mm_creds(a.profile) or die("no MATTERMOST_URL/MATTERMOST_TOKEN for profile " + a.profile)
        team, name = channel.split("/", 1)
        channel = mm_api(creds, "GET", f"/teams/name/{team}/channels/name/{name}")["id"]
    conf = repo / TASKS / "board.conf"
    conf.parent.mkdir(exist_ok=True)
    wr(conf, f"mattermost_channel={channel}\n" + (f"mention={a.mention}\n" if a.mention else ""))
    publish(repo, [conf.relative_to(repo)], "board: mattermost channel")
    print(f"board.conf: channel {channel}" + (f", mention {a.mention}" if a.mention else ""))


def cmd_thread(a):
    """Start a round thread in the paper's channel; print its post id for `new --thread`."""
    repo = Path(a.paper)
    sync(repo)
    n = Notifier(repo, a.profile)
    if not n.channel:
        die("no .tasks/board.conf — run `setup` first")
    if not n.creds:
        die("no MATTERMOST_URL/MATTERMOST_TOKEN for profile " + a.profile)
    pid = n.post(f"#### {a.title}", a.root or "")
    if not pid:
        die("could not post to Mattermost (see error above)")
    print(a.root or pid)
    print(f"link: {n.creds[0]}/_redirect/pl/{pid}", file=sys.stderr)


def cmd_approve(a):
    """Record the user's approval of an experiment protocol (or an amendment to it)."""
    repo = Path(a.paper)
    sync(repo)
    d = repo / "experiments" / a.exp
    target = d / ("amendments.md" if a.amendment else "protocol.md")
    rel = target.relative_to(repo).as_posix()
    if not target.exists():
        die(f"{rel} does not exist")
    if git(repo, "status", "--porcelain", "--", rel).stdout.strip():
        die(f"{rel} has uncommitted changes — approve only what is on the remote")
    sha = git(repo, "log", "-1", "--format=%H", "--", rel).stdout.strip() or die(f"{rel} is not committed")
    blob = git(repo, "rev-parse", f"HEAD:{rel}").stdout.strip()
    what = f"amendment {a.amendment} in amendments.md" if a.amendment else "protocol.md"
    rec = d / "approval.md"
    head = "" if rec.exists() else f"# Approvals — {a.exp}\n\nWritten by research-lead only. The runner freezes protocol.md once this file exists.\n\n"
    wr(rec, f"{head}- {now()} — {what} approved by {a.by} (commit {sha[:12]}, blob {blob[:12]})"
       + (f" — {a.note}" if a.note else "") + "\n", append=True)
    publish(repo, [rec.relative_to(repo)], f"board: approve {a.exp} {what}")
    print(f"{a.exp}: {what} approved by {a.by}")


def cmd_publish(a):
    repo = Path(a.paper)
    sync(repo)
    print("pushed" if publish(repo, a.paths, a.message) else "nothing to commit")


# ---------- worker ----------

def snapshot(clone):
    """Export HEAD without .git and .tasks/ — what a blind reviewer is allowed to see."""
    work = Path(tempfile.mkdtemp(prefix="research-task-"))
    tar = sp.run(["git", "-C", str(clone), "archive", "HEAD"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(work, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(work)
    shutil.rmtree(work / TASKS, ignore_errors=True)
    return work


def exclude_locally(clone, name):
    excl = clone / ".git" / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    if name not in (rd(excl).splitlines() if excl.exists() else []):
        wr(excl, f"\n{name}\n", append=True)


def run_agent(a, cmd, work, env, note, tid, role, thread):
    """One hermes run with heartbeat posts and the task timeout. -> (out, err, code)."""
    t0 = time.time()
    proc = popen_group(cmd, cwd=work, env=env, stdout=sp.PIPE, stderr=sp.PIPE,
                       encoding="utf-8", errors="replace")
    while True:
        try:
            out, err = proc.communicate(timeout=a.heartbeat)
            return out, err, proc.returncode
        except sp.TimeoutExpired:
            if time.time() - t0 > a.task_timeout:
                kill_tree(proc)
                out, err = proc.communicate()
                return out, (err or "") + f"\ntimed out after {a.task_timeout}s", 124
            note.post(f":hourglass: **{tid}** still running ({fmt_age(time.time() - t0)}) — {role}", thread)


def deliveries(meta, src, base, items=None):
    """(name, bytes, mime, label) for each `deliver` entry that exists in src."""
    out = []
    for item in (items if items is not None else csv(meta.get("deliver"))):
        rel, _, kind = item.partition(":")
        f = src / rel
        if not f.is_file():
            out.append((rel, None, None, f"`{rel}` was not produced"))
            continue
        if kind == "docx":
            sys.path.insert(0, str(HERE))
            import report_docx
            text = rd(f)
            data = report_docx.build_docx(text, source=f"{rel}@{base[:12]}")
            out.append((Path(rel).stem + ".docx", data, report_docx.MIME, meta.get("label") or f"**{meta['id']}** — `{rel}` as Word"))
        else:
            mime = {"pdf": "application/pdf", "md": "text/markdown", "json": "application/json"}.get(
                f.suffix.lstrip(".").lower(), "application/octet-stream")
            data = f.read_bytes()
            out.append((f.name, data, mime, meta.get("label") or f"**{meta['id']}** — `{rel}`"))
    return out


def execute(a, clone, p, me):
    meta, body = load(p)
    tid, role = meta["id"], a.role
    profile = a.profile or role
    thread = meta.get("thread", "")
    note = Notifier(clone, profile)
    base = git(clone, "rev-parse", "HEAD").stdout.strip()
    work = snapshot(clone) if role in BLIND else clone
    if TEAM_CONTEXT.exists():
        shutil.copy2(TEAM_CONTEXT, work / ".hermes.md")  # outranks the paper's CLAUDE.md
        if work == clone:
            exclude_locally(clone, ".hermes.md")
    env, sens, gw = child_env(clone, profile)
    prompt = body.strip() + "\n" + SENSITIVE_NOTE.get(sens, "") + FOOTER.format(id=tid, role=role, cwd=work)
    # The prompt goes in a file outside the paper: no command-line length or quoting limits.
    qdir = TEAM_HOME / "run" / "prompts"
    qdir.mkdir(parents=True, exist_ok=True)
    qfile = qdir / f"{Path(clone).name}-{tid}-{os.getpid()}.md"
    wr(qfile, prompt)
    cmd = [a.hermes, "-p", profile, "chat", "-Q", "--query-file", str(qfile)]
    for s in dict.fromkeys(ROLE_SKILLS.get(role, []) + csv(meta.get("skills"))):
        cmd += ["-s", s]
    if a.yolo:
        cmd.append("--yolo")
    print(f"[{now()}] {tid}: running in {work} at {base[:12]}" + (f" (gateway: {sens})" if gw else ""), flush=True)
    t0 = time.time()

    refusal = None
    drift = profile_drift(profile)
    if drift:
        refusal = f"profile {profile} differs from the install: {', '.join(drift[:5])} — reinstall the team to restore it"
    elif sens in SENSITIVE_NOTE:
        # Never run a non-public paper on a model we cannot vouch for.
        refusal = gateway_probe(env, profile) if gw else (
            f"this paper is {sens}, and without the model gateway every model is a cloud one — "
            "set up the gateway with local models, or mark the paper public")
    if refusal:
        print(f"[{now()}] {tid}: not run — {refusal}", flush=True)
        out, err, code = f"Not run.\nSTATUS: blocked — {refusal}", "", 0
    else:
        for attempt in range(len(RETRY_DELAYS) + 1):
            out, err, code = run_agent(a, cmd, work, env, note, tid, role, thread)
            said = re.search(r"^\W*STATUS:\s*(done|blocked)\b", out, re.M | re.I)
            if code in (0, 124) or said or attempt == len(RETRY_DELAYS) or not TRANSIENT.search((err or "")[-4000:] + out[-2000:]):
                break
            wait = RETRY_DELAYS[attempt]
            note.post(f":repeat: **{tid}** hit a transient model error (exit {code}); retrying in {wait}s"
                      f" ({attempt + 1}/{len(RETRY_DELAYS)})", thread)
            print(f"[{now()}] {tid}: transient failure (exit {code}); retry in {wait}s", flush=True)
            time.sleep(wait)
            if work == clone:
                git(clone, "checkout", "-q", "--", ".")  # a retry starts from the claimed commit
                git(clone, "clean", "-fdq", "-e", ".hermes.md")

    qfile.unlink(missing_ok=True)
    touched = guard_frozen(clone) if work == clone else []

    marks = re.findall(r"^\W*STATUS:\s*(done|blocked)\b\W*(.*)$", out, re.M | re.I)
    said, reason = (marks[-1][0].lower(), marks[-1][1].strip()) if marks else (None, "")
    missing = [e for e in csv(meta.get("expects")) if not (work / e).exists()]
    if code == 0 and said == "done" and not missing:
        status = "done"
    elif said == "blocked":
        status = "blocked"
    else:
        status = "failed"
        reason = f"exit {code}" + (f"; missing {', '.join(missing)}" if missing else "") + ("" if said else "; no STATUS line")
    if touched:
        status = "failed"
        reason = f"edited frozen file(s) {', '.join(touched)} — restored; amendments go in amendments.md"

    if role in BLIND:  # bring the outputs back from the snapshot
        for rel in OUTPUTS[role]:
            src = work / rel
            if src.is_dir():
                shutil.copytree(src, clone / rel, dirs_exist_ok=True)
            elif src.is_file():
                shutil.copy2(src, clone / rel)

    report = out.strip()[-20000:] or "(no output)"
    if status == "failed" and err.strip():
        report += "\n\nstderr (tail):\n" + err.strip()[-3000:]
    body = (body.rstrip() + f"\n\n## Result — {status} ({me}, {now()}, at commit {base[:12]})\n\n"
            + (f"**{reason}**\n\n" if reason else "") + report + "\n")
    meta.update(status=status, base=base, updated=now())
    save(p, meta, body)
    rel_task = p.relative_to(clone).as_posix()
    staged = stage(clone, OUTPUTS[role] + [rel_task], excludes=BUILD_JUNK)
    outputs = {f: sha256_file(clone / f) for f in staged if f != rel_task and (clone / f).is_file()}
    broken = ledger_append(clone, {"task": tid, "role": role, "worker": me, "status": status, "base": base,
                                   "started": dt.datetime.fromtimestamp(t0, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   "finished": now(), "sensitivity": sens, "outputs": outputs})
    stage(clone, [LEDGER])
    commit_push(clone, f"{role}: {tid} {status}")
    print(f"[{now()}] {tid}: {status} {reason}", flush=True)
    if broken is not None:
        note.post(f":warning: **{Path(clone).name}**: the task ledger was rewritten before line {broken + 1}; "
                  f"recorded the break and continued. Check `git log -p {LEDGER}`.", thread, ping=True)

    took = fmt_age(time.time() - t0)
    metas = [e for e in csv(meta.get("expects")) if e.endswith("meta.md")]
    if status == "done" and metas:
        note.post(f":checkered_flag: **{tid} done — round checkpoint** (reviewed commit `{base[:12]}`). "
                  f"{checkpoint(clone / metas[0])}\n"
                  f"Read `{metas[0]}`, then tell research-lead what to do next.", thread, ping=True)
    elif status == "done" and meta.get("notify_done"):
        note.post(f":raising_hand: **{tid}** done — {headline(out)}\n{meta['notify_done']}", thread, ping=True)
    elif status == "done":
        note.post(f":white_check_mark: **{tid}** done in {took} — {headline(out)}", thread)
    else:
        icon = ":no_entry:" if status == "blocked" else ":x:"
        note.post(f"{icon} **{tid}** {status} after {took} — {reason or headline(out)}\n"
                  f"Needs you: ask research-lead to resolve and retry it.", thread, ping=True)

    if status == "done":
        for name, data, mime, label in deliveries(meta, clone, base):
            if data is None:
                note.post(f":warning: {label} — nothing to deliver", thread)
            elif len(data) > MAX_DELIVERY_BYTES:
                note.post(f":warning: {label} is {len(data) // 1048576} MB — too large to attach; it is in the repo", thread)
            else:
                ok, detail = note.deliver(name, data, mime, thread, label)
                if not ok:
                    note.post(f":warning: {label} could not be delivered: {detail}. The file is in the repo.", thread, ping=True)
    if role in BLIND:
        shutil.rmtree(work, ignore_errors=True)


def claim(clone, p, me):
    meta, body = load(p)
    meta.update(status="running", claimed_by=me, updated=now())
    save(p, meta, body)
    try:
        git(clone, "add", p.relative_to(clone).as_posix())
        git(clone, "commit", "-q", "-m", f"board: claim {meta['id']}")
        if git(clone, "push", "-q", check=False).returncode == 0:
            return True
    except RuntimeError:
        pass
    reset_to_remote(clone)  # another worker claimed first, or the board moved
    return False


def remotes(a):
    urls = list(a.remotes)
    if a.papers_file and Path(a.papers_file).is_file():
        urls += [l.strip() for l in rd(a.papers_file).splitlines() if l.strip() and not l.startswith("#")]
    return list(dict.fromkeys(urls))


def cmd_run(a):
    if a.role not in OUTPUTS:
        die(f"--role must be one of {', '.join(OUTPUTS)} (the lead is interactive, not a runner)")
    a.hermes = a.hermes or os.environ.get("RESEARCH_TEAM_HERMES") or shutil.which("hermes")
    if not a.hermes:
        die("hermes not found — pass --hermes or set RESEARCH_TEAM_HERMES")
    if not a.papers_file and not a.remotes and (TEAM_HOME / "papers").is_file():
        a.papers_file = str(TEAM_HOME / "papers")
    if "RESEARCH_GATEWAY_API_KEY" in profile_env(a.profile or a.role):
        die(f"remove RESEARCH_GATEWAY_API_KEY from the {a.profile or a.role} profile's .env — the runner sets it per "
            "task from each paper's sensitivity (keep only RESEARCH_GATEWAY_SECRET there)")
    me = f"{socket.gethostname()}/{a.role}/slot{a.slot}"
    root = Path(a.work or TEAM_HOME / "work" / a.role / f"slot-{a.slot}")
    root.mkdir(parents=True, exist_ok=True)
    clones, first, waits = {}, set(), {}  # waits: task id -> (last post time, lost already pinged)
    print(f"research_board runner {me}: every {a.interval}s"
          + (f", papers from {a.papers_file}" if a.papers_file else ""), flush=True)
    while True:
        for url in remotes(a):
            if url in clones:
                continue
            c = root / repo_name(url)
            try:
                if not c.exists():
                    git(root, "clone", "-q", "-c", "core.autocrlf=false", url, str(c))
                git_identity(c, a.role)
                clones[url] = c
                print(f"[{now()}] serving {c.name}", flush=True)
            except RuntimeError as e:
                print(f"[{now()}] {url}: {e}", file=sys.stderr, flush=True)
        did = False
        for url, c in clones.items():
            try:
                reset_to_remote(c)
                board = tasks(c)
                if url not in first:  # a crash left our own claims dangling: release them
                    first.add(url)
                    for tid, (p, m, b) in board.items():
                        if m.get("status") == "running" and m.get("claimed_by") == me:
                            m.update(status="ready", claimed_by="", updated=now())
                            save(p, m, b)
                            publish(c, [p.relative_to(c).as_posix()], f"board: release stale claim {tid}")
                    board = tasks(c)
                for tid, (p, m, _) in board.items():
                    if m.get("assignee") == a.role and m.get("status") == "ready" and not waiting_on(m, board):
                        ok, why, lost = condition_met(c, m.get("ready_when", ""))
                        if not ok:
                            last, pinged = waits.get(tid, (0, False))
                            if why.startswith("no jobs"):
                                continue  # another device launched them; it will collect
                            if time.time() - last >= a.heartbeat or (lost and not pinged):
                                Notifier(c, a.profile or a.role).post(
                                    f":hourglass: **{tid}** waiting — {why}" + ("\nSome jobs were lost (no process, no DONE)." if lost else ""),
                                    m.get("thread", ""), ping=lost and not pinged)
                                waits[tid] = (time.time(), pinged or lost)
                            continue
                        waits.pop(tid, None)
                        if claim(c, p, me):
                            Notifier(c, a.profile or a.role).post(
                                f":arrow_forward: **{tid}** picked up by {a.role} ({me})", m.get("thread", ""))
                            execute(a, c, p, me)
                            did = True
                        break
            except Exception as e:  # keep the loop alive; the board shows what happened
                print(f"[{now()}] {c.name}: {e}", file=sys.stderr, flush=True)
        if a.status_file:
            try:
                wr(a.status_file, json.dumps({"pid": os.getpid(), "role": a.role, "slot": a.slot, "updated": now(),
                                              "papers": sorted(c.name for c in clones.values())}))
            except OSError:
                pass
        if a.once and not did:
            return
        if not did:
            time.sleep(a.interval)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="give a paper folder its task board and register it for the runners")
    s.add_argument("folder"); s.add_argument("--boards", help="where bare board repos live (default <team home>/boards)")
    s.add_argument("--papers-file", help="the runners' papers list (default <team home>/papers)")
    s.add_argument("--force", action="store_true", help="also for a folder without CLAUDE.md")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("new", help="create a task (idempotent on --id)")
    s.add_argument("paper"); s.add_argument("--id", required=True); s.add_argument("--assignee", required=True)
    s.add_argument("--after", help="comma-separated task ids that must be done first")
    s.add_argument("--expects", help="comma-separated paths the task must produce")
    s.add_argument("--skills", help="comma-separated skills to preload")
    s.add_argument("--thread", help="Mattermost post id of the round thread (from `thread`)")
    s.add_argument("--ready-when", help="built-in wait condition, e.g. 'jobs-done x1'")
    s.add_argument("--notify-done", help="text posted with an @mention when the task is done (e.g. an approval request)")
    s.add_argument("--deliver", help="files to attach to the thread when done: <path> or <report.md>:docx, comma-separated")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--body"); g.add_argument("--body-file", help="file with the prompt, or - for stdin")
    s.set_defaults(fn=cmd_new)

    s = sub.add_parser("list", help="tasks and their status"); s.add_argument("paper")
    s.add_argument("--no-sync", action="store_true"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("show", help="print one task with its result"); s.add_argument("paper"); s.add_argument("id")
    s.set_defaults(fn=cmd_show)
    s = sub.add_parser("wait", help="poll until the tasks finish or --timeout; exit 0 only if all done")
    s.add_argument("paper"); s.add_argument("ids", nargs="+")
    s.add_argument("--timeout", type=int, default=150, help="seconds (keep under your terminal tool timeout)")
    s.add_argument("--poll", type=int, default=20); s.set_defaults(fn=cmd_wait)
    s = sub.add_parser("edit", help="change after/status or append a note to a task")
    s.add_argument("paper"); s.add_argument("id"); s.add_argument("--after"); s.add_argument("--append")
    s.add_argument("--status", choices=["ready", "blocked", "failed", "done"]); s.set_defaults(fn=cmd_edit)
    s = sub.add_parser("ledger", help="the append-only record of finished tasks")
    s.add_argument("paper"); s.add_argument("--verify", action="store_true", help="only check the hash chain")
    s.add_argument("--no-sync", action="store_true"); s.set_defaults(fn=cmd_ledger)
    s = sub.add_parser("deliver", help="attach committed files to a thread, verified by SHA-256 after upload")
    s.add_argument("paper"); s.add_argument("items", nargs="+", help="<path> or <report.md>:docx")
    s.add_argument("--thread", default="", help="post id of the thread"); s.add_argument("--label", default="")
    s.add_argument("--profile", default="research-lead"); s.set_defaults(fn=cmd_deliver)
    s = sub.add_parser("setup", help="bind the paper to a Mattermost channel for progress posts")
    s.add_argument("paper"); s.add_argument("--channel", required=True, help="channel id, or team/channel-name")
    s.add_argument("--mention", help="who to @mention on blocks and checkpoints, e.g. @paul")
    s.add_argument("--profile", default="research-lead", help="hermes profile whose .env holds the bot token")
    s.set_defaults(fn=cmd_setup)
    s = sub.add_parser("thread", help="post a round's root message; prints its id for `new --thread`")
    s.add_argument("paper"); s.add_argument("title")
    s.add_argument("--root", help="post inside this existing thread instead (e.g. the user's request) and print its id")
    s.add_argument("--profile", default="research-lead"); s.set_defaults(fn=cmd_thread)
    s = sub.add_parser("approve", help="record the user's approval of an experiment protocol or amendment")
    s.add_argument("paper"); s.add_argument("exp", help="experiment id, e.g. x1")
    s.add_argument("--by", required=True, help="who approved, e.g. @paul")
    s.add_argument("--amendment", type=int, help="approve amendment N in amendments.md instead of the protocol")
    s.add_argument("--note"); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("publish", help="commit and push the lead's own files")
    s.add_argument("paper"); s.add_argument("paths", nargs="+"); s.add_argument("-m", "--message", required=True)
    s.set_defaults(fn=cmd_publish)

    s = sub.add_parser("run", help="worker loop for one role on this device")
    s.add_argument("remotes", nargs="*", help="git URLs of the paper repos to serve")
    s.add_argument("--papers-file", help="file with one git URL per line, re-read on every pass "
                                         "(default <team home>/papers when no URLs are given)")
    s.add_argument("--role", required=True); s.add_argument("--profile", help="hermes profile (default: the role)")
    s.add_argument("--hermes", help="hermes command (default $RESEARCH_TEAM_HERMES, else hermes on PATH)")
    s.add_argument("--slot", type=int, default=1, help="run several slots for parallel tasks")
    s.add_argument("--work", help="clone dir (default <team home>/work/<role>/slot-<n>)")
    s.add_argument("--interval", type=int, default=60)
    s.add_argument("--task-timeout", type=int, default=3 * 3600)
    s.add_argument("--heartbeat", type=int, default=1800, help="seconds between 'still running' posts")
    s.add_argument("--status-file", help="write a small JSON heartbeat here after every pass")
    s.add_argument("--yolo", action="store_true", help="pass --yolo to hermes (skip dangerous-command approvals)")
    s.add_argument("--once", action="store_true", help="exit when no task is ready")
    s.set_defaults(fn=cmd_run)

    a = ap.parse_args()
    try:
        a.fn(a)
    except RuntimeError as e:
        die(str(e))


if __name__ == "__main__":
    main()
