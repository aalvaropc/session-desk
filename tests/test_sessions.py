import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from session_desk.providers.claude import extract


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def claude_session(root, sid="claude-one", text="Revisa el panel"):
    return write_jsonl(
        root / "projects" / "-workspace" / f"{sid}.jsonl",
        [
            {
                "type": "user",
                "cwd": "/workspace",
                "gitBranch": "main",
                "message": {"content": text},
            },
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Listo"}]}},
        ],
    )


def codex_session(root, sid="codex-one"):
    return write_jsonl(
        root / "sessions" / "2026" / "11" / f"rollout-{sid}.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {"id": sid, "cwd": "/workspace", "git": {"branch": "feature/panel"}},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "# AGENTS.md instructions\ninternal"}
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Mejora la búsqueda"}],
                },
            },
            {
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Mejora la búsqueda"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "Busqué dentro de todas las sesiones"}
                    ],
                },
            },
        ],
    )


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.claude = self.root / "claude"
        self.codex = self.root / "codex"

    def store(self):
        from session_desk.sessions import SessionStore

        return SessionStore(self.claude, self.codex)

    def test_spaced_claude_json_is_counted_and_searchable(self):
        path = claude_session(self.claude)
        row = extract(str(path), {}, grep="Listo")
        self.assertEqual(row["msgs"], 2)
        self.assertEqual(row["match"], "Listo")

    def test_malformed_claude_records_do_not_hide_valid_messages(self):
        path = claude_session(self.claude)
        with path.open("a") as f:
            f.write('null\n{"type":"user","message":"malformed"}\n')
            f.write('{"type":"custom-title","customTitle":{"invalid":"shape"}}\n')
        row = extract(str(path), {})
        self.assertEqual(row["last"][-1]["t"], "Listo")

    def test_only_current_codex_database_is_modified(self):
        path = codex_session(self.codex)
        for version in (5, 6):
            with closing(sqlite3.connect(self.codex / f"state_{version}.sqlite")) as conn, conn:
                conn.execute(
                    "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
                )
                conn.execute(
                    "INSERT INTO threads VALUES (?, ?, ?, 0, NULL)",
                    ("codex-one", str(path), f"Title {version}"),
                )
        store = self.store()
        row = store.scan()[0]
        self.assertEqual(row.title, "Title 6")
        self.assertFalse(store.trash([row.id]).errors)
        with closing(sqlite3.connect(self.codex / "state_5.sqlite")) as conn, conn:
            self.assertEqual(conn.execute("SELECT archived FROM threads").fetchone()[0], 0)

    def test_codex_restore_updates_current_index_after_upgrade(self):
        path = codex_session(self.codex)
        db = self.codex / "state_5.sqlite"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO threads VALUES (?, ?, 'Title', 0, NULL)", ("codex-one", str(path))
            )
        store = self.store()
        store.trash([store.scan()[0].id])
        with (
            closing(sqlite3.connect(db)) as old,
            closing(sqlite3.connect(self.codex / "state_6.sqlite")) as new,
        ):
            old.backup(new)
        self.assertFalse(store.restore([store.list_trash()[0].id]).errors)
        with closing(sqlite3.connect(self.codex / "state_6.sqlite")) as conn, conn:
            self.assertEqual(
                conn.execute("SELECT rollout_path, archived FROM threads").fetchone(),
                (str(path), 0),
            )

    def test_locked_codex_index_rolls_back_files_and_allows_retry(self):
        path = codex_session(self.codex)
        db = self.codex / "state_5.sqlite"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO threads VALUES (?, ?, 'Title', 0, NULL)", ("codex-one", str(path))
            )
        store = self.store()
        sid = store.scan()[0].id
        blocker = sqlite3.connect(db)
        try:
            blocker.execute("BEGIN")
            blocker.execute("SELECT * FROM threads").fetchall()
            result = store.trash([sid])
            self.assertEqual(len(result.errors), 1)
            self.assertTrue(path.exists())
            self.assertEqual(store.list_trash(), [])
        finally:
            blocker.close()
        self.assertFalse(store.trash([sid]).errors)

    def test_codex_recovery_after_interruption_before_index_update(self):
        path = codex_session(self.codex)
        db = self.codex / "state_5.sqlite"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO threads VALUES (?, ?, 'Title', 0, NULL)", ("codex-one", str(path))
            )
        store = self.store()
        sid = store.scan()[0].id
        with patch.object(store.index, "update", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                store.trash([sid])
        restarted = self.store()
        result = restarted.restore([restarted.list_trash()[0].id])
        self.assertFalse(result.errors)
        self.assertTrue(path.exists())

    def test_codex_parsing_ignores_instructions_and_duplicate_events(self):
        from session_desk.sessions import extract_codex

        path = codex_session(self.codex)
        with path.open("a") as f:
            f.write('broken json\nnull\n{"payload": []}\n')
        row = extract_codex(path, grep="todas")
        self.assertEqual(row["provider"], "codex")
        self.assertEqual(row["first"], "Mejora la búsqueda")
        self.assertEqual(row["msgs"], 2)
        self.assertEqual(row["last"][-1]["r"], "a")
        self.assertIn("todas las sesiones", row["match"])

    def test_both_providers_with_same_session_id_remain_distinct(self):
        claude_session(self.claude, "same")
        codex_session(self.codex, "same")
        rows = self.store().scan()
        self.assertEqual({r.provider for r in rows}, {"claude", "codex"})
        self.assertEqual(len({r.id for r in rows}), 2)

    def test_refresh_reuses_unchanged_transcripts_but_reads_new_messages(self):
        path = claude_session(self.claude)
        store = self.store()
        self.assertEqual(store.scan()[0].message_count, 2)
        original_open = Path.open

        def reject_transcript_reads(candidate, *args, **kwargs):
            if candidate == path:
                raise AssertionError("Unchanged transcript was read again")
            return original_open(candidate, *args, **kwargs)

        with patch.object(Path, "open", reject_transcript_reads):
            self.assertEqual(store.scan()[0].message_count, 2)
        with path.open("a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "Otro mensaje"}}) + "\n")
        self.assertEqual(store.scan()[0].message_count, 3)

    def test_trash_and_restore_survive_restart_with_claude_sidecars(self):
        path = claude_session(self.claude)
        sidecar = path.with_suffix("") / "subagents" / "agent.jsonl"
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text("subagent")
        store = self.store()
        row = store.scan()[0]
        result = store.trash([row.id])
        self.assertFalse(result.errors)
        self.assertFalse(path.exists())
        self.assertFalse(sidecar.exists())
        restarted = self.store()
        entries = restarted.list_trash()
        self.assertEqual(len(entries), 1)
        restored = restarted.restore([entries[0].id])
        self.assertFalse(restored.errors)
        self.assertEqual(sidecar.read_text(), "subagent")
        self.assertEqual(len(restarted.scan()), 1)
        self.assertEqual(restarted.list_trash(), [])

    def test_modified_session_is_not_moved(self):
        path = claude_session(self.claude)
        store = self.store()
        row = store.scan()[0]
        with path.open("a") as f:
            f.write("{}\n")
        result = store.trash([row.id])
        self.assertEqual(len(result.errors), 1)
        self.assertTrue(path.exists())

    def test_unknown_ids_and_symlink_transcripts_cannot_move_arbitrary_files(self):
        outside = self.root / "private.jsonl"
        outside.write_text("private")
        link = self.claude / "projects" / "project" / "link.jsonl"
        link.parent.mkdir(parents=True)
        link.symlink_to(outside)
        store = self.store()
        self.assertEqual(store.scan(), [])
        result = store.trash([str(outside)])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(outside.read_text(), "private")

    def test_restore_never_overwrites_a_new_session(self):
        path = claude_session(self.claude)
        store = self.store()
        store.trash([store.scan()[0].id])
        path.write_text("new session")
        entry = store.list_trash()[0]
        result = store.restore([entry.id])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(path.read_text(), "new session")
        self.assertEqual(len(store.list_trash()), 1)

    def test_restore_race_does_not_overwrite_a_session_created_after_validation(self):
        path = claude_session(self.claude)
        store = self.store()
        store.trash([store.scan()[0].id])
        entry = store.list_trash()[0]
        real_exists = Path.exists

        def create_after_check(candidate):
            exists = real_exists(candidate)
            if candidate == path and not exists:
                candidate.write_text("new concurrent session")
            return exists

        with patch.object(Path, "exists", create_after_check):
            result = store.restore([entry.id])
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(path.read_text(), "new concurrent session")
        self.assertEqual(len(store.list_trash()), 1)

    def test_codex_index_is_archived_and_restored_without_losing_metadata(self):
        path = codex_session(self.codex)
        db = self.codex / "state_5.sqlite"
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, title TEXT, archived INTEGER, archived_at INTEGER)"
            )
            conn.execute(
                "INSERT INTO threads VALUES (?, ?, ?, 0, NULL)",
                ("codex-one", str(path), "Título personalizado"),
            )
        store = self.store()
        row = store.scan()[0]
        self.assertEqual(row.title, "Título personalizado")
        self.assertFalse(store.trash([row.id]).errors)
        with closing(sqlite3.connect(db)) as conn, conn:
            self.assertEqual(conn.execute("SELECT archived FROM threads").fetchone()[0], 1)
        result = store.restore([store.list_trash()[0].id])
        self.assertFalse(result.errors)
        with closing(sqlite3.connect(db)) as conn, conn:
            self.assertEqual(
                conn.execute(
                    "SELECT rollout_path, archived, archived_at, title FROM threads"
                ).fetchone(),
                (str(path), 0, None, "Título personalizado"),
            )


if __name__ == "__main__":
    unittest.main()
