# Contributing

Session Desk is a local Python application with a compiled TypeScript interface.
Python is sufficient to run the distributed package. Node is only needed to change
or rebuild the frontend.

## Development

```sh
uv sync --group dev
npm ci --ignore-scripts
npm run build
uv run session-desk --demo --open
```

Use demo data or temporary provider directories when developing deletion/recovery.
The demo never reads `~/.claude`, `~/.codex` or `CODEX_HOME`. Demo UI changes are held
in memory; reload or Reset demo returns to the original sample data.

## Checks

```sh
uv run python -m unittest discover -s tests -v
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
npm run build
npm run test:unit
npm run format:check
npx playwright install chromium
npm run test:e2e
uv build --out-dir dist
python scripts/check-wheel.py dist
```

Browser tests start an isolated demo server on port 8766 and a temporary-file local
workspace on port 8768. Set `PYTHON` when your
Python executable is not `python3` (`python` on Windows). Keep these ports free.

## Boundaries

Provider-specific parsing belongs in `providers/`. Filesystem operations and catalog
behavior belong in `services/`. The HTTP server deals with request validation and
transport; it does not parse provider transcripts. Frontend application state is
independent from DOM rendering. Public boundary objects have explicit types.

Keep code free of explanatory comments and docstrings. Use descriptive names, focused
functions and regression tests. Record tradeoffs in `docs/architecture.md`. Add a
failing regression before changing removal, restoration, keyboard or persistence logic.

Commit built frontend assets with frontend source changes. Releases must include the
assets in both the wheel and source distribution, with a clean installation smoke test.
Never use real conversations in screenshots, fixtures or bug reports. Include synthetic
examples that reproduce the relevant record structure.

## Pull requests

Describe the concrete behavior change, the regression case and checks that passed.
Record known limitations rather than claiming platforms or provider versions that
have not been exercised. Use Conventional Commits titles. Do not include assistant
co-authorship trailers.
