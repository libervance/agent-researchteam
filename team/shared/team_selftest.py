#!/usr/bin/env python3
"""team_selftest — a live check that the installed team works end to end, run by the installer.

    team_selftest.py --workspace W --channel CHANNEL_ID --hermes HERMES [--timeout 1500]

Makes a small folder `_selftest-<time>` in the workspace, gives it a board, and puts one
small real task on it for each runner role, through the running team service and the real
models and bots: the librarian finds one real paper, the reviewer checks that citation
(blind), the lead (authorship) and the experimenter each write one file. When they are done, the
lead answers one question about the board through its own profile and skills, the
reviewer's note is delivered to the thread and verified, and the ledger chain is checked.
Prints one JSON object; exit 0 only if every check passed.

Nothing here is a mock: it spends model calls, and it only passes on a PC where the bots,
models, web search and runners all work.
"""
import argparse
import importlib.util
import json
import os
import subprocess as sp
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOARD = HERE / "research_board.py"
# The installer sets PYTHONSAFEPATH=1. Load this verified sibling explicitly;
# do not enable imports from the user's workspace or weaken that environment.
_board_spec = importlib.util.spec_from_file_location("_hermes_selftest_board", BOARD)
rb = importlib.util.module_from_spec(_board_spec)
_board_spec.loader.exec_module(rb)
RUNNER_ROLES = ["research-librarian", "research-reviewer", "research-lead", "research-experimenter"]

CLAUDE = """# Installation check

Created by the installer's live test. Not a real paper — answer the tasks briefly.

- **Sensitivity:** public
"""

TASKS = [
    ("t-librarian", "research-librarian", "notes/selftest/sources.md", "", "",
     "Installation check (keep it short). Use the arXiv API to find one real paper on "
     "retrieval-augmented generation. Write `notes/selftest/sources.md` with exactly one line: "
     "authors, title, year, and its arXiv ID."),
    ("t-reviewer", "research-reviewer", "reviews/selftest/check.md", "t-librarian", "",
     "Installation check (keep it short). Open the arXiv page of the paper in "
     "`notes/selftest/sources.md` and check that the title and year match. Write "
     "`reviews/selftest/check.md` with `Verdict: pass` if they match, else `Verdict: revise` and why."),
    ("t-author", "research-lead", "paper/sections/selftest.tex", "", "",
     "Installation check (keep it short; no build needed). Write `paper/sections/selftest.tex` "
     "containing one LaTeX sentence that says this is a writing check. Do not claim installation has passed."),
    ("t-experimenter", "research-experimenter", "evidence/selftest/env.json", "", "",
     "Installation check (keep it short; no protocol, no jobs). Using your terminal, run "
     "`git --version`, and write `evidence/selftest/env.json` with keys `git` (its output) and "
     "`checked_at` (current UTC time)."),
]


def board(*args, cwd, check=True):
    r = sp.run([sys.executable, str(BOARD), *args], cwd=cwd, capture_output=True,
               encoding="utf-8", errors="replace", timeout=120)
    if check and r.returncode:
        raise RuntimeError(f"research_board {args[0]}: {(r.stderr or r.stdout).strip()[-500:]}")
    return r


def status_of(folder, ws):
    out = board("list", str(folder), cwd=ws).stdout
    return {line.split()[0]: line.split()[1] for line in out.splitlines() if line.strip() and not line.startswith("(")}


def runner_errors(folder, home):
    """Only errors for this test board, never an unrelated project or old test."""
    remote = rb.git(folder, "remote", "get-url", "origin").stdout.strip()
    errors = []
    for path in (home / "run").glob("research-*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - path.stat().st_mtime > 180:
                continue
            for error in state.get("errors", {}).values():
                if error.get("remote") == remote:
                    errors.append(f"{state.get('role')}: {error['error']}")
        except (OSError, ValueError, TypeError, KeyError):
            continue  # a runner may be replacing its heartbeat
    return errors


def terminal_failure(folder):
    for tid, (_, meta, _) in rb.tasks(folder).items():
        status = meta.get("status")
        if rb.can_resume(meta, status, meta.get("stop_reason", ""), installation=True):
            continue  # the runner publishes the failed attempt before requeuing it
        if status in ("blocked", "failed") or (status == "partial" and
                (meta.get("resume_policy") != "auto" or
                 int(meta.get("attempt") or 0) >= int(meta.get("max_attempts") or 1))):
            return f"{tid}: {status} — {meta.get('stop_reason', '')}"
    return ""


def progress(message):
    print("SELFTEST_PROGRESS " + message, flush=True)


def save_check(result, phase, outcome="running"):
    """Persist each phase separately from installer evidence, including abrupt exits."""
    record = {**result, "phase": phase, "outcome": outcome, "updated": rb.now()}
    directory = rb.TEAM_HOME / "checks"
    directory.mkdir(parents=True, exist_ok=True)
    rb.write_state(directory / (Path(result["folder"]).name + ".json"), record)
    rb.write_state(rb.TEAM_HOME / "installation-check.json", record)


STATUS_KO = {"ready": "대기", "running": "진행 중", "done": "완료", "failed": "재시도 또는 원인 확인 중",
             "partial": "저장된 결과에서 이어서 확인 중", "blocked": "진행 불가", "missing": "준비 중"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True); ap.add_argument("--channel", required=True)
    ap.add_argument("--hermes", required=True); ap.add_argument("--mention", default="")
    ap.add_argument("--timeout", type=int, default=1500)
    a = ap.parse_args()
    ws = Path(a.workspace)
    folder = ws / time.strftime("_selftest-%Y%m%d-%H%M%S")
    result = {"passed": False, "live": True, "folder": str(folder), "roles": {}, "lead": None,
              "delivered": False, "ledger_intact": False, "dashboard_ready": False, "review_passed": False, "thread": None, "error": None}
    note = None
    def phase(message):
        progress(message)
        save_check(result, message)
        if note and result["thread"]:
            note.progress("installation-summary", message + "\n[이번 설치 확인 보드](" + rb.dashboard_url(folder) + ")", result["thread"])
    try:
        save_check(result, "네 역할의 확인 작업을 준비하고 있습니다.")
        for d in ("notes", "reviews", "paper/sections", "evidence"):
            (folder / d).mkdir(parents=True, exist_ok=True)
            (folder / d / ".gitkeep").write_text("", encoding="utf-8")
        (folder / "CLAUDE.md").write_text(CLAUDE, encoding="utf-8", newline="\n")
        board("init", str(folder), cwd=ws)
        board("setup", str(folder), "--channel", a.channel, *(["--mention", a.mention] if a.mention else []), cwd=ws)
        thread = board("thread", str(folder), "연구팀 설치 확인을 시작합니다. 문헌 검색·원고 작성·실행 환경·독립 심사를 확인한 뒤, 총괄의 보드 조회와 결과 전달까지 검증합니다.\n"
                       "자동 재시도 중에는 사용자 조치가 필요하지 않습니다. 최종 통과 여부는 별도로 알려드리겠습니다.\n"
                       "[이번 설치 확인 보드](" + rb.dashboard_url(folder) + ")", cwd=ws).stdout.split()[0]
        result["thread"] = thread
        note = rb.Notifier(folder, "research-lead")
        for tid, role, expects, after, deliver, body in TASKS:
            args = ["new", str(folder), "--id", tid, "--assignee", role, "--expects", expects, "--thread", thread, "--body", body,
                    "--gate", "auto", "--resume-policy", "auto", "--max-attempts", "2"]
            args += ["--after", after] if after else []
            args += ["--deliver", deliver] if deliver else []
            board(*args, cwd=ws)
        deadline = time.time() + a.timeout
        previous = None
        while True:
            st = status_of(folder, ws)
            result["roles"] = {role: st.get(tid, "missing") for tid, role, *_ in TASKS}
            if result["roles"] != previous:
                phase(" · ".join(f"{rb.CHECK_LABELS[tid]}: {STATUS_KO.get(st.get(tid, 'missing'), '확인 중')}" for tid, *_ in TASKS))
                previous = dict(result["roles"])
            failure = terminal_failure(folder)
            if failure:
                raise RuntimeError(f"worker stopped: {failure}")
            errors = runner_errors(folder, rb.TEAM_HOME)
            if errors:
                raise RuntimeError("board publication/runner error; saved outputs retained: " + "; ".join(errors))
            if all(s == "done" for s in result["roles"].values()) or time.time() > deadline:
                break
            time.sleep(20)
        if not all(s == "done" for s in result["roles"].values()):
            bad = {r: s for r, s in result["roles"].items() if s != "done"}
            raise RuntimeError(f"roles not done: {bad}" + (" (timed out)" if time.time() > deadline else ""))
        # The lead: its own profile, its skill placeholders and its terminal, one question.
        result["review_passed"] = bool(rb.re.search(r"^\s*Verdict:\s*pass\s*$", (folder / "reviews/selftest/check.md").read_text(encoding="utf-8"), rb.re.M | rb.re.I))
        if not result["review_passed"]:
            raise RuntimeError("독립 심사에서 서지 정보가 확인되지 않았습니다. 심사 결과를 확인하세요.")
        phase("네 역할의 결과 저장과 독립 심사가 끝났습니다. 아직 설치 통과 전입니다. 총괄이 보드를 조회할 수 있는지 확인합니다(최대 15분).")
        q = folder.parent / ".scratch" / "selftest-lead.md"
        q.parent.mkdir(exist_ok=True)
        q.write_text(f"Installation check. Using your board command, list the tasks of `{folder.name}` and "
                     "reply with one line: how many tasks are done. End with `STATUS: done`.", encoding="utf-8")
        r = sp.run([a.hermes, "-p", "research-lead", "chat", "-Q", "--query-file", str(q)], cwd=ws,
                   capture_output=True, encoding="utf-8", errors="replace", timeout=900)
        result["lead"] = "done" if r.returncode == 0 and rb.completion_marker(r.stdout)[0] == "done" and "4" in r.stdout else \
            f"failed (exit {r.returncode}): {(r.stdout + r.stderr).strip()[-300:]}"
        if result["lead"] != "done":
            raise RuntimeError(f"research-lead: {result['lead']}")
        phase("총괄의 보드 조회를 확인했습니다. 작업 기록과 Mattermost 첨부 파일이 저장된 결과와 일치하는지 확인합니다.")
        result["ledger_intact"] = board("ledger", str(folder), "--verify", cwd=ws, check=False).returncode == 0
        # Deliver once, as the lead; download and verify the uploaded bytes.
        dl = board("deliver", str(folder), "reviews/selftest/check.md", "--thread", thread,
                   "--label", "설치 확인의 독립 심사 결과", cwd=ws, check=False)
        result["delivered"] = dl.returncode == 0
        phase("설치 확인 보드에 네 역할의 완료 결과가 표시되는지 확인합니다.")
        dashboard = json.loads((rb.TEAM_HOME / "dashboard.json").read_text(encoding="utf-8"))
        url = dashboard.get("url", "")
        if not rb.re.fullmatch(r"http://127\.0\.0\.1:[0-9]+/", url):
            raise RuntimeError("Graphical board URL is unavailable")
        with urllib.request.urlopen(url + "api/projects?project=" + urllib.parse.quote(folder.name), timeout=30) as response:
            snapshot = json.load(response)
        result["dashboard_ready"] = any(p.get("name") == folder.name and len(p.get("tasks", [])) == 4
            and all(t.get("status") == "done" for t in p["tasks"]) for p in snapshot.get("projects", []))
        result["passed"] = result["ledger_intact"] and result["delivered"] and result["dashboard_ready"]
        if not result["passed"]:
            result["error"] = ("ledger chain broken" if not result["ledger_intact"] else
                               "graphical board verification failed" if not result["dashboard_ready"] else
                               f"delivery failed: {dl.stdout.strip()[-300:]}")
    except Exception as e:
        result["error"] = str(e)[:800]
    message = ("설치 확인을 통과했습니다. 네 역할의 작업, 독립 심사, 총괄의 보드 조회, 작업 기록, 결과 전달을 모두 확인했습니다."
               if result["passed"] else "설치 확인을 완료하지 못했습니다. 작업 결과와 실패 원인은 이번 설치 확인 보드에 보존했습니다. "
               "일부 작업이 나중에 완료되더라도 설치 통과를 뜻하지는 않습니다. 원인을 확인한 뒤 설치기에서 같은 연구팀으로 다시 시도하세요.")
    save_check(result, message, "passed" if result["passed"] else "incomplete")
    progress(message)
    if note and result["thread"]:
        note.progress("installation-summary", message + "\n[이번 설치 확인 보드](" + rb.dashboard_url(folder) + ")", result["thread"])
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
