# Contributing to rpawright

## Setup

```bash
uv sync
uv run playwright install chromium
```

## Checks CI runs

Run these before opening a PR:

```bash
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest                     # coverage must stay at 85% or above
uv run rpawright schema --out schema/workflow.schema.json && git diff --exit-code schema/
uv lock --check
```

## Tests and Playwright

Playwright's sync API cannot nest: a test module that uses the browser fixtures (`page`, `run_bot`)
must not start its own `sync_playwright()` or call `run_workflow` without an injected `browser`;
put such tests in a module without browser fixtures.

## Commits and PRs

- Use conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, with an optional scope
  such as `feat(cli):`).
- One focused change per PR.
- PRs are merged with a merge commit or rebase, not squash.
