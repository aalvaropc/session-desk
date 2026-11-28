from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Callable

SURROGATE = re.compile("[\ud800-\udfff]")


def clean_json(value: Any) -> Any:
    if isinstance(value, str):
        return SURROGATE.sub("\ufffd", value)
    if isinstance(value, dict):
        return {clean_json(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean_json(item) for item in value]
    return value


def records(path, *, checkpoint: Callable[[], None] | None = None):
    with Path(path).open(encoding="utf-8", errors="replace") as stream:
        for index, line in enumerate(stream):
            if checkpoint is not None and index % 128 == 0:
                checkpoint()
            try:
                obj = json.loads(line)
                if r"\u" in line:
                    obj = clean_json(obj)
            except (ValueError, RecursionError):
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


def timestamp(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OSError, OverflowError):
        return 0.0
