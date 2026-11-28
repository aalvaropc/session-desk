from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, ContextManager

from ..models import Message, Session
from ..sessions import SessionStore

PAGE_SIZE = 50
MESSAGE_PAGE_SIZE = 40
IMPORT_BATCH_SIZE = 25
IMPORT_BATCH_SECONDS = 1.0


def normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def project_contains(project: str, path: str) -> bool:
    if not path:
        return False
    root = os.path.normcase(os.path.normpath(project))
    candidate = os.path.normcase(os.path.normpath(path))
    if root == candidate:
        return True
    if not os.path.isabs(root) and (root == "." or os.sep not in root):
        return False
    try:
        return os.path.commonpath((root, candidate)) == root
    except ValueError:
        return False


def workspace_key(store: SessionStore) -> str:
    roots = "\n".join(f"{key}={path}" for key, path in sorted(store.roots.items()))
    return hashlib.sha256(roots.encode()).hexdigest()[:24]


def workspace_path(directory: Path, store: SessionStore) -> Path:
    return directory / "workspaces" / workspace_key(store) / "workspace.sqlite3"


def result_snippet(text: str, needle: str) -> str:
    words = " ".join(text.split())
    offset = words.casefold().find(needle)
    if offset < 0:
        return words[:180]
    start = max(0, offset - 65)
    end = min(len(words), offset + len(needle) + 65)
    return ("…" if start else "") + words[start:end] + ("…" if end < len(words) else "")


class Workspace:
    def __init__(self, store: SessionStore, path: Path | None = None) -> None:
        self.store = store
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.is_symlink():
                raise ValueError("The workspace index must be a regular file")
            os.close(os.open(path, os.O_CREAT | os.O_RDWR, 0o600))
        self.db = sqlite3.connect(path if path is not None else ":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if path is not None:
            self.db.execute("PRAGMA journal_mode = WAL").fetchone()
        self.rows: dict[str, Session] = {}
        self.library: dict[str, Any] | None = None
        self.db.executescript("""
            PRAGMA foreign_keys = ON;
            PRAGMA secure_delete = ON;
            CREATE TABLE IF NOT EXISTS indexed_session (
                id TEXT PRIMARY KEY,
                version TEXT NOT NULL,
                first_message TEXT NOT NULL,
                latest REAL NOT NULL,
                count INTEGER NOT NULL,
                prompts INTEGER NOT NULL,
                snapshot TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS message (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES indexed_session(id) ON DELETE CASCADE,
                position INTEGER NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                search_text TEXT NOT NULL,
                UNIQUE(session_id, position)
            );
            CREATE TABLE IF NOT EXISTS review (
                session_id TEXT PRIMARY KEY,
                state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_initial_import (id INTEGER PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS note (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                source_text_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
        """)
        try:
            self.db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5("
                "search_text, content='message', content_rowid='rowid', tokenize='trigram')"
            )
            self.db.execute("SELECT rowid FROM message_fts LIMIT 0")
            self.fts = True
            self.db.executescript("""
                CREATE TRIGGER IF NOT EXISTS workspace_message_insert AFTER INSERT ON message BEGIN
                    INSERT INTO message_fts(rowid, search_text) VALUES (new.rowid, new.search_text);
                END;
                CREATE TRIGGER IF NOT EXISTS workspace_message_delete AFTER DELETE ON message BEGIN
                    INSERT INTO message_fts(message_fts, rowid, search_text)
                    VALUES ('delete', old.rowid, old.search_text);
                END;
            """)
            if not self.db.execute(
                "SELECT 1 FROM sqlite_schema WHERE name = 'workspace_fts_ready'"
            ).fetchone():
                with self.db:
                    self.db.execute("INSERT INTO message_fts(message_fts) VALUES ('rebuild')")
                    self.db.execute("CREATE TABLE workspace_fts_ready (version INTEGER)")
        except sqlite3.OperationalError:
            self.fts = False
            self.db.executescript("""
                DROP TRIGGER IF EXISTS workspace_message_insert;
                DROP TRIGGER IF EXISTS workspace_message_delete;
                DROP TABLE IF EXISTS workspace_fts_ready;
            """)

        self.rows = self.snapshots(
            {row["id"]: row for row in self.db.execute("SELECT * FROM indexed_session")}
        )

    @staticmethod
    def snapshots(records: dict[str, sqlite3.Row]) -> dict[str, Session]:
        return {
            identifier: Session(**json.loads(record["snapshot"]))
            for identifier, record in records.items()
        }

    def __enter__(self) -> Workspace:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        self.db.close()

    def needs_initial_import(self) -> bool:
        return (
            not self.rows
            or self.db.execute("SELECT 1 FROM pending_initial_import LIMIT 1").fetchone()
            is not None
        )

    def refresh(
        self,
        *,
        rebuild: bool = False,
        grep: str | None = None,
        progress: Callable[[int, int], None] | None = None,
        checkpoint: Callable[[], None] | None = None,
        publish: Callable[[Workspace, list[Session]], ContextManager[None]] | None = None,
        publish_partial: Callable[[Workspace], ContextManager[None]] | None = None,
    ) -> None:
        known = {item["id"]: item for item in self.db.execute("SELECT * FROM indexed_session")}
        snapshots = self.snapshots(known)
        processed = 0
        published = dict(snapshots)
        pending = 0
        last_publish = time.monotonic()
        progressive = publish_partial if self.needs_initial_import() else None

        def consume(row: Session, messages: list[Message], latest: float) -> None:
            nonlocal processed, pending, last_publish
            if checkpoint is not None:
                checkpoint()
            self.write_session(row, messages, latest)
            processed += 1
            if progressive is not None:
                published[row.id] = row
                pending += 1
                if (
                    processed == 1
                    or pending >= IMPORT_BATCH_SIZE
                    or time.monotonic() - last_publish >= IMPORT_BATCH_SECONDS
                ):
                    with progressive(self):
                        self.db.commit()
                        self.rows = dict(published)
                    pending = 0
                    last_publish = time.monotonic()
            if progress is not None:
                progress(processed, 0)

        with self.db:
            if progressive is not None:
                self.db.execute("INSERT OR IGNORE INTO pending_initial_import VALUES (1)")
            rows = {
                row.id: row
                for row in self.store.scan(
                    grep=grep,
                    previews=False,
                    known={} if rebuild else snapshots,
                    consume=consume,
                    checkpoint=checkpoint,
                    recent_first=progressive is not None,
                )
            }
            unstable = {
                warning.path
                for warning in self.store.warnings
                if warning.code == "changed_during_scan"
            }
            for identifier in snapshots.keys() - rows.keys():
                previous = snapshots[identifier]
                if previous.file_path in unstable and Path(previous.file_path).is_file():
                    if not grep:
                        rows[identifier] = previous
                else:
                    self.db.execute("DELETE FROM indexed_session WHERE id = ?", (identifier,))
            for identifier, row in rows.items():
                previous_record = known.get(identifier)
                if (
                    not rebuild
                    and previous_record is not None
                    and previous_record["version"] == row.version
                ):
                    self.apply_metadata(row, previous_record)
                    # Reuse the saved messages while keeping provider metadata changes durable.
                    if row != snapshots[identifier]:
                        self.db.execute(
                            "UPDATE indexed_session SET snapshot = ? WHERE id = ?",
                            (json.dumps(row.to_dict(), ensure_ascii=False), identifier),
                        )
            if progress is not None:
                progress(len(rows), len(rows))
            if checkpoint is not None:
                checkpoint()
            self.db.execute("DELETE FROM pending_initial_import")
            with publish(self, list(rows.values())) if publish is not None else nullcontext():
                self.db.commit()
                self.rows = rows

    def write_session(self, row: Session, messages: list[Message], latest: float) -> None:
        stats = {
            "first_message": next(
                (message["text"][:300] for message in messages if message["role"] == "user"), ""
            ),
            "latest": latest,
            "count": len(messages),
            "prompts": sum(message["role"] == "user" for message in messages),
        }
        self.apply_metadata(row, stats)
        self.db.execute("DELETE FROM indexed_session WHERE id = ?", (row.id,))
        self.db.execute(
            """INSERT INTO indexed_session VALUES (:id, :version, :first_message,
               :latest, :count, :prompts, :snapshot)""",
            {
                "id": row.id,
                "version": row.version,
                **stats,
                "snapshot": json.dumps(row.to_dict(), ensure_ascii=False),
            },
        )
        self.db.executemany(
            "INSERT INTO message(session_id, position, role, text, search_text) VALUES (?, ?, ?, ?, ?)",
            (
                (row.id, position, message["role"], message["text"], normalized(message["text"]))
                for position, message in enumerate(messages)
            ),
        )

    @staticmethod
    def apply_metadata(row: Session, stats: Any) -> None:
        if not row.first_message:
            row.first_message = stats["first_message"]
        if row.has_transcript:
            row.message_count = stats["count"]
            row.prompt_count = stats["prompts"]
        latest = stats["latest"]
        if latest and (row.activity_source != "recorded" or latest > row.timestamp):
            row.timestamp = int(latest)
            row.updated_at = datetime.datetime.fromtimestamp(latest).astimezone().isoformat()
            row.activity_source = "recorded"

    def session_detail(self, identifier: str) -> dict[str, Any]:
        review = self.db.execute(
            "SELECT state FROM review WHERE session_id = ?", (identifier,)
        ).fetchone()
        return {**self.rows[identifier].to_dict(), "review": review[0] if review else "pending"}

    def set_reviews(self, values: dict[str, str], *, migrate: bool = False) -> None:
        operation = "INSERT OR IGNORE" if migrate else "INSERT OR REPLACE"
        with self.db:
            self.db.executemany(f"{operation} INTO review VALUES (?, ?)", values.items())

    def page(
        self,
        *,
        query: str = "",
        provider: str = "all",
        project: str = "",
        review: str = "all",
        sort: str = "updated",
        ascending: bool = False,
        offset: int = 0,
        project_scope: str = "",
        grep_scope: bool = False,
    ) -> dict[str, Any]:
        available = self.scoped_rows(project_scope, grep_scope)
        reviews = dict(self.db.execute("SELECT session_id, state FROM review"))
        projects = sorted({row.project_path for row in available if row.project_path})
        needle = normalized(query)
        rows = [
            row
            for row in available
            if (provider == "all" or row.provider == provider)
            and (not project or project_contains(project, row.project_path))
            and (review == "all" or reviews.get(row.id, "pending") == review)
        ]
        hits = self.hits(needle) if needle and rows else {}
        if needle:
            rows = [
                row
                for row in rows
                if row.id in hits
                or needle
                in normalized(
                    " ".join(
                        (row.title, row.first_message, row.project_path, row.branch, row.session_id)
                    )
                )
            ]
        if sort == "title":
            rows.sort(
                key=lambda row: (normalized(row.title or row.first_message), row.id),
                reverse=not ascending,
            )
        else:
            rows.sort(key=lambda row: (row.timestamp, row.id), reverse=not ascending)
        paged = rows[offset : offset + PAGE_SIZE]
        snippets = self.snippets(needle, [hits[row.id] for row in paged if row.id in hits])
        return {
            "sessions": [
                {
                    **row.to_dict(),
                    "hit": snippets.get(row.id),
                    "review": reviews.get(row.id, "pending"),
                }
                for row in paged
            ],
            "total": len(rows),
            "catalog_total": len(available),
            "projects": projects,
        }

    def scoped_rows(self, project: str, grep: bool) -> list[Session]:
        return [
            row
            for row in self.rows.values()
            if (not project or project.casefold() in row.project_path.casefold())
            and (not grep or row.match)
        ]

    def hits(self, needle: str) -> dict[str, int]:
        indexed = self.fts and len(needle) >= 3 and "\x00" not in needle
        source = (
            "message JOIN message_fts ON message.rowid = message_fts.rowid"
            if indexed
            else "message"
        )
        condition = "message_fts MATCH ? AND " if indexed else ""
        phrase = '"' + needle.replace('"', '""') + '"'
        parameters = (phrase, needle) if indexed else (needle,)
        return dict(
            self.db.execute(
                f"""SELECT message.session_id, min(message.rowid) FROM {source}
                    WHERE {condition}instr(message.search_text, ?) > 0 GROUP BY message.session_id""",
                parameters,
            )
        )

    def snippets(self, needle: str, matches: list[int]) -> dict[str, dict[str, Any]]:
        placeholders = ", ".join("?" for _ in matches)
        if not matches:
            return {}
        return {
            row["session_id"]: {
                "position": row["position"],
                "snippet": result_snippet(row["text"], needle),
            }
            for row in self.db.execute(
                f"SELECT session_id, position, text FROM message WHERE rowid IN ({placeholders})",
                matches,
            )
        }

    def full_messages(self, identifier: str) -> list[Message]:
        return [
            {"role": row["role"], "text": row["text"]}
            for row in self.db.execute(
                "SELECT role, text FROM message WHERE session_id = ? ORDER BY position",
                (identifier,),
            )
        ]

    def message_page(self, identifier: str, offset: int) -> dict[str, Any] | None:
        if not self.db.execute(
            "SELECT 1 FROM indexed_session WHERE id = ?", (identifier,)
        ).fetchone():
            return None
        count = self.db.execute(
            "SELECT count(*) FROM message WHERE session_id = ?", (identifier,)
        ).fetchone()[0]
        messages = [
            dict(row)
            for row in self.db.execute(
                "SELECT role, text FROM message WHERE session_id = ? ORDER BY position LIMIT ? OFFSET ?",
                (identifier, MESSAGE_PAGE_SIZE, offset),
            )
        ]
        references = self.db.execute(
            """SELECT (SELECT max(position) FROM message WHERE session_id = ? AND role = 'user'),
                      (SELECT max(position) FROM message WHERE session_id = ? AND role = 'assistant')""",
            (identifier, identifier),
        ).fetchone()
        context = {}
        for role, position in zip(("user", "assistant"), references):
            if position is not None:
                text = self.db.execute(
                    "SELECT text FROM message WHERE session_id = ? AND position = ?",
                    (identifier, position),
                ).fetchone()[0]
                context[role] = {"position": position, "text": text}
        return {"messages": messages, "total": count, "offset": offset, "context": context}

    def activity(self, days: int, provider: str, project: str, grep: bool) -> list[dict[str, Any]]:
        cutoff = time.time() - days * 86400
        groups: dict[str, dict[str, Any]] = {}
        for row in sorted(
            self.scoped_rows(project, grep), key=lambda item: item.timestamp, reverse=True
        ):
            if row.timestamp < cutoff or (provider != "all" and row.provider != provider):
                continue
            path = os.path.normcase(os.path.normpath(row.project_path)) if row.project_path else ""
            group = groups.setdefault(path, {"project": path, "sessions": []})
            group["sessions"].append(
                {
                    "id": row.id,
                    "title": row.title or row.first_message,
                    "provider": row.provider,
                    "updated_at": row.updated_at,
                    "activity_source": row.activity_source,
                }
            )
        return list(groups.values())

    def source_hash(self, identifier: str, position: int) -> str | None:
        row = self.db.execute(
            "SELECT role, text FROM message WHERE session_id = ? AND position = ?",
            (identifier, position),
        ).fetchone()
        return (
            hashlib.sha256((row["role"] + "\n" + row["text"]).encode()).hexdigest() if row else None
        )

    def notes(self) -> list[dict[str, Any]]:
        notes = []
        for row in self.db.execute("SELECT * FROM note ORDER BY updated_at DESC, id"):
            item = dict(row)
            source = item.pop("source_text_hash")
            item["source_available"] = (
                self.source_hash(item["session_id"], item["position"]) == source
            )
            notes.append(item)
        return notes

    def save_note(
        self, note_id: str | None, identifier: str, position: int, title: str, body: str
    ) -> dict[str, Any]:
        with self.db:
            if note_id:
                result = self.db.execute(
                    "UPDATE note SET title = ?, body = ?, updated_at = ? WHERE id = ?",
                    (title, body, int(time.time()), note_id),
                )
                if not result.rowcount:
                    raise ValueError("Note not found")
            else:
                digest = self.source_hash(identifier, position)
                if digest is None:
                    raise ValueError("Message is no longer available")
                note_id = uuid.uuid4().hex
                self.db.execute(
                    "INSERT INTO note VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (note_id, identifier, position, digest, title, body, int(time.time())),
                )
        return next(note for note in self.notes() if note["id"] == note_id)
