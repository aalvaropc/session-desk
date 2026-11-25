from __future__ import annotations

import collections
import datetime
import json
import os


def load_history(path=None) -> dict:
    hist: dict[str, list[str]] = {}
    path = path or ""
    if not os.path.exists(path):
        return hist
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            sid, disp = obj.get("sessionId"), obj.get("display")
            if isinstance(sid, str) and isinstance(disp, str) and disp.strip():
                disp = disp.strip()
                hist.setdefault(sid, []).append(disp)
    return hist


def extract(path: str, hist: dict, grep: str | None = None) -> dict:
    sid = os.path.basename(path)[:-6]
    st = os.stat(path)
    title = first = cwd = branch = None
    n_msgs = 0
    match = None
    needle = grep.lower() if grep else None
    tail: collections.deque[dict] = collections.deque(maxlen=150)
    from .common import readable, records, snippet, text_content

    for i, obj in enumerate(records(path)):
        typ = obj.get("type")
        if typ in ("user", "assistant"):
            n_msgs += 1
            tail.append(obj)
            message = obj.get("message")
            txt = text_content(message.get("content")) if isinstance(message, dict) else ""
            if needle and match is None:
                match = snippet(txt, needle) or None
        if typ == "custom-title":
            value = obj.get("customTitle")
            if isinstance(value, str):
                title = value.strip() or title
        if i >= 150 or (first and cwd and branch):
            continue
        if not cwd and isinstance(obj.get("cwd"), str):
            cwd = obj["cwd"]
        if not branch and isinstance(obj.get("gitBranch"), str):
            branch = obj["gitBranch"]
        if first is None and typ == "user":
            message = obj.get("message")
            txt = text_content(message.get("content")) if isinstance(message, dict) else ""
            if readable(txt):
                first = txt.strip()
    prompts = hist.get(sid, [])
    if first is None and prompts:
        first = prompts[0]

    msgs = []
    for obj in tail:
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            continue
        message = obj.get("message")
        txt = text_content(message.get("content")) if isinstance(message, dict) else ""
        txt = txt.strip()
        if not readable(txt):
            continue
        msgs.append({"r": "u" if typ == "user" else "a", "t": txt.replace("\r", "")[:600]})
    return {
        "id": sid,
        "sid": sid,
        "provider": "claude",
        "file": path,
        "proj": cwd or os.path.basename(os.path.dirname(path)),
        "date": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "ts": int(st.st_mtime),
        "kb": st.st_size // 1024,
        "msgs": n_msgs,
        "branch": branch or "",
        "prompts": len(prompts),
        "title": (title or "").replace("\n", " ")[:160],
        "first": (first or "").replace("\n", " ")[:300],
        "last": msgs[-10:],
        "match": match or "",
    }


def load_messages(path: str) -> list[dict]:
    """Return the complete readable conversation, without the catalog's preview limits."""
    from .common import readable, records, text_content

    result = []
    for obj in records(path):
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            continue
        message = obj.get("message")
        txt = text_content(message.get("content")) if isinstance(message, dict) else ""
        txt = txt.strip()
        if readable(txt):
            result.append({"role": typ, "text": txt.replace("\r", "")})
    return result


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm, body = text[3:end], text[end + 4 :].lstrip("\n")
    meta: dict = {}
    cur_key = None
    for line in fm.splitlines():
        if not line.strip() or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        k, _, v = line.strip().partition(":")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if indent == 0:
            meta[k] = v or {}
            cur_key = None if v else k
        elif cur_key and isinstance(meta.get(cur_key), dict):
            meta[cur_key][k] = v
    return meta, body


def mem_type(meta: dict) -> str:
    t = meta.get("type")
    if isinstance(t, str) and t:
        return t
    md = meta.get("metadata")
    if isinstance(md, dict) and isinstance(md.get("type"), str) and md["type"]:
        return md["type"]
    return "other"


def mem_origin(meta: dict) -> str:
    o = meta.get("originSessionId")
    if isinstance(o, str) and o:
        return o
    md = meta.get("metadata")
    if isinstance(md, dict) and isinstance(md.get("originSessionId"), str):
        return md["originSessionId"]
    return ""


def slug_to_path_guess(slug_dir: str) -> str:
    base = os.path.basename(slug_dir)
    return base.replace("-", "/") if base.startswith("-") else base


def _meta_str(meta: dict, key: str) -> str:
    v = meta.get(key)
    return v if isinstance(v, str) and v else ""


def extract_memory(path: str, proj_map: dict) -> dict:
    st = os.stat(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    meta, body = parse_frontmatter(text)
    slug_dir = os.path.dirname(os.path.dirname(path))
    return {
        "id": path,
        "file": path,
        "proj": proj_map.get(slug_dir) or slug_to_path_guess(slug_dir),
        "name": _meta_str(meta, "name") or os.path.splitext(os.path.basename(path))[0],
        "description": _meta_str(meta, "description"),
        "type": mem_type(meta),
        "origin": mem_origin(meta),
        "date": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "ts": int(st.st_mtime),
        "kb": max(1, st.st_size // 1024),
        "body": body.strip(),
    }
