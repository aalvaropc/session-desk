from __future__ import annotations

import collections
import datetime
from pathlib import Path


def extract_codex(path, grep=None):
    from .common import readable, records, snippet, text_content

    path = Path(path)
    meta = {}
    messages: collections.deque[dict[str, str]] = collections.deque(maxlen=10)
    events: collections.deque[dict[str, str]] = collections.deque(maxlen=10)
    first = event_first = match = event_match = ""
    count = event_count = 0
    for obj in records(path):
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        typ = obj.get("type")
        if typ == "session_meta":
            meta = payload
        if typ == "response_item" and payload.get("type") == "message":
            role = payload.get("role")
            text = text_content(payload.get("content")).strip()
            if role not in ("user", "assistant") or not readable(text):
                continue
            count += 1
            if role == "user" and not first:
                first = text
            messages.append({"r": "u" if role == "user" else "a", "t": text[:600]})
            if grep and not match:
                match = snippet(text, grep)
        elif typ == "event_msg" and payload.get("type") in ("user_message", "agent_message"):
            text = payload.get("message")
            if not isinstance(text, str) or not readable(text):
                continue
            role = "u" if payload["type"] == "user_message" else "a"
            event_count += 1
            if role == "u" and not event_first:
                event_first = text
            events.append({"r": role, "t": text[:600]})
            if grep and not event_match:
                event_match = snippet(text, grep)
    sid = meta.get("id") or meta.get("session_id")
    if not isinstance(sid, str) or not sid:
        raise ValueError("Transcript de Codex sin identificador")
    st = path.stat()
    git = meta.get("git")
    if not isinstance(git, dict):
        git = {}
    return {
        "id": "codex:" + sid,
        "sid": sid,
        "provider": "codex",
        "file": str(path),
        "proj": meta.get("cwd") or "(sin proyecto)",
        "branch": git.get("branch") or "",
        "date": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "ts": int(st.st_mtime),
        "kb": st.st_size // 1024,
        "msgs": count or event_count,
        "prompts": 0,
        "title": "",
        "first": (first or event_first).replace("\n", " ")[:300],
        "last": list(messages if count else events),
        "match": match or event_match,
    }
