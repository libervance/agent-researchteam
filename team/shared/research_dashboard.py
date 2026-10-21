#!/usr/bin/env python3
"""Local read-only research board. Reads committed Git snapshots, never edits agent worktrees."""
import argparse
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import threading
import time
import urllib.parse

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("dashboard_board", HERE / "research_board.py")
rb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rb)
MAX_BYTES = 20 * 1024 * 1024
ASSETS = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css"}


def git(repo, *args, binary=False, required=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=20)
    if required and result.returncode:
        raise RuntimeError("Git snapshot unavailable; check the team service and project repository.")
    return result.stdout if binary else result.stdout.decode("utf-8", "replace").strip()


def output_allowed(path):
    p = PurePosixPath(path)
    return (not p.is_absolute() and ".." not in p.parts and "\\" not in path and ":" not in path
            and bool(p.parts) and not any(x.startswith(".") for x in p.parts)
            and (p.parts[0] in {"paper", "notes", "reviews", "evidence", "experiments"}
                 or path in {"claims.md", "outline.md", "CLAUDE.md", "REVIEW_RUBRIC.md"}))


class Board:
    def __init__(self, workspace, home):
        self.workspace, self.home = Path(workspace).resolve(), Path(home).resolve()
        self.lock = threading.Lock()
        self.cached, self.cached_at, self.cached_key = None, 0, None

    def projects(self):
        found = {}
        for path in self.workspace.iterdir():
            if not path.is_dir() or path.is_symlink() or not path.resolve().is_relative_to(self.workspace) or not (path / ".git").exists():
                continue
            key = hashlib.sha256(str(path).encode()).hexdigest()[:20]
            found[key] = path
        return found

    def source(self, project):
        remote = git(project, "remote", "get-url", "origin", required=False)
        local = Path(remote)
        if not local.is_absolute():
            local = project / local
        if remote and local.is_dir() and git(local, "rev-parse", "--is-bare-repository", required=False) == "true":
            return local, git(local, "rev-parse", "HEAD"), "Shared local board"
        # For external remotes show the last synced local snapshot, without background
        # network requests or changing a working tree. The UI labels this explicitly.
        return project, git(project, "rev-parse", "HEAD"), "Local snapshot; external remote is not refreshed by this page"

    def blob(self, repo, commit, path):
        size = git(repo, "cat-file", "-s", f"{commit}:{path}", required=False)
        if not size.isdigit() or int(size) > MAX_BYTES:
            raise ValueError("Output is missing or exceeds the 20 MB preview/download limit.")
        return git(repo, "show", f"{commit}:{path}", binary=True)

    def project(self, key, project):
        repo, commit, source = self.source(project)
        tree = git(repo, "-c", "core.quotepath=false", "ls-tree", "-r", commit).splitlines()
        objects = {line.split("\t", 1)[1]: line.split("\t", 1)[0].split()[2] for line in tree if "\t" in line}
        files = list(objects)
        ledger = []
        if rb.LEDGER in files:
            for line in self.blob(repo, commit, rb.LEDGER).decode("utf-8", "replace").splitlines():
                try:
                    ledger.append(json.loads(line))
                except ValueError:
                    pass
        latest = {entry.get("task"): entry for entry in ledger}
        tasks = []
        for path in files:
            if not re.fullmatch(r"\.tasks/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.md", path):
                continue
            raw = self.blob(repo, commit, path)
            match = re.match(r"---\n(.*?)\n---\n?(.*)", raw.decode("utf-8", "replace").replace("\r\n", "\n"), re.S)
            if not match:
                continue
            meta = dict((k.strip(), v.strip()) for k, _, v in (line.partition(":") for line in match[1].splitlines()))
            tid = meta.get("id", PurePosixPath(path).stem)
            entry = latest.get(tid, {})
            expected = rb.csv(meta.get("expects"))
            names = list(dict.fromkeys(expected + list(entry.get("outputs", {}))))
            outputs = [{"path": name, "available": name in files} for name in names if output_allowed(name)]
            parts = [hashlib.sha256(raw).hexdigest()]
            for name in names:
                if name in files:
                    parts.append(name + ":" + objects[name])
            token = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
            approval = {}
            approval_path = f".tasks/approvals/{tid}.json"
            if approval_path in files:
                try:
                    approval = json.loads(self.blob(repo, commit, approval_path))
                except ValueError:
                    pass
            waiting = meta.get("status") == "done" and meta.get("gate") == "human" and (approval.get("token") != token or not approval.get("post_id"))
            tasks.append({"id": tid, "assignee": rb.effective_assignee(meta.get("assignee", "")),
                          "original_assignee": meta.get("assignee"), "status": meta.get("status", "unknown"),
                          "column": "approval" if waiting else meta.get("status", "unknown"),
                          "after": rb.csv(meta.get("after")), "updated": meta.get("updated"),
                          "claimed_by": meta.get("claimed_by"), "attempt": meta.get("attempt", "0"),
                          "gate": meta.get("gate"), "report": match[2], "outputs": outputs,
                          "approval_command": f"approve {tid} {token}" if waiting else "",
                          "thread": meta.get("thread", "")})
        return {"id": key, "name": project.name, "path": str(project), "commit": commit,
                "source": source, "test": project.name.startswith("_selftest-"), "tasks": tasks,
                "paused": any(t["column"] == "approval" for t in tasks), "error": None}

    def snapshot(self, project_name=None, include_tests=False):
        with self.lock:
            key = (project_name, include_tests)
            if self.cached_key == key and self.cached is not None and time.monotonic() - self.cached_at < 3:
                return self.cached
            projects = []
            for project_id, path in self.projects().items():
                if project_name and path.name != project_name:
                    continue
                if not project_name and not include_tests and path.name.startswith("_selftest-"):
                    continue
                try:
                    projects.append(self.project(project_id, path))
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    projects.append({"id": project_id, "name": path.name, "tasks": [], "test": path.name.startswith("_selftest-"),
                                     "error": str(exc), "paused": False})
            state = {}
            try:
                raw = json.loads((self.home / "service-status.json").read_text(encoding="utf-8"))
                state = {"updated": raw.get("updated"), "stopped": raw.get("stopped", False),
                         "children": [{k: c.get(k) for k in ("name", "state", "restarts")} for c in raw.get("children", [])]}
            except (OSError, ValueError):
                pass
            issues = []
            for status in (self.home / "run").glob("research-*.json"):
                try:
                    runner = json.loads(status.read_text(encoding="utf-8"))
                    issues.extend({"role": runner.get("role", "worker"), "project": name} for name in runner.get("errors", {}))
                except (OSError, ValueError):
                    pass
            state["issues"] = issues
            self.cached = {"projects": projects, "service": state, "updated": rb.now(), "workspace": str(self.workspace)}
            self.cached_at = time.monotonic()
            self.cached_key = key
            return self.cached

    def output(self, key, path, commit):
        if not output_allowed(path) or not re.fullmatch(r"[a-f0-9]{40,64}", commit):
            raise ValueError("Output path rejected.")
        project = self.projects().get(key)
        if project is None:
            raise ValueError("Project not found.")
        repo, current, _ = self.source(project)
        if current != commit:
            raise ValueError("The board changed. Refresh and select the current output.")
        return self.blob(repo, commit, path)


def handler(board):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, data, mime):
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            port = self.server.server_port
            if (self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}")
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                return self.reply(403, b"Local access only", "text/plain")
            url = urllib.parse.urlsplit(self.path)
            try:
                if url.path in ASSETS:
                    file = HERE / "board-ui" / ASSETS[url.path]
                    mime = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[file.suffix]
                    return self.reply(200, file.read_bytes(), mime + "; charset=utf-8")
                if url.path == "/api/projects":
                    query = urllib.parse.parse_qs(url.query)
                    return self.reply(200, json.dumps(board.snapshot(query.get("project", [None])[0], query.get("tests") == ["1"]), ensure_ascii=False).encode(), "application/json; charset=utf-8")
                if url.path == "/api/output":
                    query = urllib.parse.parse_qs(url.query)
                    path = query["path"][0]
                    data = board.output(query["project"][0], path, query["commit"][0])
                    mime = "application/pdf" if path.endswith(".pdf") else "text/plain; charset=utf-8"
                    return self.reply(200, data, mime)
                self.reply(404, b"Not found", "text/plain")
            except (KeyError, ValueError, OSError, RuntimeError, subprocess.TimeoutExpired):
                self.reply(409, b"Output unavailable or board changed. Refresh and try again.", "text/plain")
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--home", required=True)
    args = parser.parse_args()
    board = Board(args.workspace, args.home)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler(board))
    url = f"http://127.0.0.1:{server.server_port}/"
    record = board.home / "dashboard.json"
    rb.write_state(record, {"url": url, "pid": os.getpid(), "started": rb.now()})
    # Stable double-click entry point; the port is chosen afresh on each service start.
    shortcut = board.workspace / "Research Board.url"
    shortcut.write_text("[InternetShortcut]\nURL=" + url + "\n", encoding="utf-8")
    print("Research board: " + url, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
