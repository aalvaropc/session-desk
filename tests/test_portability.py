import builtins
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_sessions import claude_session

from session_desk.sessions import SessionStore


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.claude = self.root / "claude"
        self.store = SessionStore(self.claude, self.root / "codex")

    def sidecar_session(self):
        transcript = claude_session(self.claude)
        sidecar = transcript.with_suffix("")
        artifact = sidecar / "subagents" / "worker.jsonl"
        artifact.parent.mkdir(parents=True)
        artifact.write_text("saved tool result", encoding="utf-8")
        return transcript, sidecar, artifact

    def test_directory_moves_work_when_rename_rejects_existing_destinations(self):
        transcript, _, artifact = self.sidecar_session()
        session = self.store.scan()[0]
        original_rename = Path.rename

        def windows_rename(source, target):
            if source.is_dir() and Path(target).exists():
                raise FileExistsError("Destination already exists")
            return original_rename(source, target)

        with patch.object(Path, "rename", windows_rename):
            self.assertFalse(self.store.trash([session.id]).errors)
            entry = self.store.list_trash()[0]
            self.assertFalse(self.store.restore([entry.id]).errors)
        self.assertTrue(transcript.exists())
        self.assertEqual(artifact.read_text(encoding="utf-8"), "saved tool result")

    def test_interruption_before_directory_rename_is_recoverable(self):
        transcript, sidecar, artifact = self.sidecar_session()
        session = self.store.scan()[0]
        original_rename = Path.rename
        canonical_sidecar = sidecar.resolve()

        def interrupted_rename(source, target):
            if source == canonical_sidecar:
                raise KeyboardInterrupt
            return original_rename(source, target)

        with patch.object(Path, "rename", interrupted_rename):
            with self.assertRaises(KeyboardInterrupt):
                self.store.trash([session.id])
        entry = self.store.list_trash()[0]
        self.assertFalse(self.store.restore([entry.id]).errors)
        self.assertTrue(transcript.exists())
        self.assertEqual(artifact.read_text(encoding="utf-8"), "saved tool result")

    def test_empty_directory_reservation_from_interrupted_move_can_recover(self):
        transcript, sidecar, artifact = self.sidecar_session()
        session = self.store.scan()[0]
        original_move = self.store._trash._move
        canonical_sidecar = sidecar.resolve()

        def interrupted_move(source, destination):
            if source == canonical_sidecar:
                destination.mkdir()
                raise KeyboardInterrupt
            original_move(source, destination)

        with patch.object(self.store._trash, "_move", interrupted_move):
            with self.assertRaises(KeyboardInterrupt):
                self.store.trash([session.id])
        entry = self.store.list_trash()[0]
        self.assertFalse(self.store.restore([entry.id]).errors)
        self.assertTrue(transcript.exists())
        self.assertEqual(artifact.read_text(encoding="utf-8"), "saved tool result")

    def test_utf8_manifest_restores_accented_filename_with_non_utf8_locale(self):
        transcript = claude_session(self.claude, "sesión")
        session = self.store.scan()[0]
        self.assertFalse(self.store.trash([session.id]).errors)
        original_read = Path.read_text

        def locale_read(path, *arguments, **keywords):
            keywords.setdefault("encoding", "cp1252")
            return original_read(path, *arguments, **keywords)

        with patch.object(Path, "read_text", locale_read):
            entry = self.store.list_trash()[0]
            self.assertFalse(self.store.restore([entry.id]).errors)
        self.assertTrue(transcript.exists())
        self.assertEqual(self.store.list_trash(), [])

    def test_provider_text_uses_utf8_independently_of_platform_locale(self):
        transcript = claude_session(self.claude)
        transcript.write_text(
            json.dumps(
                {"type": "custom-title", "customTitle": "Configuración del diseño"},
                ensure_ascii=False,
            )
            + "\n"
            + json.dumps(
                {"type": "user", "cwd": "/workspace", "message": {"content": "Revisión de sesión"}},
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        memory = self.claude / "projects" / "-workspace" / "memory" / "diseño.md"
        memory.parent.mkdir(parents=True)
        memory.write_text(
            "---\nname: Guía de diseño\n---\nPreferir recuperación explícita.", encoding="utf-8"
        )
        original_path_open, original_open = Path.open, builtins.open

        def path_locale_open(path, *arguments, **keywords):
            keywords.setdefault("encoding", "cp1252")
            return original_path_open(path, *arguments, **keywords)

        def locale_open(file, *arguments, **keywords):
            keywords.setdefault("encoding", "cp1252")
            return original_open(file, *arguments, **keywords)

        with patch.object(Path, "open", path_locale_open), patch("builtins.open", locale_open):
            sessions = self.store.scan()
            memories = self.store.memories()
        self.assertEqual(sessions[0].title, "Configuración del diseño")
        self.assertEqual(sessions[0].first_message, "Revisión de sesión")
        self.assertEqual(memories[0].name, "Guía de diseño")
        self.assertIn("recuperación explícita", memories[0].body)
