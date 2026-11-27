from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    output: Path
    action: Optional[str] = None
    managed_instance: Optional[str] = None
    open_browser: bool = False
    serve: bool = False
    static: bool = False
    demo: bool = False
    port: int = 8765
    project: Optional[str] = None
    search: Optional[str] = None
    claude_home: Optional[str] = None
    codex_home: Optional[str] = None
    antigravity_home: Optional[str] = None
