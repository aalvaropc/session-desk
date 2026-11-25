from __future__ import annotations

import json
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from typing import Any, Optional

from .rendering import build_catalog, read_asset, render_page
from .sessions import SessionStore


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
    ) -> None:
        super().__init__(("127.0.0.1", port), PanelHandler)
        self.store = store
        self.project = project
        self.search = search
        self.mode = "demo" if demo else "local"
        self.instance_id = instance_id
        self.stopping = False
        self.token = secrets.token_urlsafe(32)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        self.store_lock = threading.RLock()

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
            if self.path == "/":
                self.reply(200, render_page(self.server.catalog()), "text/html; charset=utf-8")
            elif self.path == "/api/catalog":
                self.reply(200, self.server.catalog())
            elif self.path == "/api/trash":
                self.reply(200, [entry.to_dict() for entry in self.server.store.list_trash()])
            elif match := re.fullmatch(r"/api/sessions/([a-z]+:[0-9a-f]{64})/messages", self.path):
                try:
                    self.reply(200, {"messages": self.server.store.messages(match.group(1))})
                except KeyError:
                    self.reply(404, {"error": "Session not found", "code": "not_found"})
                except (OSError, ValueError):
                    self.reply(500, {"error": "Conversation could not be read"})
            else:
                self.reply(404, {"error": "Route not found"})

    def do_POST(self) -> None:
        if not self.allowed(token=True):
            self.reply(403, {"error": "Local access is not authorized", "code": "unauthorized"})
            return
        if self.path not in ("/api/trash", "/api/restore", "/api/shutdown"):
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
                self.reply(200, result.to_dict())
        except (ValueError, TypeError, UnicodeError) as error:
            self.reply(400, {"error": str(error), "code": "invalid_request"})


def make_server(
    store: SessionStore,
    port: int = 8765,
    project: Optional[str] = None,
    grep: Optional[str] = None,
    demo: bool = False,
    instance_id: Optional[str] = None,
) -> PanelServer:
    return PanelServer(store, port, project, grep, demo, instance_id)
