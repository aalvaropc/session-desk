import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from session_desk.sessions import SessionStore


class BackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="session-desk-lifecycle-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = {
            **os.environ,
            "SESSION_DESK_STATE_DIR": str(self.root),
            "PYTHONPATH": str(Path("src").resolve()),
        }
        self.command = [sys.executable, "-m", "session_desk.cli"]
        self.addCleanup(self.stop_background)

    def run_cli(self, *arguments):
        return subprocess.run(
            [*self.command, *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def stop_background(self):
        self.run_cli("stop")

    def start_demo(self, *arguments):
        result = self.run_cli("start", "--demo", "--port", "0", *arguments)
        log = self.root / "server.log"
        detail = result.stderr + (log.read_text(encoding="utf-8") if log.exists() else "")
        self.assertEqual(result.returncode, 0, detail)
        match = re.search(r"http://127\.0\.0\.1:\d+", result.stdout)
        self.assertIsNotNone(match, result.stdout)
        return result, match.group()

    def test_background_survives_launcher_exit_and_stops_cleanly(self):
        result, url = self.start_demo()
        record = json.loads((self.root / "server.json").read_text(encoding="utf-8"))
        self.assertNotIn(record["token"], result.stdout)
        if os.name != "nt":
            self.assertEqual(os.getsid(record["pid"]), record["pid"])
            self.assertEqual((self.root / "server.json").stat().st_mode & 0o077, 0)
        status = self.run_cli("status")
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertIn(url, status.stdout)
        with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
            self.assertEqual(response.status, 200)
        stopped = self.run_cli("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn("stopped", stopped.stdout.lower())
        self.assertFalse((self.root / "server.json").exists())
        if os.name == "nt":
            (self.root / "server.log").unlink()
        self.assertIn("not running", self.run_cli("status").stdout.lower())
        self.assertEqual(self.run_cli("stop").returncode, 0)

    def test_repeated_start_reuses_the_same_managed_instance(self):
        _, first_url = self.start_demo()
        first = json.loads((self.root / "server.json").read_text(encoding="utf-8"))
        _, second_url = self.start_demo()
        second = json.loads((self.root / "server.json").read_text(encoding="utf-8"))
        self.assertEqual(first_url, second_url)
        self.assertEqual(first["instance_id"], second["instance_id"])
        self.assertEqual(first["pid"], second["pid"])

    def test_concurrent_starts_create_one_instance(self):
        processes = [
            subprocess.Popen(
                [*self.command, "start", "--demo", "--port", "0"],
                env=self.environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        results = [process.communicate(timeout=20) for process in processes]
        for process, (output, errors) in zip(processes, results):
            self.assertEqual(process.returncode, 0, errors)
            self.assertRegex(output, r"http://127\.0\.0\.1:\d+")
        urls = [re.search(r"http://127\.0\.0\.1:\d+", output).group() for output, _ in results]
        self.assertEqual(urls[0], urls[1])

    def test_different_start_options_do_not_silently_reuse_another_workspace(self):
        self.start_demo()
        result = self.run_cli("start", "--port", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stop", result.stderr.lower())
        self.assertIn("running", self.run_cli("status").stdout.lower())

    def test_occupied_port_reports_failure_without_leaving_a_record(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            result = self.run_cli("start", "--demo", "--port", str(occupied.getsockname()[1]))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log", result.stderr.lower())
        self.assertFalse((self.root / "server.json").exists())

    def test_corrupt_state_and_foreign_instance_are_not_stopped(self):
        from session_desk.server import make_server

        (self.root / "server.json").write_text("{invalid", encoding="utf-8")
        self.assertIn("not running", self.run_cli("status").stdout.lower())
        server = make_server(
            SessionStore(self.root / "claude", self.root / "codex", self.root / "gemini"),
            port=0,
            instance_id="b" * 32,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        record = {
            "application": "session-desk",
            "instance_id": "a" * 32,
            "token": server.token,
            "pid": os.getpid(),
            "url": server.origin,
            "configuration": {},
            "started_at": "2026-11-06",
        }
        (self.root / "server.json").write_text(json.dumps(record), encoding="utf-8")
        stopped = self.run_cli("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn("not running", stopped.stdout.lower())
        request = Request(server.origin + "/api/status", headers={"X-Panel-Token": server.token})
        with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
            self.assertEqual(json.load(response)["instance_id"], "b" * 32)

    def test_reused_port_with_invalid_http_is_treated_as_stale(self):
        for response in (
            b"NOT-HTTP\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nA\r\nshort",
        ):
            with self.subTest(response=response):

                class InvalidHTTP(socketserver.BaseRequestHandler):
                    def handle(self):
                        self.request.recv(4096)
                        self.request.sendall(response)

                server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), InvalidHTTP)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    record = {
                        "application": "session-desk",
                        "instance_id": "a" * 32,
                        "token": "b" * 43,
                        "pid": os.getpid(),
                        "url": f"http://127.0.0.1:{server.server_address[1]}",
                        "configuration": {},
                        "started_at": "2026-11-06",
                    }
                    (self.root / "server.json").write_text(json.dumps(record), encoding="utf-8")
                    result = self.run_cli("status")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("not running", result.stdout.lower())
                finally:
                    server.shutdown()
                    server.server_close()
