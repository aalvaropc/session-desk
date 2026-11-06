from __future__ import annotations

import argparse
import webbrowser
from contextlib import ExitStack
from pathlib import Path
from typing import Optional, Sequence

from . import __version__, background
from .config import Settings
from .demo import demo_store
from .rendering import build_catalog, render_page
from .server import make_server
from .sessions import SessionStore


def parse_settings(arguments: Optional[Sequence[str]] = None) -> Settings:
    parser = argparse.ArgumentParser(
        prog="session-desk",
        description="A private workspace for your Claude Code and Codex conversations.",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=("start", "status", "stop"),
        help="manage a local background workspace",
    )
    parser.add_argument("--managed-instance", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"Session Desk {__version__}")
    parser.add_argument(
        "-o",
        "--output",
        default=str(Path.cwd() / "session-desk.html"),
        help="output path for the standalone HTML export",
    )
    parser.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="start the panel and open it in your browser",
    )
    parser.add_argument(
        "--serve", action="store_true", help="serve the interactive panel on 127.0.0.1"
    )
    parser.add_argument("--static", action="store_true", help="export a self-contained HTML file")
    parser.add_argument(
        "--demo", action="store_true", help="use only synthetic sample conversations"
    )
    parser.add_argument(
        "--port", type=int, default=8765, help="local server port; use 0 for an available port"
    )
    parser.add_argument("--claude-home", help="Claude directory; defaults to ~/.claude")
    parser.add_argument("--codex-home", help="Codex directory; defaults to CODEX_HOME or ~/.codex")
    parser.add_argument("-p", "--project", help="filter by a substring of the project path")
    parser.add_argument(
        "-g",
        "--grep",
        dest="search",
        help="search full transcripts and memory bodies during scanning",
    )
    arguments_parsed = parser.parse_args(arguments)
    if arguments_parsed.action and (
        arguments_parsed.static or arguments_parsed.serve or arguments_parsed.managed_instance
    ):
        parser.error("background commands cannot be combined with --static or --serve")
    if arguments_parsed.action in ("status", "stop") and (
        arguments_parsed.open_browser
        or arguments_parsed.demo
        or arguments_parsed.project
        or arguments_parsed.search
        or arguments_parsed.claude_home
        or arguments_parsed.codex_home
    ):
        parser.error("status and stop operate on the managed workspace and take no launch options")
    if arguments_parsed.serve and arguments_parsed.static:
        parser.error("--serve and --static cannot be used together")
    if not 0 <= arguments_parsed.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    if arguments_parsed.demo and (arguments_parsed.claude_home or arguments_parsed.codex_home):
        parser.error("--demo uses isolated sample data and cannot be combined with provider roots")
    values = vars(arguments_parsed)
    values["output"] = Path(values["output"]).expanduser()
    return Settings(**values)


def main(arguments: Optional[Sequence[str]] = None) -> None:
    settings = parse_settings(arguments)
    if settings.action:
        try:
            if settings.action == "start":
                instance = background.start(settings)
                print(f"Session Desk is running in the background: {instance.url}")
                if settings.open_browser:
                    webbrowser.open(instance.url)
            elif settings.action == "status":
                current_instance = background.running_instance()
                print(
                    f"Session Desk is running: {current_instance.url}"
                    if current_instance
                    else "Session Desk is not running."
                )
            else:
                print(
                    "Session Desk stopped." if background.stop() else "Session Desk is not running."
                )
        except (OSError, RuntimeError) as error:
            raise SystemExit(str(error)) from error
        return
    with ExitStack() as context:
        store = (
            context.enter_context(demo_store())
            if settings.demo
            else SessionStore(settings.claude_home, settings.codex_home)
        )
        if (settings.serve or settings.open_browser or settings.demo) and not settings.static:
            try:
                server = make_server(
                    store,
                    settings.port,
                    settings.project,
                    settings.search,
                    settings.demo,
                    settings.managed_instance,
                )
            except OSError as error:
                raise SystemExit(
                    f"Could not start Session Desk: {error}. Try another --port."
                ) from error
            if settings.managed_instance:
                background.publish(settings.managed_instance, server.token, server.origin, settings)
            print(f"Session Desk: {server.origin}\nPress Ctrl+C to stop.", flush=True)
            if settings.open_browser:
                webbrowser.open(server.origin)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nSession Desk stopped.")
            finally:
                server.server_close()
                if settings.managed_instance:
                    background.remove_instance(settings.managed_instance)
            return
        mode = "demo" if settings.demo else "static"
        catalog = build_catalog(store, mode=mode, project=settings.project, search=settings.search)
        settings.output.parent.mkdir(parents=True, exist_ok=True)
        settings.output.write_text(render_page(catalog, standalone=True), encoding="utf-8")
        print(
            f"{len(catalog['sessions'])} sessions · {len(catalog['memories'])} memories → {settings.output}"
        )
        if settings.open_browser:
            webbrowser.open(settings.output.resolve().as_uri())


if __name__ == "__main__":
    main()
