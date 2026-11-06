from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any, Iterator, Optional
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .config import Settings


@dataclass(frozen=True)
class Instance:
    application: str
    instance_id: str
    token: str
    pid: int
    url: str
    configuration: dict[str, Any]
    started_at: str


def state_directory() -> Path:
    override = os.environ.get("SESSION_DESK_STATE_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        return (
            Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
            / "SessionDesk"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SessionDesk"
    return (
        Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "session-desk"
    )


def configuration(settings: Settings) -> dict[str, Any]:
    return {
        "demo": settings.demo,
        "port": settings.port,
        "project": settings.project,
        "search": settings.search,
        "claude_home": str(
            Path(settings.claude_home or Path.home() / ".claude").expanduser().resolve()
        )
        if not settings.demo
        else None,
        "codex_home": str(
            Path(settings.codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
            .expanduser()
            .resolve()
        )
        if not settings.demo
        else None,
    }


def read_instance() -> Optional[Instance]:
    try:
        data = json.loads((state_directory() / "server.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("application") != "session-desk":
            return None
        if not isinstance(data.get("instance_id"), str) or not re.fullmatch(
            r"[a-f0-9]{32}", data["instance_id"]
        ):
            return None
        if not isinstance(data.get("token"), str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{32,128}", data["token"]
        ):
            return None
        if (
            not isinstance(data.get("pid"), int)
            or isinstance(data["pid"], bool)
            or data["pid"] <= 0
        ):
            return None
        if (
            not isinstance(data.get("configuration"), dict)
            or not isinstance(data.get("started_at"), str)
            or not isinstance(data.get("url"), str)
        ):
            return None
        address = urlsplit(data["url"])
        if (
            not address.port
            or not 0 < address.port <= 65535
            or data["url"] != f"http://127.0.0.1:{address.port}"
        ):
            return None
        return Instance(**{key: data[key] for key in Instance.__dataclass_fields__})
    except (OSError, ValueError, TypeError, KeyError):
        return None


def control(
    instance: Instance, path: str, payload: Optional[dict[str, str]] = None, timeout: float = 2
) -> Any:
    request = Request(
        instance.url + path,
        headers={"X-Panel-Token": instance.token, "Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
    )
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.loads(response.read(65536))


def running_instance() -> Optional[Instance]:
    instance = read_instance()
    if instance is None:
        return None
    try:
        status = control(instance, "/api/status")
        if (
            isinstance(status, dict)
            and status.get("application") == instance.application
            and status.get("instance_id") == instance.instance_id
            and status.get("pid") == instance.pid
        ):
            return instance
    except (OSError, URLError, ValueError, HTTPException):
        pass
    return None


def publish(instance_id: str, token: str, url: str, settings: Settings) -> None:
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    instance = Instance(
        "session-desk",
        instance_id,
        token,
        os.getpid(),
        url,
        configuration(settings),
        datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    temporary = directory / f"server-{instance_id}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(asdict(instance), output)
        temporary.replace(directory / "server.json")
    finally:
        temporary.unlink(missing_ok=True)


def remove_instance(instance_id: str) -> None:
    instance = read_instance()
    if instance is not None and instance.instance_id == instance_id:
        (state_directory() / "server.json").unlink(missing_ok=True)


@contextmanager
def launch_lock() -> Iterator[None]:
    directory = state_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(directory / "launch.lock", os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+b", buffering=0) as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"0")
        deadline = time.monotonic() + 15
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Another Session Desk launch is in progress; try again shortly"
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def child_arguments(settings: Settings, instance_id: str) -> list[str]:
    arguments = [
        sys.executable,
        "-m",
        "session_desk.cli",
        "--serve",
        "--port",
        str(settings.port),
        "--managed-instance",
        instance_id,
    ]
    if settings.demo:
        arguments.append("--demo")
    for name, value in (
        ("--project", settings.project),
        ("--grep", settings.search),
        ("--claude-home", settings.claude_home),
        ("--codex-home", settings.codex_home),
    ):
        if value is not None:
            arguments.extend((name, value))
    return arguments


def start(settings: Settings) -> Instance:
    with launch_lock():
        existing = running_instance()
        if existing is not None:
            if existing.configuration != configuration(settings):
                raise RuntimeError(
                    "Session Desk is already running with different options. Run session-desk stop before starting another workspace."
                )
            return existing
        identifier = uuid.uuid4().hex
        log_path = state_directory() / "server.log"
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        options: dict[str, Any] = {}
        if sys.platform == "win32":
            options["creationflags"] = (
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            options["start_new_session"] = True
        with os.fdopen(descriptor, "ab") as log:
            child = subprocess.Popen(
                child_arguments(settings, identifier),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                **options,
            )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            instance = running_instance()
            if instance is not None and instance.instance_id == identifier:
                return instance
            if child.poll() is not None:
                child.wait()
                break
            time.sleep(0.05)
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        remove_instance(identifier)
        raise RuntimeError(f"Could not start Session Desk. Check the log: {log_path}")


def stop() -> bool:
    with launch_lock():
        instance = running_instance()
        if instance is None:
            return False
        try:
            control(instance, "/api/shutdown", {"instance_id": instance.instance_id}, timeout=20)
        except (OSError, URLError, ValueError, HTTPException) as error:
            raise RuntimeError(
                "Could not stop Session Desk; retry after the current operation completes"
            ) from error
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            current = running_instance()
            if current is None or current.instance_id != instance.instance_id:
                if os.name == "nt":
                    _wait_for_windows_process(instance.pid, deadline - time.monotonic())
                remove_instance(instance.instance_id)
                return True
            time.sleep(0.05)
        raise RuntimeError("Session Desk is still shutting down; retry status shortly")


def _wait_for_windows_process(pid: int, remaining: float) -> None:
    import ctypes

    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_ulong)
    kernel32.WaitForSingleObject.restype = ctypes.c_ulong
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x00100000, 0, pid)
    if not handle:
        error = getattr(ctypes, "get_last_error")()
        if error == 87:
            return
        raise OSError(error, "Could not wait for Session Desk to exit")
    try:
        result = kernel32.WaitForSingleObject(handle, max(0, int(remaining * 1000)))
        if result == 0x102:
            raise RuntimeError("Session Desk is still shutting down; retry status shortly")
        if result != 0:
            raise OSError(
                getattr(ctypes, "get_last_error")(), "Could not wait for Session Desk to exit"
            )
    finally:
        kernel32.CloseHandle(handle)
