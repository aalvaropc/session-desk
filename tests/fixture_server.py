import json
import os
from pathlib import Path

from session_desk.demo import demo_store
from session_desk.server import make_server

with demo_store() as store:
    sessions = store.scan()
    for provider in ("claude", "codex"):
        session = next(item for item in sessions if item.provider == provider)
        path = Path(session.file_path)
        original = path.stat()
        with path.open("a", encoding="utf-8") as stream:
            for i in range(14):
                text = f"{provider} synthetic middle message {i}"
                if provider == "claude":
                    record = {"type": "assistant", "message": {"content": text}}
                else:
                    record = {
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": text}],
                        },
                    }
                stream.write(json.dumps(record) + "\n")
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    server = make_server(
        store, port=8768, index_path=store.roots["antigravity"].parent / "workspace.sqlite3"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
