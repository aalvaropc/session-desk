from __future__ import annotations

import datetime
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any, Iterator, Optional
from urllib.parse import parse_qs, unquote

from .models import Session
from .rendering import build_catalog, read_asset, render_page
from .services.workspace import Workspace, workspace_key
from .sessions import SessionStore

PROVIDERS = {"all", "claude", "codex", "antigravity"}

SESSION_ID = re.compile(r"[a-z]+:[0-9a-f]{64}")


class IndexCancelled(RuntimeError):
    pass


class PanelServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    def __init__(
        self,
        store: SessionStore,
        port: int,
        project: Optional[str],
        search: Optional[str],
        demo: bool,
        instance_id: Optional[str],
        index_path: Optional[Path],
    ) -> None:
        self.store_lock = threading.RLock()
        self.workspace: Optional[Workspace] = None
        self.index_progress: dict[str, str | int] = {"phase": "idle"}
        self.index_thread: threading.Thread | None = None
        self.index_cancelled = threading.Event()
        self.index_revision = 0
        self.index_ready = False
        self.background_index = index_path if not search and not demo else None
        super().__init__(("127.0.0.1", port), PanelHandler)
        self.store = store
        self.project = project
        self.search = search
        self.mode = "demo" if demo else "local"
        self.instance_id = instance_id
        self.stopping = False
        self.token = secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        try:
            self.workspace = Workspace(store, index_path) if not demo else None
        except Exception:
            super().server_close()
            raise

    def server_close(self) -> None:
        self.index_cancelled.set()
        super().server_close()
        if self.index_thread is not None:
            self.index_thread.join()
        with self.store_lock:
            if self.workspace is not None:
                self.workspace.close()
                self.workspace = None

    def bootstrap(self) -> dict[str, Any]:
        return {
            "sessions": [],
            "memories": [],
            "trash": [],
            "notes": [],
            "warnings": [],
            "generated_at": datetime.datetime.now().astimezone().isoformat(),
            "mode": self.mode,
            "token": self.token,
            "paged": True,
            "workspace_id": workspace_key(self.store),
            "background_index": self.background_index is not None,
        }

    def refresh_workspace(self) -> dict[str, Any]:
        workspace = self.workspace
        if workspace is None:
            return self.catalog()
        self.index_progress = {"phase": "scan", "revision": self.index_revision}
        try:
            workspace.refresh(grep=self.search, progress=self.report_index_progress)
        finally:
            self.index_progress = {"phase": "idle", "revision": self.index_revision}
        library = self.build_library(self.store, list(workspace.rows.values()))
        workspace.library = library
        return library

    def build_library(self, store: SessionStore, rows: list[Session]) -> dict[str, Any]:
        library = self.bootstrap()
        memories = store.memories()
        visible = [
            row
            for row in rows
            if (not self.project or self.project.casefold() in row.project_path.casefold())
            and (not self.search or row.match)
        ]
        origin: dict[tuple[str, str, str], str] = {}
        for row in visible:
            origin.setdefault((row.provider, row.project_path, row.session_id), row.id)
        library["memories"] = [
            {
                **memory.to_dict(),
                "origin_row_id": origin.get(
                    (memory.provider, memory.project_path, memory.origin_session_id)
                ),
            }
            for memory in memories
            if (not self.project or self.project.casefold() in memory.project_path.casefold())
            and (
                not self.search
                or self.search.casefold()
                in (f"{memory.name} {memory.description} {memory.body}".casefold())
            )
        ]
        library["trash"] = [entry.to_dict() for entry in store.list_trash()]
        library["warnings"] = [warning.to_dict() for warning in store.warnings]
        return library

    def report_index_progress(self, completed: int, total: int) -> None:
        workspace = self.workspace
        self.index_progress = {
            "phase": "index",
            "completed": completed,
            "total": total,
            "revision": self.index_revision,
            "available": len(workspace.rows) if workspace is not None else 0,
        }

    def check_index_cancelled(self) -> None:
        if self.index_cancelled.is_set():
            raise IndexCancelled

    def queue_index(self) -> None:
        if self.background_index is None or self.index_cancelled.is_set():
            return
        if self.index_thread is not None and self.index_thread.is_alive():
            return
        self.index_progress = {"phase": "scan", "revision": self.index_revision}
        self.index_thread = threading.Thread(target=self.index_in_background, daemon=True)
        self.index_thread.start()

    def index_in_background(self) -> None:
        roots = self.store.roots
        store = SessionStore(roots["claude"], roots["codex"], roots["antigravity"])
        try:
            with Workspace(store, self.background_index) as candidate:
                candidate.db.set_progress_handler(self.index_cancelled.is_set, 10000)
                candidate.refresh(
                    progress=self.report_index_progress,
                    checkpoint=self.check_index_cancelled,
                    publish=self.publish_index,
                    publish_partial=self.publish_partial_index,
                )
        except IndexCancelled:
            return
        except Exception:
            with self.store_lock:
                if not self.index_cancelled.is_set():
                    self.index_progress = {"phase": "error", "revision": self.index_revision}

    @contextmanager
    def publish_partial_index(self, candidate: Workspace) -> Iterator[None]:
        with self.store_lock:
            self.check_index_cancelled()
            workspace = self.workspace
            if workspace is None:
                raise IndexCancelled
            yield
            workspace.rows = candidate.rows
            self.index_revision += 1

    @contextmanager
    def publish_index(self, candidate: Workspace, rows: list[Session]) -> Iterator[None]:
        library = self.build_library(candidate.store, rows)
        with self.store_lock:
            self.check_index_cancelled()
            workspace = self.workspace
            if workspace is None:
                raise IndexCancelled
            yield
            self.store = candidate.store
            workspace.store = candidate.store
            workspace.rows = candidate.rows
            workspace.library = library
            self.index_revision += 1
            self.index_ready = True
            self.index_progress = {"phase": "idle", "revision": self.index_revision}

    def index_is_running(self) -> bool:
        return self.background_index is not None and self.index_progress["phase"] in (
            "scan",
            "index",
        )

    def ready_workspace(self) -> Workspace:
        workspace = self.workspace
        if workspace is None:
            raise ValueError("This feature requires a local workspace")
        if workspace.library is None:
            if self.background_index is None:
                self.refresh_workspace()
            else:
                self.store.registry.update(workspace.rows)
                workspace.library = self.build_library(self.store, list(workspace.rows.values()))
                self.queue_index()
        return workspace

    def visible_session(self, identifier: str) -> bool:
        workspace = self.ready_workspace()
        row = workspace.rows.get(identifier)
        return bool(
            row
            and (not self.project or self.project.casefold() in row.project_path.casefold())
            and (not self.search or row.match)
        )

    def catalog(self) -> dict[str, Any]:
        return build_catalog(
            self.store, mode=self.mode, token=self.token, project=self.project, search=self.search
        )


class PanelHandler(BaseHTTPRequestHandler):
    server: PanelServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args: Any) -> None:
        pass

    def reply(
        self, status: int, data: Any, content_type: str = "application/json; charset=utf-8"
    ) -> None:
        if isinstance(data, bytes):
            body = data
        elif content_type.startswith("text/"):
            body = data.encode("utf-8")
        else:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; font-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed(self, token: bool = False) -> bool:
        if self.headers.get("Host") != self.server.origin[7:]:
            return False
        if self.headers.get("Origin") not in (None, self.server.origin):
            return False
        if self.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none"):
            return False
        return not token or secrets.compare_digest(
            self.headers.get("X-Panel-Token", "").encode("utf-8"), self.server.token.encode("ascii")
        )

    def do_GET(self) -> None:
        if not self.allowed(token=self.path.startswith("/api/")):
            self.reply(403, {"error": "Local access is not authorized", "code": "unauthorized"})
            return
        if self.path == "/" and self.server.mode == "local":
            self.reply(200, render_page(self.server.bootstrap()), "text/html; charset=utf-8")
            return
        if self.path == "/api/progress":
            self.reply(200, self.server.index_progress)
            return
        if self.path == "/api/status":
            self.reply(
                200,
                {
                    "application": "session-desk",
                    "instance_id": self.server.instance_id,
                    "pid": os.getpid(),
                    "url": self.server.origin,
                    "mode": self.server.mode,
                },
            )
            return
        if self.path.startswith("/assets/"):
            try:
                content, content_type = read_asset(self.path[len("/assets/") :])
                self.reply(200, content, content_type)
            except (FileNotFoundError, IsADirectoryError):
                self.reply(404, {"error": "Asset not found"})
            return
        with self.server.store_lock:
            try:
                self.get_workspace()
            except (ValueError, OverflowError):
                self.reply(400, {"error": "Invalid workspace query", "code": "invalid_request"})
            except (OSError, sqlite3.Error):
                self.reply(503, {"error": "Workspace storage could not be read"})

    def get_workspace(self) -> None:
        path, _, query = self.path.partition("?")
        params = parse_qs(query, max_num_fields=12, keep_blank_values=True)
        if path == "/" and not query:
            self.reply(200, render_page(self.server.catalog()), "text/html; charset=utf-8")
        elif path == "/api/catalog":
            workspace = self.server.workspace
            if workspace is not None and self.server.background_index is not None:
                library = self.server.ready_workspace().library
                if params.get("cached") != ["1"]:
                    self.server.queue_index()
            elif (
                workspace is not None
                and workspace.library is not None
                and params.get("cached") == ["1"]
            ):
                library = workspace.library
            else:
                library = self.server.refresh_workspace()
            assert library is not None
            if self.server.workspace is not None:
                notes = self.server.workspace.notes()
                self.scope_note_links(notes)
                library = {
                    **library,
                    "notes": notes,
                    "index_revision": self.server.index_revision,
                    "index_ready": self.server.index_ready,
                }
            self.reply(200, library)
        elif path == "/api/trash":
            self.reply(200, [entry.to_dict() for entry in self.server.store.list_trash()])
        elif path in ("/api/sessions", "/api/search", "/api/activity"):
            self.get_session_list(path, {key: values[-1] for key, values in params.items()})
        elif match := re.fullmatch(r"/api/sessions/([^/]+)(/messages)?", path):
            identifier = unquote(match.group(1))
            if not SESSION_ID.fullmatch(identifier):
                self.reply(404, {"error": "Session not found", "code": "not_found"})
                return
            if match.group(2) and "offset" not in params:
                self.get_full_messages(identifier)
                return
            if not self.server.visible_session(identifier):
                self.reply(404, {"error": "Session not found", "code": "not_found"})
                return
            workspace = self.server.ready_workspace()
            if not match.group(2):
                self.reply(200, workspace.session_detail(identifier))
                return
            offset = int(params["offset"][-1])
            if not 0 <= offset <= 10_000_000:
                raise ValueError("Invalid offset")
            if (
                params.get("version", [workspace.rows[identifier].version])[-1]
                != workspace.rows[identifier].version
            ):
                self.reply(409, {"error": "Conversation changed. Refresh the workspace."})
                return
            page = workspace.message_page(identifier, offset)
            if page is None:
                self.reply(503, {"error": "Conversation could not be read"})
            else:
                self.reply(200, page)
        else:
            self.reply(404, {"error": "Route not found"})

    def get_full_messages(self, identifier: str) -> None:
        try:
            if self.server.background_index is not None:
                if not self.server.visible_session(identifier):
                    raise KeyError(identifier)
                workspace = self.server.ready_workspace()
                self.reply(200, {"messages": workspace.full_messages(identifier)})
                return
            if (
                (self.server.project or self.server.search)
                and self.server.workspace is not None
                and not self.server.visible_session(identifier)
            ):
                raise KeyError(identifier)
            if identifier not in self.server.store.registry and self.server.workspace is not None:
                self.server.ready_workspace()
            self.reply(200, {"messages": self.server.store.messages(identifier)})
        except KeyError:
            self.reply(404, {"error": "Session not found", "code": "not_found"})
        except (OSError, ValueError):
            self.reply(503, {"error": "Conversation could not be read"})

    def get_session_list(self, path: str, params: dict[str, str]) -> None:
        workspace = self.server.ready_workspace()
        provider = params.get("provider", "all")
        if provider not in PROVIDERS:
            raise ValueError("Unknown provider")
        project_scope = self.server.project or ""
        grep_scope = bool(self.server.search)
        if path == "/api/activity":
            days = int(params.get("days", "7"))
            if days not in (7, 30):
                raise ValueError("Invalid activity range")
            self.reply(200, workspace.activity(days, provider, project_scope, grep_scope))
            return
        query = params.get("q", "") if path == "/api/search" else ""
        offset = int(params.get("offset", "0"))
        sort = params.get("sort", "updated")
        review = params.get("review", "all")
        if (
            len(query) > 500
            or not 0 <= offset <= 10_000_000
            or sort not in ("title", "updated")
            or review not in ("all", "keep", "pending")
        ):
            raise ValueError("Invalid session filter")
        self.reply(
            200,
            workspace.page(
                query=query,
                provider=provider,
                project=params.get("project", ""),
                review=review,
                sort=sort,
                ascending=params.get("ascending") == "1",
                offset=offset,
                project_scope=project_scope,
                grep_scope=grep_scope,
            ),
        )

    def do_POST(self) -> None:
        if not self.allowed(token=True):
            self.reply(403, {"error": "Local access is not authorized", "code": "unauthorized"})
            return
        if self.path not in (
            "/api/trash",
            "/api/restore",
            "/api/shutdown",
            "/api/reviews",
            "/api/notes",
        ):
            self.reply(404, {"error": "Route not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < length <= 1024 * 1024
                or self.headers.get_content_type() != "application/json"
            ):
                raise ValueError("A bounded JSON request is required")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/api/shutdown":
                if (
                    not self.server.instance_id
                    or not isinstance(payload, dict)
                    or payload.get("instance_id") != self.server.instance_id
                ):
                    self.reply(403, {"error": "Managed instance identity does not match"})
                    return
                with self.server.store_lock:
                    self.server.stopping = True
                    self.reply(200, {"stopping": True})
                    self.server.shutdown()
                return
            if self.path in ("/api/reviews", "/api/notes"):
                with self.server.store_lock:
                    if self.server.stopping:
                        self.reply(503, {"error": "Workspace is shutting down"})
                        return
                    if self.reject_during_index():
                        return
                    self.save_workspace_data(payload)
                return
            identifiers = payload.get("ids") if isinstance(payload, dict) else None
            if (
                not isinstance(identifiers, list)
                or not 0 < len(identifiers) <= 10000
                or any(
                    not isinstance(identifier, str) or not identifier for identifier in identifiers
                )
            ):
                raise ValueError("Select at least one valid item")
            with self.server.store_lock:
                if self.server.stopping:
                    self.reply(503, {"error": "Workspace is shutting down"})
                    return
                if self.reject_during_index():
                    return
                if self.server.background_index is not None and not self.server.index_ready:
                    self.reply(
                        409,
                        {
                            "error": "Refresh the workspace successfully before moving history files.",
                            "code": "index_not_ready",
                        },
                    )
                    return
                if self.path == "/api/trash":
                    versions = payload.get("versions")
                    if not isinstance(versions, dict) or any(
                        not isinstance(key, str) or not isinstance(value, str)
                        for key, value in versions.items()
                    ):
                        raise ValueError("Item versions are required; refresh the panel")
                    kind = payload.get("kind", "session")
                    if kind not in ("session", "memory"):
                        raise ValueError("Unknown item kind")
                    for identifier in identifiers:
                        item = self.server.store.registry.get(identifier)
                        if item and versions.get(identifier) != item.version:
                            self.reply(
                                409,
                                {
                                    "error": "Items changed; refresh the panel before moving them",
                                    "code": "stale_version",
                                },
                            )
                            return
                    result = self.server.store.trash(identifiers, versions=versions, kind=kind)
                else:
                    result = self.server.store.restore(identifiers)
                if self.server.workspace is not None:
                    self.server.workspace.library = None
                    self.server.refresh_workspace()
                self.reply(200, result.to_dict())
        except (OSError, sqlite3.Error):
            self.reply(503, {"error": "Workspace storage could not be updated"})
        except (ValueError, TypeError, UnicodeError) as error:
            self.reply(400, {"error": str(error), "code": "invalid_request"})

    def reject_during_index(self) -> bool:
        if not self.server.index_is_running():
            return False
        self.reply(
            409,
            {
                "error": "Wait for the history update to finish before editing the workspace.",
                "code": "index_in_progress",
            },
        )
        return True

    def scope_note_links(self, notes: list[dict[str, Any]]) -> None:
        if not self.server.project and not self.server.search:
            return
        workspace = self.server.ready_workspace()
        visible = {
            row.id
            for row in workspace.scoped_rows(self.server.project or "", bool(self.server.search))
        }
        for note in notes:
            note["source_available"] = note["source_available"] and note["session_id"] in visible

    def save_workspace_data(self, payload: Any) -> None:
        workspace = self.server.workspace
        if workspace is None:
            raise ValueError("This feature requires a local workspace")
        if not isinstance(payload, dict):
            raise ValueError("Invalid workspace data")
        if self.path == "/api/reviews":
            values = payload.get("reviews")
            migrate = payload.get("migrate") is True
            if (
                not isinstance(values, dict)
                or len(values) > 10000
                or any(
                    not SESSION_ID.fullmatch(key) or value not in ("keep", "pending")
                    for key, value in values.items()
                )
            ):
                raise ValueError("Invalid review values")
            if not migrate and any(not self.server.visible_session(key) for key in values):
                raise ValueError("Session not found")
            workspace.set_reviews(values, migrate=migrate)
            self.reply(200, {"saved": True})
            return
        note_id = payload.get("id")
        identifier = payload.get("session_id", "")
        position = payload.get("position", 0)
        title = payload.get("title")
        body = payload.get("body")
        if (
            not isinstance(title, str)
            or not 0 < len(title.strip()) <= 200
            or not isinstance(body, str)
            or not 0 < len(body.strip()) <= 50000
            or (
                note_id is not None
                and (not isinstance(note_id, str) or not re.fullmatch(r"[0-9a-f]{32}", note_id))
            )
            or not isinstance(identifier, str)
            or type(position) is not int
            or position < 0
            or (note_id is None and not self.server.visible_session(identifier))
        ):
            raise ValueError("Invalid note")
        if note_id is None and payload.get("version") != workspace.rows[identifier].version:
            self.reply(409, {"error": "Conversation changed. Refresh the workspace."})
            return
        note = workspace.save_note(note_id, identifier, position, title.strip(), body.strip())
        self.scope_note_links([note])
        self.reply(200, note)


def make_server(
    store: SessionStore,
    port: int = 8765,
    project: Optional[str] = None,
    grep: Optional[str] = None,
    demo: bool = False,
    instance_id: Optional[str] = None,
    *,
    index_path: Optional[Path] = None,
) -> PanelServer:
    return PanelServer(store, port, project, grep, demo, instance_id, index_path)
