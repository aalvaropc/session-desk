import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_sessions import claude_session


class DistributionTests(unittest.TestCase):
    def test_demo_is_synthetic_and_real_roots_are_not_read(self):
        from session_desk.demo import demo_store

        with tempfile.TemporaryDirectory() as directory:
            real = Path(directory) / "claude"
            sentinel = claude_session(real, text="private content must not enter demo")
            with demo_store() as store:
                sessions = store.scan()
                self.assertGreater(len(sessions), 10)
                self.assertEqual(
                    {row.provider for row in sessions}, {"claude", "codex", "antigravity"}
                )
                self.assertNotIn(
                    "private content must not enter demo",
                    json.dumps([row.to_dict() for row in sessions]),
                )
                self.assertTrue(store.memories())
            self.assertTrue(sentinel.exists())

    def test_demo_static_export_is_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.html"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "session_desk.cli",
                    "--demo",
                    "--static",
                    "-o",
                    str(output),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            page = output.read_text()
            bootstrap = re.search(
                r'<script id="app-data" type="application/json">(.*?)</script>', page, re.S
            )
            self.assertIsNotNone(bootstrap)
            catalog = json.loads(bootstrap.group(1))
            self.assertEqual(catalog["mode"], "demo")
            self.assertIsNone(catalog["token"])
            self.assertGreater(len(catalog["sessions"]), 10)
            self.assertNotIn('src="/assets/', page)
            self.assertNotIn('href="/assets/', page)
            self.assertIn("data:font/woff2;base64,", page)

    def test_real_export_is_read_only_and_filters_are_applied(self):
        from session_desk.rendering import build_catalog
        from session_desk.sessions import SessionStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claude_session(root / "claude", text="Keep this searchable request")
            store = SessionStore(root / "claude", root / "codex", root / "gemini")
            catalog = build_catalog(store, mode="static", search="searchable")
            self.assertEqual(len(catalog["sessions"]), 1)
            self.assertEqual(catalog["mode"], "static")
            self.assertIsNone(catalog["token"])
            self.assertEqual(build_catalog(store, mode="static", project="missing")["sessions"], [])
