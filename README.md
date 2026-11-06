# Session Desk

A local workspace for Claude Code and Codex conversations. Search sessions, inspect context, copy a resume command, and move sessions or project memories to a recoverable trash. Your data stays on your computer.

![Session Desk workspace](docs/screenshots/workspace.png)

## Get started

Requires Python 3.9+ and [uv](https://docs.astral.sh/uv/).

```sh
uv tool install git+https://github.com/aalvaropc/session-desk.git
session-desk start --open
```

The server keeps running after you close the terminal. Manage it with `session-desk status` and `session-desk stop`. It listens on `127.0.0.1` and does not start automatically after a reboot.

From a source checkout, use `uv run session-desk start --open`. To explore without reading your files, run `uv run session-desk start --demo --open` and stop the current instance first if needed.

## What it does

- Finds Claude Code and Codex sessions in their default directories or custom roots.
- Searches, filters, and reviews conversations and Claude project memories.
- Copies the provider's resume command for a selected session.
- Moves sessions and memories to recoverable trash and restores them from the panel.
- Exports an offline HTML snapshot with `session-desk --static -o sessions.html`.

Use `session-desk --help` for options such as `--claude-home`, `--codex-home`, `--port`, and scan filters. The demo contains only synthetic data. Exports of your own sessions contain private text; keep them private.

## Development

```sh
uv sync --group dev
npm ci --ignore-scripts
npm run build
uv run python -m unittest discover -s tests
npm run test:unit
npm run test:e2e
```

The TypeScript interface is bundled into the Python package. See [architecture](docs/architecture.md), [contributing](CONTRIBUTING.md), and the [MIT license](LICENSE).
