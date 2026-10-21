"""Exercise the embedded existing-Hermes probe against a changing auth API."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "src" / "HermesEasySetup.Codex.psm1"


class ExistingCodexProbeTests(unittest.TestCase):
    def test_auth_storage_shapes_without_auth_api_or_writes(self):
        source = SOURCE.read_text(encoding="utf-8")
        match = re.search(r"\$program = @'\n(.*?)\n'@", source, re.DOTALL)
        self.assertIsNotNone(match)
        probe = match.group(1)

        with tempfile.TemporaryDirectory(dir=SOURCE.parents[1]) as temp:
            root = Path(temp)
            package = root / "hermes_cli"
            package.mkdir()
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "codex_models.py").write_text(
                'def get_codex_model_ids():\n    return ["test-model", "second-model"]\n',
                encoding="utf-8",
            )
            (package / "config.py").write_text(
                'def read_raw_config():\n    return {"model": {"provider": "openai-codex", "default": "test-model"}}\n',
                encoding="utf-8",
            )
            home = root / "home"
            home.mkdir()
            auth_path = home / "auth.json"
            env = os.environ.copy()
            env["HERMES_HOME"] = str(home)

            for auth, expected in (
                ({"providers": {"openai-codex": {"tokens": {"access_token": "private-provider-token"}}}}, True),
                ({"credential_pool": {"openai-codex": [{"access_token": "private-pool-token"}]}}, True),
                ({"providers": {}}, False),
            ):
                with self.subTest(auth=bool(expected), shape=tuple(auth)):
                    data = json.dumps(auth).encode("utf-8")
                    auth_path.write_bytes(data)
                    result = subprocess.run(
                        [sys.executable, "-I", "-S", "-B", "-c", probe],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=15,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(auth_path.read_bytes(), data)
                    status = json.loads(result.stdout)
                    self.assertIs(status["LoggedIn"], expected)
                    self.assertEqual(status["Models"], ["test-model", "second-model"])
                    self.assertEqual(status["PreferredModel"], "test-model")
                    self.assertNotIn("private-", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
