from __future__ import annotations

import sqlite3
import time
from contextlib import closing


class CodexIndex:
    def __init__(self, state):
        self.state = state

    def databases(self):
        databases = [
            p for p in self.state.roots["codex"].glob("state_*.sqlite") if p.stem[6:].isdigit()
        ]
        return sorted(databases, key=lambda p: int(p.stem[6:]))[-1:]

    def rows(self, sid=None):
        found = []
        for db in self.databases():
            self.state.safe(db, self.state.roots["codex"])
            with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
                required = {"id", "rollout_path", "archived", "archived_at"}
                if not required <= cols:
                    raise ValueError("Índice Codex incompatible; no se modificó")
                query = "SELECT * FROM threads" + (" WHERE id = ?" if sid else "")
                for row in conn.execute(query, (sid,) if sid else ()):
                    found.append((db, dict(row)))
        return found

    def update(self, manifest, trash_path, restoring):
        from contextlib import ExitStack

        with ExitStack() as stack:
            for old in manifest["indexes"]:
                databases = self.databases()
                if not databases:
                    raise ValueError(
                        "No se encuentra el índice Codex; no se modificaron sus archivos"
                    )
                db = self.state.safe(databases[0], self.state.roots["codex"])
                conn = sqlite3.connect(db.as_uri() + "?mode=rw", uri=True, timeout=2)
                stack.callback(conn.close)
                stack.enter_context(conn)
                desired = (
                    (old["rollout_path"], old["archived"], old["archived_at"])
                    if restoring
                    else (trash_path, 1, int(time.time()))
                )
                expected = trash_path if restoring else old["rollout_path"]
                if restoring:
                    current = conn.execute(
                        "SELECT rollout_path, archived, archived_at FROM threads WHERE id=?",
                        (manifest["session"].get("session_id", manifest["session"].get("sid")),),
                    ).fetchone()
                    if current == desired:
                        continue
                cursor = conn.execute(
                    "UPDATE threads SET rollout_path=?, archived=?, archived_at=? WHERE id=? AND rollout_path=?",
                    (
                        *desired,
                        manifest["session"].get("session_id", manifest["session"].get("sid")),
                        expected,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("El índice Codex cambió; no se pudo modificar")
