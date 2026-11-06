import json
import tempfile
import unittest
from pathlib import Path

from test_sessions import claude_session

from session_desk.sessions import SessionStore


class PortfolioBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.claude = self.root / "claude"
        self.store = SessionStore(self.claude, self.root / "codex")

    def test_duplicate_native_ids_are_distinct(self):
        claude_session(self.claude, "same")
        other = self.claude / "projects" / "other" / "same.jsonl"
        other.parent.mkdir(parents=True)
        other.write_text((self.claude / "projects" / "-workspace" / "same.jsonl").read_text())
        rows = self.store.scan()
        self.assertEqual(len({row.id for row in rows}), 2)
        self.assertEqual({row.session_id for row in rows}, {"same"})

    def test_memory_collisions_trash_and_restore(self):
        files = [
            self.claude / "projects" / project / "memory" / "note.md" for project in ("a", "b")
        ]
        for i, path in enumerate(files):
            path.parent.mkdir(parents=True)
            path.write_text(f"body {i}")
        memories = self.store.memories()
        self.assertEqual(len(memories), 2)
        self.assertEqual(
            self.store.trash([m.id for m in memories], kind="memory").to_dict()["errors"], []
        )
        self.assertEqual(len(self.store.list_trash()), 2)
        self.assertEqual(
            self.store.restore([m.id for m in self.store.list_trash()]).to_dict()["errors"], []
        )
        self.assertEqual([p.read_text() for p in files], ["body 0", "body 1"])

    def test_memory_body_is_not_truncated(self):
        path = self.claude / "projects" / "a" / "memory" / "note.md"
        path.parent.mkdir(parents=True)
        path.write_text("x" * 7000)
        self.assertEqual(self.store.memories()[0].body, "x" * 7000)

    def test_stale_requested_version_does_not_trash(self):
        path = claude_session(self.claude)
        row = self.store.scan()[0]
        result = self.store.trash([row.id], versions={row.id: "stale"})
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(path.exists())

    def test_corrupt_manifest_reports_warning(self):
        path = self.claude / "trash" / "sessions-panel" / "bad" / "manifest.json"
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        self.assertEqual(self.store.list_trash(), [])
        self.assertTrue(self.store.warnings)

    def test_malformed_valid_json_manifests_do_not_crash_listing(self):
        folder = self.claude / "trash" / "sessions-panel" / "bad"
        folder.mkdir(parents=True)
        (folder / "manifest.json").write_text(
            json.dumps(
                {
                    "id": "bad",
                    "provider": "claude",
                    "session": {"kb": "broken"},
                    "deleted_at": "2026-01-01",
                    "moves": ["x"],
                    "indexes": [],
                }
            )
        )
        self.assertEqual(self.store.list_trash(), [])
        self.assertTrue(self.store.warnings)

    def test_legacy_manifest_is_restorable(self):
        path = claude_session(self.claude)
        folder = self.claude / "trash" / "sessions-panel" / "legacy"
        folder.mkdir(parents=True)
        path.rename(folder / "0")
        manifest = {
            "id": "legacy",
            "provider": "claude",
            "session": {
                "sid": "claude-one",
                "title": "",
                "first": "hello",
                "proj": "/workspace",
                "kb": 1,
            },
            "deleted_at": "2026-01-01T00:00:00",
            "moves": [str(path.relative_to(self.claude))],
            "indexes": [],
        }
        (folder / "manifest.json").write_text(json.dumps(manifest))
        self.assertEqual(self.store.list_trash()[0].kind, "session")
        self.assertEqual(self.store.restore(["legacy"]).to_dict()["errors"], [])
        self.assertTrue(path.exists())


class RecoveryPortfolioTests(unittest.TestCase):
    setUp = PortfolioBackendTests.setUp

    def test_invalid_codex_metadata_is_normalized_before_trash(self):
        from test_sessions import write_jsonl

        path = write_jsonl(
            self.root / "codex" / "sessions" / "invalid.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {"id": "bad", "cwd": 123, "git": {"branch": ["main"]}},
                },
            ],
        )
        row = self.store.scan()[0]
        self.assertIsInstance(row.project_path, str)
        self.assertIsInstance(row.branch, str)
        self.assertEqual(self.store.trash([row.id]).errors, [])
        self.assertEqual(len(self.store.list_trash()), 1)
        self.assertEqual(self.store.restore([self.store.list_trash()[0].id]).errors, [])
        self.assertTrue(path.exists())

    def test_interrupted_trash_between_session_and_sidecar_is_recoverable(self):
        from unittest.mock import patch

        path = claude_session(self.claude)
        sidecar = path.with_suffix("") / "subagents" / "agent.jsonl"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("data")
        row = self.store.scan()[0]
        move = self.store._trash._move
        calls = []

        def interrupt(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise KeyboardInterrupt()
            move(source, destination)

        with patch.object(self.store._trash, "_move", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.trash([row.id])
        entry = self.store.list_trash()[0]
        self.assertEqual(self.store.restore([entry.id]).errors, [])
        self.assertTrue(path.exists())
        self.assertEqual(sidecar.read_text(), "data")

    def test_interrupted_restore_can_resume(self):
        from unittest.mock import patch

        path = claude_session(self.claude)
        sidecar = path.with_suffix("") / "agent.jsonl"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("data")
        self.store.trash([self.store.scan()[0].id])
        entry = self.store.list_trash()[0]
        move = self.store._trash._move
        calls = []

        def interrupt(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise KeyboardInterrupt()
            move(source, destination)

        with patch.object(self.store._trash, "_move", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.restore([entry.id])
        self.assertEqual(self.store.restore([entry.id]).errors, [])
        self.assertTrue(path.exists())
        self.assertEqual(sidecar.read_text(), "data")

    def test_duplicate_codex_id_without_index_ownership_can_be_trashed(self):
        import sqlite3
        from contextlib import closing

        from test_sessions import codex_session

        path = codex_session(self.root / "codex")
        duplicate = self.root / "codex" / "archived_sessions" / "duplicate.jsonl"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_text(path.read_text())
        with closing(sqlite3.connect(self.root / "codex" / "state_5.sqlite")) as conn, conn:
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO threads VALUES (?, ?, ?, 0, NULL)", ("codex-one", str(path), "Title")
            )
        row = next(row for row in self.store.scan() if row.file_path == str(duplicate))
        self.assertEqual(self.store.trash([row.id]).errors, [])
        self.assertTrue(path.exists())
        self.assertEqual(self.store.restore([self.store.list_trash()[0].id]).errors, [])
        self.assertTrue(duplicate.exists())

    def test_changed_index_owner_is_rejected(self):
        import sqlite3
        from contextlib import closing

        from test_sessions import codex_session

        path = codex_session(self.root / "codex")
        db = self.root / "codex" / "state_5.sqlite"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO threads VALUES (?, ?, ?, 0, NULL)", ("codex-one", str(path), "Title")
            )
        row = self.store.scan()[0]
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("UPDATE threads SET rollout_path=?", ("/different",))
        self.assertEqual(len(self.store.trash([row.id]).errors), 1)
        self.assertTrue(path.exists())

    def test_interrupted_restore_rejects_modified_restored_session(self):
        from unittest.mock import patch

        path = claude_session(self.claude)
        sidecar = path.with_suffix("") / "agent.jsonl"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("data")
        self.store.trash([self.store.scan()[0].id])
        entry = self.store.list_trash()[0]
        move = self.store._trash._move
        calls = []

        def interrupt(source, destination):
            calls.append(source)
            if len(calls) == 2:
                raise KeyboardInterrupt()
            move(source, destination)

        with patch.object(self.store._trash, "_move", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.restore([entry.id])
        path.write_text("new changes")
        self.assertEqual(len(self.store.restore([entry.id]).errors), 1)
        self.assertEqual(path.read_text(), "new changes")
        self.assertEqual(len(self.store.list_trash()), 1)
