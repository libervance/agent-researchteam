"""Regression checks for false completion failures, bounded recovery and UI evidence."""
import importlib.util
import json
import unittest
from unittest.mock import patch
from test_research_board import Base, MockMattermost, ROOT, _load_board, git
from test_research_dashboard import dashboard

spec = importlib.util.spec_from_file_location("selftest", ROOT / "team/shared/team_selftest.py")
selftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selftest)


class CompletionTests(unittest.TestCase):
    def test_only_final_completion_marker_is_accepted(self):
        rb = _load_board()
        for text in ("STATUS: done", "Saved the file. STATUS: done", "Saved\n`STATUS: done`", "Saved\n**STATUS: done**"):
            self.assertEqual(("done", ""), rb.completion_marker(text))
        for text in ("Use STATUS: done when finished.", "STATUS: done\nStill working", "STATUS: done-ish"):
            self.assertEqual((None, ""), rb.completion_marker(text))
        self.assertEqual(("blocked", "no access"), rb.completion_marker("STATUS: blocked — no access"))

    def test_installer_waits_for_bounded_retry_but_stops_on_exhaustion_or_refusal(self):
        meta = {"status": "failed", "stop_reason": "exit 0; no STATUS line", "resume_policy": "auto", "attempt": "1", "max_attempts": "2"}
        with patch.object(selftest.rb, "tasks", return_value={"t-librarian": (None, meta, "")}):
            self.assertEqual("", selftest.terminal_failure(None))
            meta["attempt"] = "2"
            self.assertIn("no STATUS line", selftest.terminal_failure(None))
            meta.update(attempt="1", status="blocked", stop_reason="profile changed")
            self.assertIn("profile changed", selftest.terminal_failure(None))


class RecoveryTests(Base):
    def check_project(self):
        self.paper = self.ws / "_selftest-20261022-001122"
        self.paper.mkdir()
        (self.paper / "CLAUDE.md").write_text("# Installation check\n**Sensitivity:** public\n")
        self.board("init", str(self.paper))
        self.board("setup", str(self.paper), "--channel", "c" * 26, "--mention", "@me")
        (self.paper / ".tasks/project.json").write_text("{}")
        git("add", ".tasks/project.json", cwd=self.paper)
        git("commit", "-qm", "managed check", cwd=self.paper)
        git("push", "-q", cwd=self.paper)

    def test_inline_done_still_requires_expected_files(self):
        self.task("yes", "research-lead", "WRITE-PAPER INLINE-DONE", "--expects", "paper/main.tex")
        self.run_role("research-lead")
        self.assertIn("status: done", self.state("yes"))
        self.task("no", "research-lead", "INLINE-DONE", "--expects", "paper/missing.tex")
        self.run_role("research-lead")
        self.assertIn("status: failed", self.state("no"))
        self.assertIn("stop_reason: exit 0; missing paper/missing.tex", self.state("no"))

    def test_installation_retries_once_preserves_both_attempts_and_posts_korean_result(self):
        self.check_project()
        self.task("t-author", "research-lead", "WRITE-PAPER NO-MARKER", "--expects", "paper/main.tex")
        self.run_role("research-lead")
        self.assertIn("status: done", self.state("t-author"))
        ledger = [json.loads(line) for line in (self.paper / ".tasks/ledger.jsonl").read_text().splitlines()]
        self.assertEqual(["failed", "done"], [e["status"] for e in ledger])
        self.assertIn("no STATUS line", ledger[0]["stop_reason"])
        self.assertEqual(2, len(self.calls()))
        messages = [p["message"] for p in MockMattermost.posts]
        self.assertTrue(any("LaTeX 원고 예제를 저장" in m for m in messages))
        self.assertTrue(any("재시도가 완료" in m for m in messages))
        self.assertFalse(any("needs a decision" in m or "@me" in m for m in messages))

    def test_exhausted_retry_does_not_loop_and_real_projects_do_not_retry_failed_work(self):
        self.check_project()
        self.task("t-author", "research-lead", "WRITE-PAPER NO-MARKER ALWAYS")
        self.run_role("research-lead")
        self.assertIn("status: failed", self.state("t-author"))
        self.assertIn("attempt: 2", self.state("t-author"))
        self.assertEqual(2, len(self.calls()))
        self.board("coordinate", "--once", "--hermes", str(self.hermes))
        self.assertEqual(2, len(self.calls()), "coordinator must not restart an exhausted installation check")
        self.paper = self.ws / "p1"
        self.task("real", "research-experimenter", "NO-MARKER ALWAYS", "--resume-policy", "auto")
        self.run_role("research-experimenter")
        self.assertIn("attempt: 1", self.state("real"))
        self.assertIn("status: failed", self.state("real"))

    def test_board_distinguishes_completed_work_from_failed_final_validation(self):
        self.check_project()
        self.task("t-author", "research-lead", "WRITE-PAPER")
        self.run_role("research-lead")
        self.home.mkdir(exist_ok=True)
        result = {"folder": str(self.paper), "passed": False, "error": "lead check failed", "roles": {"research-lead": "done"}}
        (self.home / "live-test.json").write_text(json.dumps(result))
        board = dashboard.Board(self.ws, self.home)
        self.assertFalse(any(p["test"] for p in board.snapshot()["projects"]))
        checks = board.snapshot(include_tests=True, checks_only=True)["projects"]
        self.assertEqual(1, len(checks))
        self.assertEqual("done", checks[0]["tasks"][0]["status"])
        self.assertEqual("incomplete", checks[0]["check"]["outcome"])
        with patch.object(selftest.rb, "TEAM_HOME", self.home):
            selftest.save_check(result, "총괄 확인 중")
        self.assertEqual("running", dashboard.Board(self.ws, self.home).snapshot(self.paper.name)["projects"][0]["check"]["outcome"])


if __name__ == "__main__":
    unittest.main()
