from __future__ import annotations

import datetime
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
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


@dataclass(frozen=True)
class AntigravitySource:
    path: Path
    root: Path
    variant: str
    session_id: str
    info: dict[str, Any]
    transcript: bool
    has_file: bool


def discover(state) -> Iterator[AntigravitySource]:
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
            logs = folders.get(sid)
            transcript = next(
                (logs / name for name in TRANSCRIPTS if logs and (logs / name).is_file()), None
            )
            info = dict(metadata[sid]) if sid in metadata else {}
            yield AntigravitySource(
                transcript or opaque.get(sid) or database,
                root,
                variant,
                sid,
                info,
                transcript is not None,
                transcript is not None or sid in opaque,
            )


def inspect_source(
    state,
    item: AntigravitySource,
    grep: str | None,
    *,
    previews: bool,
    known: dict[str, Session] | None,
    index_messages: bool,
    checkpoint: Callable[[], None] | None,
) -> tuple[Session, list[Message], float, bool] | None:
    source, root, variant, sid, info = (
        item.path,
        item.root,
        item.variant,
        item.session_id,
        item.info,
    )
    try:
        state.safe(source, state.roots["antigravity"])
        fingerprint = state.fingerprint(source)
        version = ":".join(map(str, fingerprint)) + ":" + source.name
        identifier = state.identifier("antigravity", root / "brain" / sid)
        previous = (known or {}).get(identifier)
        changed = previous is None or previous.version != version
        cache_key = str(source)
        cached = state.cache.get(cache_key) if item.transcript and (previews or grep) else None
        if cached and cached[0] == fingerprint:
            messages, latest = cached[2]
        elif item.transcript and (previews or grep or (index_messages and changed)):
            messages, latest = read_steps(source, checkpoint=checkpoint)
            if state.fingerprint(source) != fingerprint:
                state.warn("changed_during_scan", "File changed during scan", source)
                return None
            if previews and not index_messages:
                state.cache[cache_key] = (fingerprint, None, (messages, latest))
        else:
            messages, latest = [], 0.0
        first = next((message["text"] for message in messages if message["role"] == "user"), "")
        observed = max(latest, timestamp(info.get("last_modified_time")))
        modified = observed or fingerprint[2] / 1_000_000_000
        title = info.get("title")
        preview = info.get("preview")
        hit = next(
            (result for message in messages if grep and (result := snippet(message["text"], grep))),
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
            size_bytes=fingerprint[1] if item.has_file else 0,
            message_count=len(messages) if item.transcript and (previews or grep) else None,
            prompt_count=sum(message["role"] == "user" for message in messages)
            if item.transcript and (previews or grep)
            else None,
            messages=[
                {"role": message["role"], "text": message["text"][:600]}
                for message in (messages[-10:] if previews else [])
            ],
            match=hit,
            version=version,
            variant=variant,
            has_transcript=item.transcript,
            activity_source="recorded" if observed else "file",
        )
    except (OSError, ValueError) as error:
        state.warn("antigravity_read", error, source)
        return None
    return session, messages, latest, changed
