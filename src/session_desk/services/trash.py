from __future__ import annotations

import datetime
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Mapping, Optional, Sequence

from ..models import BatchResult, Memory, Session, TrashEntry


class TrashService:
    def __init__(self, state, index):
        self.state = state
        self.index = index

    def _write_manifest(self, folder, manifest):
        pending = folder / "manifest.tmp"
        pending.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        pending.replace(folder / "manifest.json")

    def _move(self, source, destination):
        if source.is_file():
            os.link(source, destination, follow_symlinks=False)
            source.unlink()
        else:
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(f"Destination already exists: {destination}")
            source.rename(destination)

    def _snapshot(self, source):
        paths = [source]
        if source.is_dir():
            paths.extend(sorted(source.rglob("*")))
        snapshot = []
        for path in paths:
            if path.is_symlink():
                raise ValueError("La sesión contiene enlaces simbólicos")
            snapshot.append([str(path.relative_to(source)), *self.state.fingerprint(path)])
        return snapshot

    def _trash_one(self, sid, versions=None, kind="session"):
        if sid not in self.state.registry:
            raise ValueError("Sesión desconocida; actualiza el panel")
        row = self.state.registry[sid]
        if (
            (kind == "session" and not isinstance(row, Session))
            or (kind == "memory" and not isinstance(row, Memory))
            or kind not in ("session", "memory")
        ):
            raise ValueError("Tipo de entrada incorrecto")
        if row.provider == "antigravity":
            raise ValueError("Antigravity sessions are read-only")
        if versions is not None and versions.get(sid) != row.version:
            raise ValueError("La versión cambió; actualiza el panel")
        root = self.state.roots[row.provider]
        path = self.state.safe(row.file_path, root)
        if self.state.fingerprint(path) != self.state.fingerprints[sid]:
            raise ValueError("La sesión cambió; actualiza el panel y vuelve a revisarla")
        sources = [path]
        sidecar = path.with_suffix("")
        if kind == "session" and row.provider == "claude" and sidecar.exists():
            self.state.safe(sidecar, root)
            if any(p.is_symlink() for p in sidecar.rglob("*")):
                raise ValueError("La sesión contiene enlaces simbólicos")
            sources.append(sidecar)
        indexes = []
        if kind == "session" and row.provider == "codex":
            indexed_rows = self.index.rows(row.session_id)
            snapshot_path = self.state.index_paths.get(sid)
            current_path = indexed_rows[0][1]["rollout_path"] if indexed_rows else None
            if current_path != snapshot_path:
                raise ValueError("El índice Codex cambió; actualiza el panel")
            if isinstance(snapshot_path, str) and Path(snapshot_path).resolve() == path:
                for db, idx in indexed_rows:
                    indexes.append(
                        {
                            "db": db.name,
                            "rollout_path": idx["rollout_path"],
                            "archived": idx["archived"],
                            "archived_at": idx["archived_at"],
                        }
                    )
        entry_id = uuid.uuid4().hex
        parent = self.state.safe(root / "trash" / "sessions-panel", root)
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder = parent / entry_id
        folder.mkdir(mode=0o700)
        manifest = {
            "id": entry_id,
            "provider": row.provider,
            "kind": kind,
            "session": row.to_dict(),
            "deleted_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "moves": [str(p.relative_to(root)) for p in sources],
            "snapshots": [self._snapshot(p) for p in sources],
            "indexes": indexes,
        }
        moved = []
        try:
            self._write_manifest(folder, manifest)
            for i, source in enumerate(sources):
                self._move(source, folder / str(i))
                moved.append((source, folder / str(i)))
            self.index.update(manifest, str(folder / "0"), restoring=False)
        except Exception:
            for original, backup in reversed(moved):
                self._move(backup, original)
            for file in folder.iterdir():
                file.unlink()
            folder.rmdir()
            raise
        self.state.registry.pop(sid, None)

    def _trash_entries(self):
        entries = {}
        for provider in ("claude", "codex"):
            root = self.state.roots[provider]
            for file in (root / "trash" / "sessions-panel").glob("*/manifest.json"):
                try:
                    self.state.safe(file, root)
                    manifest = json.loads(file.read_text(encoding="utf-8"))
                    if (
                        not isinstance(manifest, dict)
                        or manifest.get("id") != file.parent.name
                        or manifest.get("provider") != provider
                    ):
                        raise ValueError("Invalid manifest identity")
                    if (
                        not isinstance(manifest.get("session"), dict)
                        or not isinstance(manifest.get("moves"), list)
                        or not manifest["moves"]
                        or not all(isinstance(v, str) for v in manifest["moves"])
                        or not isinstance(manifest.get("indexes"), list)
                        or not isinstance(manifest.get("deleted_at"), str)
                        or manifest.get("kind", "session") not in ("session", "memory")
                    ):
                        raise ValueError("Invalid manifest structure")
                    row = manifest["session"]
                    if not isinstance(
                        row.get("size_bytes", row.get("kb", 0)), (int, float)
                    ) or not all(
                        isinstance(row.get(key, ""), str)
                        for key in (
                            "title",
                            "first",
                            "first_message",
                            "sid",
                            "session_id",
                            "name",
                            "proj",
                            "project_path",
                        )
                    ):
                        raise ValueError("Invalid manifest metadata")
                    for index in manifest["indexes"]:
                        if (
                            not isinstance(index, dict)
                            or not {"rollout_path", "archived", "archived_at"} <= index.keys()
                            or not isinstance(index["rollout_path"], str)
                        ):
                            raise ValueError("Invalid manifest index")
                    if manifest["indexes"] and not isinstance(
                        row.get("session_id", row.get("sid")), str
                    ):
                        raise ValueError("Missing session identifier")
                    entries[manifest["id"]] = (file.parent, manifest)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    self.state.warn("invalid_manifest", error, file)
        return entries

    def list_trash(self) -> list[TrashEntry]:
        entries = []
        for folder, manifest in self._trash_entries().values():
            row = manifest["session"]
            kind = manifest.get("kind", "session")
            title = (
                row.get("name")
                if kind == "memory"
                else row.get("title")
                or row.get("first_message")
                or row.get("first")
                or row.get("session_id")
                or row.get("sid")
                or ""
            )
            entries.append(
                TrashEntry(
                    manifest["id"],
                    kind,
                    manifest["provider"],
                    title or "",
                    row.get("project_path", row.get("proj", "")),
                    manifest["deleted_at"],
                    row.get("size_bytes", row.get("kb", 0) * 1024),
                )
            )
        return sorted(entries, key=lambda row: row.deleted_at, reverse=True)

    def _restore_one(self, entry_id):
        entries = self._trash_entries()
        if entry_id not in entries:
            raise ValueError("Entrada de papelera desconocida")
        folder, manifest = entries[entry_id]
        root = self.state.roots[manifest["provider"]]
        pairs = []
        redundant_backups = []
        snapshots = manifest.get("snapshots")
        for i, relative in enumerate(manifest["moves"]):
            destination = self.state.safe(root / relative, root)
            backup = self.state.safe(folder / str(i), root)
            if destination.exists():
                if (
                    not isinstance(snapshots, list)
                    or i >= len(snapshots)
                    or self._snapshot(destination) != snapshots[i]
                ):
                    raise ValueError("Ya existe una sesión en el destino; no se sobrescribió")
                if backup.exists():
                    if destination.is_dir() and backup.is_dir() and not any(backup.iterdir()):
                        redundant_backups.append(backup)
                    elif (
                        destination.is_file()
                        and backup.is_file()
                        and os.path.samefile(destination, backup)
                    ):
                        redundant_backups.append(backup)
                    else:
                        raise ValueError("Ya existe una sesión en el destino; no se sobrescribió")
                continue
            if not backup.exists():
                raise ValueError("Falta un archivo de la papelera")
            pairs.append((backup, destination))
        moved = []
        try:
            for backup, destination in pairs:
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._move(backup, destination)
                moved.append((backup, destination))
            self.index.update(manifest, str(folder / "0"), restoring=True)
        except Exception:
            for backup, destination in reversed(moved):
                self._move(destination, backup)
            raise
        for backup in redundant_backups:
            if backup.is_dir():
                backup.rmdir()
            else:
                backup.unlink()
        (folder / "manifest.json").unlink()
        folder.rmdir()

    def _batch(self, ids, action):
        result = BatchResult([], [])
        for sid in dict.fromkeys(ids):
            try:
                action(sid)
                result.done.append(sid)
            except (OSError, ValueError, sqlite3.Error) as error:
                result.errors.append({"id": sid, "code": "operation_failed", "message": str(error)})
        return result

    def trash(
        self,
        ids: Sequence[str],
        versions: Optional[Mapping[str, str]] = None,
        kind: str = "session",
    ) -> BatchResult:
        return self._batch(ids, lambda sid: self._trash_one(sid, versions, kind))

    def restore(self, ids: Sequence[str]) -> BatchResult:
        return self._batch(ids, self._restore_one)
