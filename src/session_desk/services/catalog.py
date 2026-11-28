from __future__ import annotations

import datetime
import sqlite3
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from ..models import Memory, Message, Session
from ..providers.antigravity import discover, read_steps
from ..providers.codex import extract_codex


class Catalog:
    def __init__(self, state, index):
        self.state = state
        self.index = index

    def scan(
        self,
        grep: Optional[str] = None,
        *,
        previews: bool = True,
        known: dict[str, Session] | None = None,
        consume: Callable[[Session, list[Message], float], None] | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> list[Session]:
        from ..providers.claude import extract, load_history

        self.state.warnings = []
        try:
            hist = load_history(str(self.state.roots["claude"] / "history.jsonl"))
        except OSError as error:
            self.state.warn("history_read", error, self.state.roots["claude"] / "history.jsonl")
            hist = {}
        metadata = {}
        try:
            metadata = {row["id"]: row for _, row in self.index.rows()}
        except (sqlite3.Error, ValueError, OSError) as error:
            self.state.warn("codex_index", error)
        rows, registry, fingerprints, cache, index_paths = [], {}, {}, {}, {}
        paths = [("claude", p) for p in self.state.roots["claude"].glob("projects/*/*.jsonl")]
        for sub in ("sessions", "archived_sessions"):
            paths.extend(("codex", p) for p in (self.state.roots["codex"] / sub).rglob("*.jsonl"))
        for provider, path in paths:
            if checkpoint is not None:
                checkpoint()
            try:
                self.state.safe(path, self.state.roots[provider])
                before = self.state.fingerprint(path)
                version = ":".join(map(str, before))
                identifier = self.state.identifier(provider, path)
                previous = (known or {}).get(identifier)
                reusable = (
                    previous
                    if previous is not None
                    and previous.version == version
                    and not grep
                    and (provider != "codex" or previous.source_branch is not None)
                    else None
                )
                if reusable is not None:
                    row = replace(reusable, match="", messages=[])
                    if provider == "codex":
                        idx = metadata.get(row.session_id, {})
                        title, branch, indexed_path = self.codex_fields(idx, row.source_branch)
                        row.title, row.branch = title, branch
                        index_paths[row.id] = indexed_path
                    registry[row.id] = row
                    fingerprints[row.id] = before
                    rows.append(row)
                    continue

                dialogue: list[Message] = []
                changed = previous is None or previous.version != version
                cached = self.state.cache.get(str(path))
                if consume is not None and changed:
                    raw = (
                        extract(
                            str(path),
                            hist,
                            grep,
                            dialogue=dialogue,
                            previews=previews,
                            checkpoint=checkpoint,
                        )
                        if provider == "claude"
                        else extract_codex(path, grep, dialogue=dialogue, checkpoint=checkpoint)
                    )
                elif cached and cached[0] == before and cached[1] == grep:
                    raw = dict(cached[2])
                else:
                    raw = (
                        extract(str(path), hist, grep)
                        if provider == "claude"
                        else extract_codex(path, grep)
                    )
                if consume is None or previews:
                    cache[str(path)] = (before, grep, dict(raw))
                sid = raw.get("sid", raw["id"])
                if not isinstance(sid, str):
                    raise ValueError("Identificador de sesión inválido")
                source_branch = raw["branch"] if isinstance(raw["branch"], str) else ""
                if provider == "codex":
                    title, branch, indexed_path = self.codex_fields(
                        metadata.get(sid, {}), source_branch
                    )
                    raw["title"], raw["branch"] = title, branch
                    index_paths[identifier] = indexed_path
                for key in ("title", "first", "proj", "branch", "match"):
                    if not isinstance(raw[key], str):
                        raw[key] = ""

                if before != self.state.fingerprint(path):
                    self.state.warn("changed_during_scan", "File changed during scan", path)
                    continue
                row = Session(
                    identifier,
                    sid,
                    provider,
                    raw["title"],
                    raw["first"],
                    raw["proj"],
                    str(path),
                    raw["branch"],
                    datetime.datetime.fromtimestamp(
                        raw.get("activity") or before[2] / 1_000_000_000
                    )
                    .astimezone()
                    .isoformat(timespec="seconds"),
                    int(raw.get("activity") or raw["ts"]),
                    before[1],
                    raw["msgs"],
                    raw["prompts"],
                    [
                        {"role": "user" if m["r"] == "u" else "assistant", "text": m["t"]}
                        for m in (raw["last"] if previews else [])
                    ],
                    raw["match"],
                    version,
                    activity_source="recorded" if raw.get("activity") else "file",
                    source_branch=source_branch,
                )
            except (OSError, ValueError, TypeError) as error:
                self.state.warn("session_read", error, path)
                continue
            if consume is not None and changed:
                consume(row, dialogue, 0.0)
            registry[row.id] = row
            fingerprints[row.id] = before
            rows.append(row)
        self.state.registry = {
            key: value for key, value in self.state.registry.items() if isinstance(value, Memory)
        }
        antigravity = discover(
            self.state, grep, previews=previews, known=known, consume=consume, checkpoint=checkpoint
        )
        for row in antigravity:
            registry[row.id] = row
            if row.file_path in self.state.cache:
                cache[row.file_path] = self.state.cache[row.file_path]
        rows.extend(antigravity)
        self.state.registry.update(registry)
        self.state.fingerprints.update(fingerprints)
        self.state.cache = cache
        self.state.index_paths = index_paths
        return sorted(rows, key=lambda row: row.timestamp, reverse=True)

    @staticmethod
    def codex_fields(idx: dict, source_branch: str | None) -> tuple[str, str, str | None]:
        title = idx.get("title") or idx.get("name")
        branch = idx.get("git_branch") or source_branch
        path = idx.get("rollout_path")
        return (
            title if isinstance(title, str) else "",
            branch if isinstance(branch, str) else "",
            path if isinstance(path, str) else None,
        )

    def conversation(self, identifier: str) -> tuple[list[Message], float]:
        from ..providers.claude import load_messages
        from ..providers.codex import load_codex_messages

        row = self.state.registry.get(identifier)
        if not isinstance(row, Session):
            raise KeyError(identifier)
        if not row.has_transcript:
            return [], 0.0
        path = self.state.safe(Path(row.file_path), self.state.roots[row.provider])
        before = self.state.fingerprint(path)
        version = ":".join(map(str, before))
        if row.version not in (version, version + ":" + path.name):
            raise ValueError("Conversation changed; refresh the workspace")
        latest = 0.0
        if row.provider == "antigravity":
            messages, latest = read_steps(path)
        elif row.provider == "claude":
            messages = load_messages(str(path))
        else:
            messages = load_codex_messages(path)
        if self.state.fingerprint(path) != before:
            raise ValueError("Conversation changed; refresh the workspace")
        return messages, latest

    def memories(self) -> list[Memory]:
        from ..providers.claude import extract_memory

        project_map: dict[str, str] = {}
        for row in self.state.registry.values():
            if isinstance(row, Session) and row.provider == "claude":
                project_map.setdefault(str(Path(row.file_path).parent), row.project_path)
        result = []
        for path in self.state.roots["claude"].glob("projects/*/memory/*.md"):
            if path.name == "MEMORY.md":
                continue
            try:
                self.state.safe(path, self.state.roots["claude"])
                before = self.state.fingerprint(path)
                raw = extract_memory(str(path), project_map)
                if before != self.state.fingerprint(path):
                    self.state.warn("changed_during_scan", "File changed during scan", path)
                    continue
                row = Memory(
                    self.state.identifier("claude", path),
                    "claude",
                    raw["name"],
                    raw["description"],
                    raw["type"],
                    raw["origin"],
                    raw["body"],
                    raw["proj"],
                    str(path),
                    datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                        timespec="seconds"
                    ),
                    raw["ts"],
                    before[1],
                    ":".join(map(str, before)),
                )
                self.state.registry[row.id] = row
                self.state.fingerprints[row.id] = before
                result.append(row)
            except (OSError, ValueError, TypeError) as error:
                self.state.warn("memory_read", error, path)
        return sorted(result, key=lambda row: row.timestamp, reverse=True)
