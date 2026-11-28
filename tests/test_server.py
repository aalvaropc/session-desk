import http.client
import json
import socket
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

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

    def start_server(self, index_path=None):
        from session_desk.server import make_server

        self.server = make_server(self.store(), port=0, index_path=index_path)
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
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": f"r{index}"}]},
                }
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
        encoded = f"/api/sessions/{quote(session.id, safe='')}/messages"
        self.assertEqual(self.request("GET", encoded, headers=self.headers())[0], 200)
        for bad in (
            "/api/sessions/claude:" + "0" * 64 + "/messages",
            "/api/sessions/../x/messages",
        ):
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

    def test_initial_page_and_index_progress_respond_while_catalog_is_busy(self):
        self.start_server()
        with self.server.store_lock:
            self.server.index_progress = {"phase": "index", "completed": 2, "total": 10}
            self.assertEqual(self.request("GET", "/")[0], 200)
            self.assertEqual(self.request("GET", "/api/progress")[0], 403)
            status, body = self.request("GET", "/api/progress", headers=self.headers())
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), self.server.index_progress)

    def test_saved_conversation_is_available_during_a_background_refresh(self):
        from pathlib import Path

        from session_desk.services.workspace import Workspace

        path = claude_session(self.claude, text="saved message")
        index = Path(self.claude).parent / "workspace.sqlite3"
        with Workspace(self.store(), index) as workspace:
            workspace.refresh()
            identifier = next(iter(workspace.rows))
        path = Path(path)
        entered = threading.Event()
        release = threading.Event()
        write_session = Workspace.write_session

        def slow_write(workspace, *args, **kwargs):
            result = write_session(workspace, *args, **kwargs)
            entered.set()
            if not release.wait(6):
                raise RuntimeError("Did not release the background scan")
            return result

        self.start_server(index)
        with path.open("a", encoding="utf-8") as stream:
            stream.write('{"type":"assistant","message":{"content":"new message"}}\n')
        with patch.object(Workspace, "write_session", slow_write):
            try:
                self.assertEqual(
                    self.request("GET", "/api/catalog?cached=1", headers=self.headers())[0], 200
                )
                self.assertTrue(entered.wait(3))
                status, body = self.request(
                    "GET", "/api/search?q=saved%20message", headers=self.headers()
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["total"], 1)
                status, body = self.request(
                    "GET", "/api/search?q=new%20message", headers=self.headers()
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["total"], 0)
                status, body = self.request(
                    "GET", f"/api/sessions/{identifier}/messages", headers=self.headers()
                )
                self.assertEqual(status, 200)
                self.assertNotIn("new message", str(json.loads(body)["messages"]))
                status, body = self.request("POST", "/api/reviews", {"reviews": {}}, self.headers())
                self.assertEqual(status, 409)
                self.assertEqual(json.loads(body)["code"], "index_in_progress")
            finally:
                release.set()
        self.server.index_thread.join(timeout=4)
        self.assertFalse(self.server.index_thread.is_alive())
        status, body = self.request("GET", "/api/search?q=new%20message", headers=self.headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["total"], 1)

    def test_failed_initial_refresh_protects_cached_session_from_trash(self):
        from pathlib import Path

        from session_desk.services.workspace import Workspace

        path = claude_session(self.claude)
        index = Path(self.claude).parent / "workspace.sqlite3"
        with Workspace(self.store(), index) as workspace:
            workspace.refresh()
            row = next(iter(workspace.rows.values()))
        self.start_server(index)
        with patch.object(Workspace, "refresh", side_effect=OSError("index write failed")):
            self.assertEqual(
                self.request("GET", "/api/catalog?cached=1", headers=self.headers())[0], 200
            )
            self.server.index_thread.join(timeout=4)
            self.assertFalse(self.server.index_thread.is_alive())
        payload = {"ids": [row.id], "versions": {row.id: row.version}}
        status, body = self.request("POST", "/api/trash", payload, self.headers())
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["code"], "index_not_ready")
        self.assertTrue(path.exists())

    def test_empty_workspace_serves_search_results_before_import_finishes(self):
        import os
        from pathlib import Path

        from session_desk.services.workspace import Workspace

        folder = Path(self.claude) / "projects" / "sample"
        folder.mkdir(parents=True)
        for identifier, modified in (("old", 1000000000), ("recent", 1000000001)):
            path = folder / f"{identifier}.jsonl"
            path.write_text(
                json.dumps({"type": "user", "message": {"content": f"{identifier} transcript"}})
                + "\n",
                encoding="utf-8",
            )
            os.utime(path, (modified, modified))
        self.start_server(Path(self.claude).parent / "progressive.sqlite3")
        entered = threading.Event()
        release = threading.Event()
        write = Workspace.write_session

        def pause_before_old_file(workspace, row, *args):
            if row.session_id == "old":
                entered.set()
                if not release.wait(6):
                    raise RuntimeError("Did not release the older transcript")
            return write(workspace, row, *args)

        with patch.object(Workspace, "write_session", pause_before_old_file):
            try:
                self.assertEqual(
                    self.request("GET", "/api/catalog?cached=1", headers=self.headers())[0], 200
                )
                self.assertTrue(entered.wait(3))
                status, body = self.request(
                    "GET", "/api/search?q=recent%20transcript", headers=self.headers()
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["total"], 1)
                status, body = self.request("GET", "/api/progress", headers=self.headers())
                self.assertEqual(status, 200)
                progress = json.loads(body)
                self.assertEqual(progress["phase"], "index")
                self.assertEqual(progress["available"], 1)
            finally:
                release.set()
        self.server.index_thread.join(timeout=4)
        status, body = self.request("GET", "/api/sessions", headers=self.headers())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["catalog_total"], 2)

    def test_http_trash_restore_and_stale_snapshot(self):
        path = claude_session(self.claude)
        self.start_server()
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn(b"Revisa el panel", body)
        self.assertIn(b'"paged": true', body)
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
