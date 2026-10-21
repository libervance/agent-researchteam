"""Four-role migration, real approval gating and the read-only browser API."""
import http.server
import importlib.util
import json
import threading
import urllib.error
import urllib.request
from test_research_board import Base, MockMattermost, ROOT, git, _load_board

spec = importlib.util.spec_from_file_location("dashboard", ROOT / "team/shared/research_dashboard.py")
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


class DashboardTests(Base):
    def checkpoint(self):
        self.board("new", str(self.paper), "--id", "draft", "--assignee", "research-lead",
                   "--body", "WRITE-PAPER", "--expects", "paper/main.tex")
        self.run_role("research-lead")
        self.state("draft")
        rb = _load_board()
        meta = rb.load(self.paper / ".tasks/draft.md")[0]
        return rb, meta

    def test_default_gate_blocks_unrelated_tasks_until_verified_human_approval(self):
        (self.paper / ".tasks/project.json").write_text("{}")
        git("add", ".tasks/project.json", cwd=self.paper)
        git("commit", "-qm", "managed project", cwd=self.paper)
        git("push", "-q", cwd=self.paper)
        rb, meta = self.checkpoint()
        self.assertEqual("human", meta["gate"])
        self.assertTrue(meta["thread"])
        self.task("next", "research-librarian", "REPORT")
        self.run_role("research-librarian")
        self.assertIn("status: ready", self.state("next"))
        token = rb.approval_token(self.paper, meta)
        post = {"id": "approval-post", "user_id": "human", "channel_id": "c" * 26,
                "root_id": meta["thread"], "message": f"approve draft {token}"}
        for change in ({"user_id": "bot"}, {"root_id": "wrong"}, {"message": "OK"},
                       {"channel_id": "wrong"}, {"delete_at": 1}, {"message": "approve draft stale"}):
            self.assertFalse(rb.accept_approval(self.paper, meta, {**post, **change}, "human", "c" * 26))
        rejected = self.board("edit", str(self.paper), "draft", "--gate", "auto", check=False)
        self.assertNotEqual(0, rejected.returncode)
        before_approval = len(self.calls())
        MockMattermost.posts.append(post)
        self.board("coordinate", "--once", "--hermes", str(self.hermes))
        self.state("draft")
        self.assertFalse(rb.needs_approval(self.paper, meta))
        self.assertEqual(before_approval + 1, len(self.calls()), "approval and completion must not invoke lead twice")
        before = len(self.calls())
        self.board("coordinate", "--once", "--hermes", str(self.hermes))
        self.assertEqual(before, len(self.calls()), "approval continuation must not repeat")
        self.run_role("research-librarian")
        self.assertIn("status: done", self.state("next"))
        # A revised result cannot inherit the prior acceptance.
        (self.paper / "paper/main.tex").write_text("revised", encoding="utf-8")
        git("add", "paper/main.tex", cwd=self.paper)
        git("commit", "-qm", "revised published result", cwd=self.paper)
        self.assertTrue(rb.needs_approval(self.paper, meta))

    def test_checkpoint_revision_can_run_while_another_checkpoint_waits(self):
        rb, meta = self.checkpoint()
        self.task("other", "research-reviewer", "REVIEW", "--gate", "human")
        # Model two results that completed concurrently before the project paused.
        path = self.paper / ".tasks/other.md"
        other, body = rb.load(path)
        other["status"] = "done"
        rb.save(path, other, body)
        git("add", ".tasks/other.md", cwd=self.paper)
        git("commit", "-qm", "concurrent checkpoint", cwd=self.paper)
        git("push", "-q", cwd=self.paper)
        self.board("edit", str(self.paper), "draft", "--append", "Revise the wording", "--status", "ready")
        self.run_role("research-lead")
        self.assertIn("status: done", self.state("draft"))
        self.assertEqual(2, len(self.calls()))
        self.assertEqual(2, len(rb.pending_approvals(self.paper)))

    def test_historical_writer_task_is_processed_by_lead(self):
        self.task("old", "research-lead", "WRITE-PAPER")
        path = self.paper / ".tasks/old.md"
        path.write_text(path.read_text().replace("assignee: research-lead", "assignee: research-writer"))
        git("add", ".tasks/old.md", cwd=self.paper)
        git("commit", "-qm", "historical writer task", cwd=self.paper)
        git("push", "-q", cwd=self.paper)
        self.run_role("research-lead")
        self.assertIn("status: done", self.state("old"))
        self.assertEqual("research-lead", self.calls()[0]["profile"])

    def test_dashboard_reads_shared_snapshot_and_secure_output_api(self):
        # Do not pull the workspace clone after execution: UI must see worker commits.
        self.board("new", str(self.paper), "--id", "draft", "--assignee", "research-lead",
                   "--body", "WRITE-PAPER", "--expects", "paper/main.tex")
        self.run_role("research-lead")
        board = dashboard.Board(self.ws, self.home)
        project = board.snapshot()["projects"][0]
        task = project["tasks"][0]
        self.assertEqual("approval", task["column"])
        self.assertEqual("research-lead", task["assignee"])
        self.assertTrue(task["outputs"][0]["available"])
        rb = _load_board()
        self.state("draft")
        meta = rb.load(self.paper / ".tasks/draft.md")[0]
        self.assertEqual("approve draft " + rb.approval_token(self.paper, meta), task["approval_command"])
        self.assertIn(b"section", board.output(project["id"], "paper/main.tex", project["commit"]))
        for path in ("../private/bots.json", ".env", ".git/config", "paper/../../.env", "paper\\..\\.env"):
            with self.assertRaises(ValueError):
                board.output(project["id"], path, project["commit"])
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.handler(board))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(url + "/api/projects") as response:
                self.assertEqual("approval", json.load(response)["projects"][0]["tasks"][0]["column"])
                self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
            for headers in ({"Host": "evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(url + "/api/projects", headers=headers))
                self.assertEqual(403, error.exception.code)
        finally:
            server.shutdown()
            server.server_close()
