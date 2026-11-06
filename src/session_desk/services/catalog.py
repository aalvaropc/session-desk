from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Optional

from ..models import Memory, Session
from ..providers.codex import extract_codex


class Catalog:
    def __init__(self, state, index):
        self.state = state
        self.index = index

    def scan(self, grep: Optional[str] = None) -> list[Session]:
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
            try:
                self.state.safe(path, self.state.roots[provider])
                before = self.state.fingerprint(path)
                cached = self.state.cache.get(str(path))
                if cached and cached[0] == before and cached[1] == grep:
                    raw = dict(cached[2])
                else:
                    raw = (
                        extract(str(path), hist, grep)
                        if provider == "claude"
                        else extract_codex(path, grep)
                    )
                cache[str(path)] = (before, grep, dict(raw))
                sid = raw.get("sid", raw["id"])
                if not isinstance(sid, str):
                    raise ValueError("Identificador de sesión inválido")
                if provider == "codex":
                    idx = metadata.get(sid, {})
                    title = idx.get("title") or idx.get("name") or ""
                    branch = idx.get("git_branch") or raw["branch"]
                    raw["title"] = title if isinstance(title, str) else ""
                    raw["branch"] = branch if isinstance(branch, str) else ""
                for key in ("title", "first", "proj", "branch", "match"):
                    if not isinstance(raw[key], str):
                        raw[key] = ""

                if before != self.state.fingerprint(path):
                    self.state.warn("changed_during_scan", "File changed during scan", path)
                    continue
                version = ":".join(map(str, before))
                row = Session(
                    self.state.identifier(provider, path),
                    sid,
                    provider,
                    raw["title"],
                    raw["first"],
                    raw["proj"],
                    str(path),
                    raw["branch"],
                    datetime.datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                        timespec="seconds"
                    ),
                    raw["ts"],
                    before[1],
                    raw["msgs"],
                    raw["prompts"],
                    [
                        {"role": "user" if m["r"] == "u" else "assistant", "text": m["t"]}
                        for m in raw["last"]
                    ],
                    raw["match"],
                    version,
                )
                if provider == "codex":
                    indexed_path = metadata.get(sid, {}).get("rollout_path")
                    index_paths[row.id] = indexed_path if isinstance(indexed_path, str) else None
                registry[row.id] = row
                fingerprints[row.id] = before
                rows.append(row)
            except (OSError, ValueError, TypeError) as error:
                self.state.warn("session_read", error, path)
        self.state.registry = {
            key: value for key, value in self.state.registry.items() if isinstance(value, Memory)
        }
        self.state.registry.update(registry)
        self.state.fingerprints.update(fingerprints)
        self.state.cache = cache
        self.state.index_paths = index_paths
        return sorted(rows, key=lambda row: row.timestamp, reverse=True)

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
