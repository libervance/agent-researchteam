"""Real local Git races: no model calls, installed profiles, or network remotes."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "team/shared"))
import research_board as rb
import team_selftest as selftest


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="publication-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / "empty.config"; config.write_text("")
        template = self.root / "empty-template"; template.mkdir()
        env = patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "file", "GIT_CONFIG_GLOBAL": str(config),
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_TEMPLATE_DIR": str(template)})
        env.start(); self.addCleanup(env.stop)
        self.remote = self.root / "remote.git"
        rb.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.a = self.root / "a"; self.b = self.root / "b"
        rb.git(self.root, "clone", str(self.remote), str(self.a))
        rb.git_identity(self.a, "fixture")
        (self.a / ".tasks").mkdir()
        (self.a / "seed").write_text("seed\n")
        rb.ledger_append(self.a, {"task": "seed"})
        rb.git(self.a, "add", ".")
        rb.git(self.a, "commit", "-m", "seed")
        rb.git(self.a, "push", "-u", "origin", "main")
        rb.git(self.root, "clone", str(self.remote), str(self.b))
        rb.git_identity(self.b, "fixture")

    def result(self, clone, task, output=None):
        name = output or task + ".txt"
        (clone / name).write_text(task + "\n")
        rb.ledger_append(clone, {"task": task, "outputs": {name: rb.sha256_file(clone / name)}})
        rb.stage(clone, [name, rb.LEDGER])

    def test_concurrent_results_preserve_all_outputs_and_ledger_prefix(self):
        self.result(self.a, "reviewer")
        self.result(self.b, "writer")
        rb.commit_push(self.a, "reviewer done")
        prefix = rb.ledger_lines(self.a)
        rb.commit_push(self.b, "writer done")
        rb.reset_to_remote(self.a)
        lines = rb.ledger_lines(self.a)
        self.assertEqual(prefix, lines[:len(prefix)])
        self.assertIsNone(rb.ledger_check(lines))
        self.assertEqual(["seed", "reviewer", "writer"], [json.loads(l)["task"] for l in lines])
        self.assertEqual("writer\n", (self.a / "writer.txt").read_text())
        self.assertEqual("reviewer\n", (self.a / "reviewer.txt").read_text())
        self.assertNotEqual(0, rb.git(self.b, "rev-parse", "--verify", rb.PENDING_PUBLICATION, check=False).returncode)

    def test_first_concurrent_ledger_entries(self):
        rb.git(self.a, "rm", rb.LEDGER)
        rb.commit_push(self.a, "empty ledger")
        rb.reset_to_remote(self.b)
        self.test_multiple_pending_commits()

    def test_multiple_pending_commits(self):
        # Also exercises multiple local commits while other workers publish.
        self.result(self.a, "reviewer")
        self.result(self.b, "writer")
        rb.git(self.b, "commit", "-m", "writer done")
        self.result(self.b, "experimenter")
        rb.commit_push(self.a, "reviewer done")
        rb.commit_push(self.b, "experimenter done")
        lines = rb.ledger_lines(self.b)
        self.assertIsNone(rb.ledger_check(lines))
        self.assertEqual(["reviewer", "writer", "experimenter"], [json.loads(l)["task"] for l in lines[-3:]])

    def test_real_output_conflict_survives_next_poll(self):
        self.result(self.a, "reviewer", "shared.txt")
        self.result(self.b, "writer", "shared.txt")
        rb.commit_push(self.a, "reviewer done")
        with self.assertRaisesRegex(RuntimeError, "publication pending"):
            rb.commit_push(self.b, "writer done")
        original = rb.git(self.b, "rev-parse", "HEAD").stdout.strip()
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "publication pending"):
                rb.reset_to_remote(self.b)
            self.assertEqual(original, rb.git(self.b, "rev-parse", "HEAD").stdout.strip())
            self.assertEqual(original, rb.git(self.b, "rev-parse", rb.PENDING_PUBLICATION).stdout.strip())
            self.assertEqual("writer\n", (self.b / "shared.txt").read_text())

    def test_next_poll_retries_saved_result_without_model_call(self):
        self.result(self.b, "writer")
        rb.git(self.b, "commit", "-m", "result saved just before crash")
        self.result(self.a, "reviewer")
        rb.commit_push(self.a, "reviewer done")
        rb.reset_to_remote(self.b)
        rb.reset_to_remote(self.a)
        self.assertTrue((self.a / "writer.txt").exists())
        self.assertIsNone(rb.ledger_check(rb.ledger_lines(self.a)))

    def test_rewritten_ledger_is_not_silently_merged(self):
        self.result(self.b, "writer")
        (self.a / rb.LEDGER).write_text('{"task":"rewritten","prev":""}\n')
        rb.stage(self.a, [rb.LEDGER]); rb.commit_push(self.a, "rewritten")
        with self.assertRaisesRegex(RuntimeError, "publication pending"):
            rb.commit_push(self.b, "writer done")
        self.assertEqual("seed", json.loads(rb.ledger_lines(self.b)[0])["task"])

    def test_interrupted_rebase_is_not_reset(self):
        self.result(self.a, "reviewer", "shared.txt")
        self.result(self.b, "writer", "shared.txt")
        rb.commit_push(self.a, "reviewer done")
        rb.git(self.b, "commit", "-m", "writer done")
        rb.git(self.b, "update-ref", rb.PENDING_PUBLICATION, "HEAD")
        original = rb.git(self.b, "rev-parse", rb.PENDING_PUBLICATION).stdout
        rb.git(self.b, "fetch", "origin")
        self.assertNotEqual(0, rb.git(self.b, "rebase", "@{u}", check=False).returncode)
        with self.assertRaisesRegex(RuntimeError, "interrupted rebase"):
            rb.reset_to_remote(self.b)
        self.assertEqual(original, rb.git(self.b, "rev-parse", rb.PENDING_PUBLICATION).stdout)
        self.assertIn("shared.txt", rb.git(self.b, "diff", "--name-only", "--diff-filter=U").stdout)

    def test_selftest_partial_waits_for_auto_resume_only(self):
        path = self.a / ".tasks/t-writer.md"
        meta = {"id": "t-writer", "status": "partial", "attempt": "1", "max_attempts": "2", "resume_policy": "auto"}
        rb.save(path, meta, "")
        self.assertEqual("", selftest.terminal_failure(self.a))
        meta["attempt"] = "2"; rb.save(path, meta, "")
        self.assertIn("partial", selftest.terminal_failure(self.a))
        meta.update(attempt="1", resume_policy="manual"); rb.save(path, meta, "")
        self.assertIn("partial", selftest.terminal_failure(self.a))

    def test_selftest_reports_only_current_board_errors(self):
        run = self.root / "run"; run.mkdir()
        status = run / "research-writer-1.json"
        status.write_text(json.dumps({"role": "research-writer", "errors": {
            "test": {"remote": str(self.remote), "error": "publication pending"},
            "other": {"remote": "other", "error": "unrelated"}}}))
        self.assertEqual(["research-writer: publication pending"], selftest.runner_errors(self.a, self.root))


if __name__ == "__main__":
    unittest.main()
