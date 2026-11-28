from __future__ import annotations

import datetime
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from urllib.request import url2pathname

from ..models import Message, Session
from .common import records, snippet, timestamp

VARIANTS = {"cli": "antigravity-cli", "app": "antigravity", "ide": "antigravity-ide"}
NATIVE_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
TRANSCRIPTS = ("transcript_full.jsonl", "transcript.jsonl")


def project_path(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        workspaces = json.loads(value)
        if isinstance(workspaces, list):
            for item in workspaces:
                if not isinstance(item, str):
                    continue
                uri = urlsplit(item)
                if uri.scheme == "file" and uri.netloc in ("", "localhost"):
                    return url2pathname(uri.path)
    except ValueError:
        pass
    return ""


def read_steps(
    path: Path, *, checkpoint: Callable[[], None] | None = None
) -> tuple[list[Message], float]:
    messages: list[Message] = []
    latest = 0.0
    for step in records(path, checkpoint=checkpoint):
        role = {"USER_INPUT": "user", "PLANNER_RESPONSE": "assistant"}.get(str(step.get("type")))
        content = step.get("content")
        if role and isinstance(content, str) and content.strip():
            messages.append({"role": role, "text": content.strip()})
            latest = max(latest, timestamp(step.get("created_at")))
    return messages, latest


def summaries(path: Path) -> dict[str, sqlite3.Row]:
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        columns = {row[1] for row in db.execute("PRAGMA table_info(conversation_summaries)")}
        if "conversation_id" not in columns:
            raise ValueError("Unrecognized Antigravity summaries schema")
        fields = [
            key if key in columns else f"NULL AS {key}"
            for key in ("title", "preview", "workspace_uris", "last_modified_time")
        ]
        return {
            row["conversation_id"]: row
            for row in db.execute(
                f"SELECT conversation_id, {', '.join(fields)} FROM conversation_summaries"
            )
            if isinstance(row["conversation_id"], str)
            and NATIVE_ID.fullmatch(row["conversation_id"])
        }


def discover(
    state,
    grep: str | None = None,
    *,
    previews: bool = True,
    known: dict[str, Session] | None = None,
    consume: Callable[[Session, list[Message], float], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> list[Session]:
    sessions = []
    home = state.roots["antigravity"]
    for variant, directory in VARIANTS.items():
        root = home / directory
        database = root / "conversation_summaries.db"
        metadata = {}
        if database.exists():
            try:
                metadata = summaries(state.safe(database, home))
            except (OSError, ValueError, sqlite3.Error) as error:
                state.warn("antigravity_metadata", error, database)
        folders = {
            path.name: path / ".system_generated" / "logs"
            for path in (root / "brain").glob("*")
            if NATIVE_ID.fullmatch(path.name)
        }
        opaque = {
            path.stem: path
            for path in sorted(
                (root / "conversations").glob("*"), key=lambda path: path.suffix, reverse=True
            )
            if path.suffix in (".db", ".pb") and NATIVE_ID.fullmatch(path.stem)
        }
        for sid in sorted(folders.keys() | metadata.keys() | opaque.keys()):
            if checkpoint is not None:
                checkpoint()
            logs = folders.get(sid)
            transcript = next(
                (logs / name for name in TRANSCRIPTS if logs and (logs / name).is_file()), None
            )
            info = dict(metadata[sid]) if sid in metadata else {}
            source = transcript or opaque.get(sid) or database
            try:
                state.safe(source, home)
                fingerprint = state.fingerprint(source)
                version = ":".join(map(str, fingerprint)) + ":" + source.name
                identifier = state.identifier("antigravity", root / "brain" / sid)
                previous = (known or {}).get(identifier)
                changed = previous is None or previous.version != version
                cache_key = str(source)
                cached = state.cache.get(cache_key) if transcript and (previews or grep) else None
                if cached and cached[0] == fingerprint:
                    messages, latest = cached[2]
                elif transcript and (previews or grep or (consume is not None and changed)):
                    messages, latest = read_steps(transcript, checkpoint=checkpoint)
                    if state.fingerprint(source) != fingerprint:
                        state.warn("changed_during_scan", "File changed during scan", source)
                        continue
                    if previews and consume is None:
                        state.cache[cache_key] = (fingerprint, None, (messages, latest))
                else:
                    messages, latest = [], 0.0
                first = next(
                    (message["text"] for message in messages if message["role"] == "user"), ""
                )
                observed = max(latest, timestamp(info.get("last_modified_time")))
                modified = observed or fingerprint[2] / 1_000_000_000
                title = info.get("title")
                preview = info.get("preview")
                hit = next(
                    (
                        result
                        for message in messages
                        if grep and (result := snippet(message["text"], grep))
                    ),
                    "",
                )
                session = Session(
                    id=identifier,
                    session_id=sid,
                    provider="antigravity",
                    title=title[:300] if isinstance(title, str) else "",
                    first_message=(first or (preview if isinstance(preview, str) else ""))[:300],
                    project_path=project_path(info.get("workspace_uris")),
                    file_path=str(source),
                    branch="",
                    updated_at=datetime.datetime.fromtimestamp(modified).astimezone().isoformat(),
                    timestamp=int(modified),
                    size_bytes=fingerprint[1] if transcript or sid in opaque else 0,
                    message_count=len(messages) if transcript and (previews or grep) else None,
                    prompt_count=sum(message["role"] == "user" for message in messages)
                    if transcript and (previews or grep)
                    else None,
                    messages=[
                        {"role": message["role"], "text": message["text"][:600]}
                        for message in (messages[-10:] if previews else [])
                    ],
                    match=hit,
                    version=version,
                    variant=variant,
                    has_transcript=transcript is not None,
                    activity_source="recorded" if observed else "file",
                )
            except (OSError, ValueError) as error:
                state.warn("antigravity_read", error, source)
                continue
            if changed and consume is not None:
                consume(session, messages, latest)
            sessions.append(session)
    return sessions
