from __future__ import annotations

import base64
import datetime
import json
import re
from importlib import resources
from typing import Any, Optional

from .sessions import SessionStore


def read_resource(name: str) -> bytes:
    root = resources.files("session_desk").joinpath("web")
    return root.joinpath(name).read_bytes()


def read_asset(name: str) -> tuple[bytes, str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise FileNotFoundError(name)
    if name == "styles.css":
        return read_resource(name), "text/css; charset=utf-8"
    content_types = {
        ".js": "text/javascript; charset=utf-8",
        ".woff2": "font/woff2",
        ".svg": "image/svg+xml",
    }
    extension = "." + name.rsplit(".", 1)[-1]
    if extension not in content_types:
        raise FileNotFoundError(name)
    return read_resource("assets/" + name), content_types[extension]


def build_catalog(
    store: SessionStore,
    mode: str = "local",
    token: Optional[str] = None,
    project: Optional[str] = None,
    search: Optional[str] = None,
) -> dict[str, Any]:
    sessions = store.scan(grep=search)
    memories = store.memories()
    if project:
        needle = project.casefold()
        sessions = [session for session in sessions if needle in session.project_path.casefold()]
        memories = [memory for memory in memories if needle in memory.project_path.casefold()]
    if search:
        needle = search.casefold()
        sessions = [session for session in sessions if session.match]
        memories = [
            memory
            for memory in memories
            if needle in f"{memory.name} {memory.description} {memory.body}".casefold()
        ]
    trash = store.list_trash()
    return {
        "sessions": [session.to_dict() for session in sessions],
        "memories": [memory.to_dict() for memory in memories],
        "trash": [entry.to_dict() for entry in trash],
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": mode,
        "token": token if mode == "local" else None,
        "warnings": [warning.to_dict() for warning in store.warnings],
    }


def render_page(catalog: dict[str, Any], standalone: bool = False) -> str:
    template = read_resource("index.html").decode("utf-8")
    if standalone:
        styles = read_resource("styles.css").decode("utf-8")
        for weight in (400, 500, 600):
            filename = f"plex-{weight}.woff2"
            encoded = base64.b64encode(read_resource("assets/" + filename)).decode("ascii")
            styles = re.sub(
                r"(?:(?:/)?assets/)?" + re.escape(filename),
                "data:font/woff2;base64," + encoded,
                styles,
            )
        script = read_resource("assets/app.js").decode("utf-8").replace("</script", "<\\/script")
        style_tag = "<style>" + styles + "</style>"
        script_tag = "<script>" + script + "</script>"
    else:
        style_tag = '<link rel="stylesheet" href="/assets/styles.css">'
        script_tag = '<script defer src="/assets/app.js"></script>'
    serialized = (
        json.dumps(catalog, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    substitutions = {"__APP_DATA__": serialized, "__STYLES__": style_tag, "__SCRIPT__": script_tag}
    return re.sub(
        r"__APP_DATA__|__STYLES__|__SCRIPT__", lambda match: substitutions[match.group()], template
    )
