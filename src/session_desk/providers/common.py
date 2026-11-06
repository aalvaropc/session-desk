from __future__ import annotations

import json
from pathlib import Path


def records(path):
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                yield obj


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b["text"]
            for b in content
            if isinstance(b, dict)
            and b.get("type") in ("text", "input_text", "output_text")
            and isinstance(b.get("text"), str)
        )
    return ""


def readable(text):
    return bool(text.strip()) and not text.lstrip().startswith(
        ("<", "Caveat:", "# AGENTS.md instructions", "# Environment context")
    )


def snippet(text, needle):
    flat = text.replace("\n", " ")
    i = flat.lower().find(needle.lower())
    if i < 0:
        return ""
    lo, hi = max(0, i - 60), min(len(flat), i + len(needle) + 60)
    return ("…" if lo else "") + flat[lo:hi] + ("…" if hi < len(flat) else "")
