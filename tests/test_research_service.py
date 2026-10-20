"""team_service: starts one runner per role/slot, restarts a crashed one, passes each runner
only its own bot token, and stops every child on request."""
import json
import os
import shutil
import subprocess as sp
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "team" / "shared" / "team_service.py"

FAKE_BOARD = r'''
import json, os, sys, time
from pathlib import Path
role = sys.argv[sys.argv.index("--role") + 1]; slot = sys.argv[sys.argv.index("--slot") + 1]
out = Path(os.environ["RESEARCH_TEAM_HOME"]) / f"env-{role}-{slot}.json"
out.write_text(json.dumps({"token": os.environ.get("MATTERMOST_TOKEN"), "secret": os.environ.get("RESEARCH_GATEWAY_SECRET"),
                           "pid": os.getpid()}))
time.sleep(600)
'''


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="service-test-"))
        board = self.tmp / "board.py"; board.write_text(FAKE_BOARD)
        secrets = self.tmp / "secrets.env"
        secrets.write_text("MATTERMOST_URL=http://127.0.0.1:1\nMATTERMOST_TOKEN__research-writer=" + "w" * 26 +
                           "\nMATTERMOST_TOKEN__research-reviewer=" + "r" * 26 + "\nRESEARCH_GATEWAY_SECRET=s3\n")
        self.home = self.tmp / "home"
        self.cfg = self.tmp / "service.json"
        self.cfg.write_text(json.dumps({
            "team_home": str(self.home), "hermes_home": str(self.tmp / "hh"), "python": sys.executable,
            "hermes": "hermes", "board": str(board), "papers_file": str(self.tmp / "papers"),
            "secrets_file": str(secrets), "gateway": None,
            "runners": [{"role": "research-writer", "slot": 1}, {"role": "research-reviewer", "slot": 1},
                        {"role": "research-reviewer", "slot": 2}]}))
        import team_service_under_test  # noqa: F401
        self.proc = sp.Popen([sys.executable, str(SERVICE), "serve", "--config", str(self.cfg)])

    def tearDown(self):
        sp.run([sys.executable, str(SERVICE), "stop", "--config", str(self.cfg)], capture_output=True)
        try:
            self.proc.wait(timeout=30)
        except sp.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def status(self):
        p = self.home / "service-status.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def wait_for(self, cond, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if cond():
                    return True
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.5)
        return False

    def test_runners_started_with_own_token_restarted_and_stopped(self):
        files = [self.home / f"env-{n}.json" for n in ("research-writer-1", "research-reviewer-1", "research-reviewer-2")]
        self.assertTrue(self.wait_for(lambda: all(f.exists() for f in files)))
        w = json.loads(files[0].read_text()); r = json.loads(files[2].read_text())
        self.assertEqual("w" * 26, w["token"]); self.assertEqual("r" * 26, r["token"]); self.assertEqual("s3", w["secret"])
        self.assertTrue(self.wait_for(lambda: all(c["state"] == "running" for c in self.status()["children"])))
        victim = json.loads(files[1].read_text())["pid"]
        files[1].unlink()
        os.kill(victim, 9) if os.name != "nt" else sp.run(["taskkill", "/F", "/PID", str(victim)], capture_output=True)
        self.assertTrue(self.wait_for(lambda: files[1].exists(), timeout=40), "crashed runner was not restarted")
        self.assertEqual(1, [c for c in self.status()["children"] if c["name"] == "research-reviewer-1"][0]["restarts"])
        pids = [json.loads(f.read_text())["pid"] for f in files]
        sp.run([sys.executable, str(SERVICE), "stop", "--config", str(self.cfg)], check=True, capture_output=True)
        self.proc.wait(timeout=30)
        self.assertTrue(self.status().get("stopped"))
        time.sleep(1)
        for pid in pids:
            if os.name != "nt":
                with self.assertRaises(OSError):
                    os.kill(pid, 0)

    def test_coordinator_child_gets_gateway_secret_without_bot_token(self):
        import team_service_under_test as service
        cfg = json.loads(self.cfg.read_text(encoding="utf-8"))
        cfg["coordinator"] = {"enabled": True, "task_timeout": 1200}
        lead = [child for child in service.children(cfg) if child.name == "lead-coordinator"]
        self.assertEqual(1, len(lead))
        self.assertEqual("s3", lead[0].env["RESEARCH_GATEWAY_SECRET"])
        self.assertNotIn("MATTERMOST_TOKEN", lead[0].env)
        self.assertIn("coordinate", lead[0].argv)


import importlib.util as _u  # noqa: E402
_spec = _u.spec_from_file_location("team_service_under_test", SERVICE)
sys.modules["team_service_under_test"] = _u.module_from_spec(_spec); _spec.loader.exec_module(sys.modules["team_service_under_test"])

if __name__ == "__main__":
    unittest.main()
