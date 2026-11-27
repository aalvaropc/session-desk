from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..models import ScanWarning


class StoreState:
    def __init__(self, claude_home=None, codex_home=None, antigravity_home=None):
        self.roots = {
            "antigravity": Path(antigravity_home or Path.home() / ".gemini").expanduser().resolve(),
            "claude": Path(claude_home or Path.home() / ".claude").expanduser().resolve(),
            "codex": Path(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            .expanduser()
            .resolve(),
        }
        self.registry = {}
        self.fingerprints = {}
        self.cache = {}
        self.index_paths = {}
        self.warnings = []

    def safe(self, path, root):
        path = Path(path)
        if path.absolute() != path.resolve() or root not in path.parents:
            raise ValueError("Ruta fuera del directorio permitido o enlace simbólico")
        return path

    def fingerprint(self, path):
        st = path.stat()
        return st.st_ino, st.st_size, st.st_mtime_ns

    def warn(self, code, error, path=None):
        warning = ScanWarning(code, str(error), str(path) if path is not None else None)
        if warning not in self.warnings:
            self.warnings.append(warning)

    def identifier(self, provider, path):
        relative = str(path.relative_to(self.roots[provider]))
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        return provider + ":" + digest
