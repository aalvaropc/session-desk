import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from session_desk.sessions import SessionStore


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / "sample project"
        self.agy = self.root / "gemini"
        self.store = SessionStore(self.root / "claude", self.root / "codex", self.agy)

    def antigravity(self, variant, transcript=True):
        native_id = "b0000000-0000-0000-0000-000000000001"
        root = self.agy / variant
        logs = root / "brain" / native_id / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        with closing(sqlite3.connect(root / "conversation_summaries.db")) as db, db:
            db.execute(
                "CREATE TABLE conversation_summaries (conversation_id, title, preview, "
                "workspace_uris, last_modified_time)"
            )
            db.execute(
                "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?)",
                (
                    native_id,
                    "Synthetic title",
                    None,
                    json.dumps([self.project.as_uri()]),
                    "2026-11-27T12:00:00Z",
                ),
            )
        path = logs / "transcript_full.jsonl"
        if transcript:
            rows = [
                {"type": "USER_INPUT", "content": "first"},
                {
                    "type": "PLANNER_RESPONSE",
                    "content": "Two words/middle",
                    "step_index": 1,
                    "created_at": "2026-11-27T13:00:00Z",
                },
                {"type": "GENERIC", "content": "internal tool text"},
            ]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows) + "{", encoding="utf-8")
            path.with_name("transcript.jsonl").write_text(
                json.dumps({"type": "USER_INPUT", "content": "duplicate file"}), encoding="utf-8"
            )
        return path

    def test_antigravity_surfaces_are_distinct_and_read_only(self):
        path = self.antigravity("antigravity-cli")
        self.antigravity("antigravity")
        self.antigravity("antigravity-ide", transcript=False)
        by_variant = {session.variant: session for session in self.store.scan()}
        self.assertEqual(set(by_variant), {"cli", "app", "ide"})
        self.assertEqual(len({session.id for session in by_variant.values()}), 3)
        cli = by_variant["cli"]
        self.assertEqual(Path(cli.project_path), self.project)
        self.assertEqual(self.store.messages(cli.id)[-1]["text"], "Two words/middle")
        self.assertFalse(by_variant["ide"].has_transcript)
        before = path.read_bytes()
        self.assertTrue(self.store.trash([cli.id], {cli.id: cli.version}).errors)
        self.assertEqual(before, path.read_bytes())

    def test_index_updates_and_survives_reopen(self):
        from session_desk.services.workspace import Workspace

        transcript = self.antigravity("antigravity-cli")
        index = self.root / "index.sqlite"
        with Workspace(self.store, index) as workspace:
            workspace.refresh()
            results = workspace.page(query="words/middle")
            self.assertEqual(results["total"], 1)
            self.assertEqual(results["sessions"][0]["hit"]["position"], 1)
            self.assertEqual(results["sessions"][0]["updated_at"][:10], "2026-11-27")
            self.assertEqual(results["sessions"][0]["activity_source"], "recorded")
            workspace.fts = False
            self.assertEqual(workspace.page(query="words/middle"), results)
            identifier = results["sessions"][0]["id"]
            workspace.set_reviews({identifier: "keep"})
            note = workspace.save_note(None, identifier, 1, "Decision", "Use both")
        transcript.write_text('{"type":"USER_INPUT","content":"updated"}\n', encoding="utf-8")
        with Workspace(self.store, index) as workspace:
            workspace.refresh()
            self.assertEqual(workspace.page(query="words/middle")["total"], 0)
            self.assertEqual(workspace.page(query="updated", review="keep")["total"], 1)
            self.assertEqual(workspace.notes()[0]["id"], note["id"])
            self.assertFalse(workspace.notes()[0]["source_available"])
            workspace.refresh(rebuild=True)
            self.assertEqual(workspace.page(query="updated", review="keep")["total"], 1)
            self.assertEqual(workspace.notes()[0]["id"], note["id"])

    def test_paginated_filters_and_index_after_trash_restore(self):
        from session_desk.services.workspace import Workspace

        project = self.root / "claude" / "projects" / "sample"
        project.mkdir(parents=True)
        for i in range(51):
            record = {"type": "user", "cwd": "/sample", "message": {"content": f"Find needle {i}."}}
            (project / f"sample-{i}.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
        with Workspace(self.store) as workspace:
            workspace.refresh()
            first = workspace.page(query="needle", provider="claude", project="/sample")
            second = workspace.page(query="needle", offset=50)
            self.assertEqual(first["total"], 51)
            self.assertEqual(len(first["sessions"]), 50)
            self.assertTrue(all(row["messages"] == [] for row in first["sessions"]))
            self.assertEqual(len(second["sessions"]), 1)
            target = second["sessions"][0]
            self.assertNotIn(target["id"], {row["id"] for row in first["sessions"]})
            workspace.set_reviews({target["id"]: "keep"})
            workspace.set_reviews({target["id"]: "pending"}, migrate=True)
            self.assertEqual(workspace.session_detail(target["id"])["review"], "keep")
            trash = self.store.trash([target["id"]], {target["id"]: target["version"]})
            self.assertTrue(trash.done)
            workspace.refresh()
            self.assertEqual(workspace.page(query="needle")["total"], 50)
            restored = self.store.restore([self.store.list_trash()[0].id])
            self.assertTrue(restored.done)
            workspace.refresh()
            self.assertEqual(workspace.page(query="needle")["total"], 51)

    def test_concurrent_write_preserves_last_readable_snapshot(self):
        from session_desk.providers import antigravity
        from session_desk.services.workspace import Workspace

        transcript = self.antigravity("antigravity-cli")
        index = self.root / "workspace.sqlite3"
        with Workspace(self.store, index) as workspace:
            workspace.refresh()
            saved = workspace.page(query="words/middle")["sessions"][0]
        with transcript.open("a", encoding="utf-8") as stream:
            stream.write('\n{"type":"USER_INPUT","content":"new synthetic turn"}\n')
        read_steps = antigravity.read_steps

        def append_during_scan(path, **options):
            result = read_steps(path, **options)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            return result

        with Workspace(self.store, index) as workspace:
            with patch.object(antigravity, "read_steps", side_effect=append_during_scan):
                workspace.refresh()
            previous = workspace.page(query="words/middle")["sessions"][0]
            self.assertEqual(previous["version"], saved["version"])
            self.assertEqual(self.store.warnings[0].code, "changed_during_scan")
            workspace.refresh()
            self.assertEqual(workspace.page(query="new synthetic turn")["total"], 1)

    def test_index_tolerates_lone_surrogate_in_an_old_message(self):
        from session_desk.services.workspace import Workspace

        project = self.root / "claude" / "projects" / "sample"
        project.mkdir(parents=True)
        rows = [{"type": "assistant", "message": {"content": "malformed \ud800 older answer"}}]
        rows.extend({"type": "user", "message": {"content": "legible"}} for _ in range(12))
        (project / "damaged.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
        )
        with Workspace(self.store) as workspace:
            workspace.refresh()
            hit = workspace.page(query="older answer")["sessions"][0]
            self.assertEqual(hit["hit"]["position"], 0)
            self.assertIn("\ufffd", hit["hit"]["snippet"])

    def test_reads_each_changed_transcript_once_and_skips_unchanged_files_after_restart(self):
        from session_desk.providers import common
        from session_desk.services.workspace import Workspace

        project = self.root / "claude" / "projects" / "sample"
        project.mkdir(parents=True)
        transcript = project / "story.jsonl"
        transcript.write_text('{"type":"user","message":{"content":"first"}}\n', encoding="utf-8")
        index = self.root / "workspace.sqlite3"
        with patch.object(common, "records", wraps=common.records) as reads:
            with Workspace(self.store, index) as workspace:
                workspace.refresh()
                self.assertEqual(workspace.page(query="first")["total"], 1)
            self.assertEqual(reads.call_count, 1)
            reads.reset_mock()
            reopened = SessionStore(self.root / "claude", self.root / "codex", self.agy)
            with Workspace(reopened, index) as workspace:
                self.assertEqual(workspace.page(query="first")["total"], 1)
                workspace.refresh()
                self.assertEqual(reads.call_count, 0)
                with transcript.open("a", encoding="utf-8") as output:
                    output.write('{"type":"assistant","message":{"content":"second"}}\n')
                workspace.refresh()
                self.assertEqual(reads.call_count, 1)
                self.assertEqual(workspace.page(query="second")["total"], 1)
