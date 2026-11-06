from __future__ import annotations

from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

from .models import BatchResult, Memory, ScanWarning, Session, TrashEntry
from .providers.codex import extract_codex
from .providers.codex_index import CodexIndex
from .providers.common import readable, records, snippet, text_content
from .services.catalog import Catalog
from .services.state import StoreState
from .services.trash import TrashService

__all__ = ["SessionStore", "extract_codex", "readable", "records", "snippet", "text_content"]


class SessionStore:
    def __init__(
        self,
        claude_home: Optional[Union[str, Path]] = None,
        codex_home: Optional[Union[str, Path]] = None,
    ) -> None:
        self._state = StoreState(claude_home, codex_home)
        self.index = CodexIndex(self._state)
        self._catalog = Catalog(self._state, self.index)
        self._trash = TrashService(self._state, self.index)

    @property
    def roots(self) -> dict[str, Path]:
        return self._state.roots

    @property
    def registry(self) -> dict[str, Union[Session, Memory]]:
        return self._state.registry

    @property
    def warnings(self) -> list[ScanWarning]:
        return self._state.warnings

    def scan(self, grep: Optional[str] = None) -> list[Session]:
        return self._catalog.scan(grep)

    def memories(self) -> list[Memory]:
        return self._catalog.memories()

    def trash(
        self,
        ids: Sequence[str],
        versions: Optional[Mapping[str, str]] = None,
        kind: str = "session",
    ) -> BatchResult:
        return self._trash.trash(ids, versions, kind)

    def restore(self, ids: Sequence[str]) -> BatchResult:
        return self._trash.restore(ids)

    def list_trash(self) -> list[TrashEntry]:
        return self._trash.list_trash()
