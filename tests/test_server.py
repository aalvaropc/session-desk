import http.client
import json
import socket
import threading
import unittest
from unittest.mock import patch

import test_sessions as fixtures
from test_sessions import claude_session


class ServerTests(unittest.TestCase):
    setUp = fixtures.SessionTests.setUp
    store = fixtures.SessionTests.store

    def test_binding_loopback_does_not_require_name_resolution(self):
        from session_desk.server import make_server

        with patch("socket.getfqdn", side_effect=AssertionError("unexpected DNS lookup")):
            server = make_server(self.store(), port=0)
        self.addCleanup(server.server_close)
        self.assertEqual(server.server_name, "127.0.0.1")

    def start_server(self):
        from session_desk.server import make_server

        self.server = make_server(self.store(), port=0)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(
                method,
                path,
                body=json.dumps(data) if data is not None else None,
                headers=headers or {},
            )
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def headers(self):
        return {"X-Panel-Token": self.server.token, "Content-Type": "application/json"}

    def test_server_requires_token_and_same_origin_before_mutating(self):
        path = claude_session(self.claude)
        self.start_server()
        session = self.server.store.scan()[0]
        data = {"ids": [session.id], "versions": {session.id: session.version}}
        self.assertEqual(self.request("POST", "/api/trash", data)[0], 403)
        headers = {**self.headers(), "Origin": "https://unrelated.example"}
        self.assertEqual(self.request("POST", "/api/trash", data, headers)[0], 403)
        headers = {**self.headers(), "Host": "unrelated.example"}
        self.assertEqual(self.request("POST", "/api/trash", data, headers)[0], 403)
        self.assertTrue(path.exists())

    def test_full_conversation_is_served_beyond_catalog_preview_limits(self):
        from test_sessions import write_jsonl

        long_text = "x" * 2000
        records = [{"type": "user", "cwd": "/workspace", "message": {"content": long_text}}]
        for index in range(30):
            records.append(
                {"type": "assistant", "message": {"content": [{"type": "text", "text": f"r{index}"}]}}
            )
        write_jsonl(self.claude / "projects" / "-workspace" / "long.jsonl", records)
        self.start_server()
        session = self.server.store.scan()[0]
        self.assertEqual(len(session.messages), 10)
        path = f"/api/sessions/{session.id}/messages"
        self.assertEqual(self.request("GET", path)[0], 403)
        status, body = self.request("GET", path, headers=self.headers())
        self.assertEqual(status, 200)
        messages = json.loads(body)["messages"]
        self.assertEqual(len(messages), 31)
        self.assertEqual(messages[0], {"role": "user", "text": long_text})
        self.assertEqual(messages[-1]["text"], "r29")
        for bad in ("/api/sessions/claude:" + "0" * 64 + "/messages", "/api/sessions/../x/messages"):
            self.assertEqual(self.request("GET", bad, headers=self.headers())[0], 404)

    def test_full_codex_conversation_ignores_instructions_and_duplicate_events(self):
        fixtures.codex_session(self.codex)
        self.start_server()
        session = self.server.store.scan()[0]
        status, body = self.request(
            "GET", f"/api/sessions/{session.id}/messages", headers=self.headers()
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(body)["messages"],
            [
                {"role": "user", "text": "Mejora la búsqueda"},
                {"role": "assistant", "text": "Busqué dentro de todas las sesiones"},
            ],
        )

    def test_server_validates_payload_and_only_serves_whitelisted_routes(self):
        self.start_server()
        for payload in ({"ids": "file"}, {"ids": [1]}, {"ids": []}, None):
            self.assertEqual(self.request("POST", "/api/trash", payload, self.headers())[0], 400)
        for path in ("/../../etc/passwd", "/assets/../../pyproject.toml", "/assets/unknown.js"):
            self.assertEqual(self.request("GET", path)[0], 404)
        self.assertEqual(self.request("GET", "/api/catalog")[0], 403)
        status, body = self.request("GET", "/assets/styles.css")
        self.assertEqual(status, 200)
        self.assertIn(b"color", body)

    def test_browser_preconnect_does_not_block_other_requests(self):
        self.start_server()
        idle = socket.create_connection(("127.0.0.1", self.port))
        try:
            self.assertEqual(self.request("GET", "/")[0], 200)
        finally:
            idle.close()

    def test_http_trash_restore_and_stale_snapshot(self):
        path = claude_session(self.claude)
        self.start_server()
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Revisa el panel", body)
        session = self.server.store.scan()[0]
        stale = {"ids": [session.id], "versions": {session.id: "old"}}
        self.assertEqual(self.request("POST", "/api/trash", stale, self.headers())[0], 409)
        data = {"ids": [session.id], "versions": {session.id: session.version}}
        status, body = self.request("POST", "/api/trash", data, self.headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["done"], [session.id])
        self.assertFalse(path.exists())
        _, body = self.request("GET", "/api/trash", headers=self.headers())
        entry = json.loads(body)[0]
        status, body = self.request("POST", "/api/restore", {"ids": [entry["id"]]}, self.headers())
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["errors"])
        self.assertTrue(path.exists())

    def test_memory_round_trip_and_catalog_contract(self):
        path = self.claude / "projects" / "a" / "memory" / "note.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: Project conventions\ntype: project\n---\nUse explicit names.")
        self.start_server()
        status, body = self.request("GET", "/api/catalog", headers=self.headers())
        catalog = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(catalog["mode"], "local")
        memory = catalog["memories"][0]
        payload = {
            "ids": [memory["id"]],
            "versions": {memory["id"]: memory["version"]},
            "kind": "memory",
        }
        status, body = self.request("POST", "/api/trash", payload, self.headers())
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["errors"])
        self.assertFalse(path.exists())
        _, body = self.request("GET", "/api/trash", headers=self.headers())
        entry = json.loads(body)[0]
        self.assertEqual(entry["kind"], "memory")
        _, body = self.request("POST", "/api/restore", {"ids": [entry["id"]]}, self.headers())
        self.assertFalse(json.loads(body)["errors"])
        self.assertTrue(path.exists())
