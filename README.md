# rpawright

Open-source, self-healing web RPA: record browser tasks to YAML, run them on a schedule.

[![CI](https://github.com/WickTech/rpawright/actions/workflows/ci.yml/badge.svg)](https://github.com/WickTech/rpawright/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Status: pre-alpha — M1 (foundation: validate + run) is complete and in review; recording, vault, healing and scheduling are not built yet.**

## What it is

rpawright is a Python tool for automating web tasks. You record a browser task once and
get a readable, git-friendly YAML bot. Bots run from a CLI or from a local scheduler
daemon. When a site changes and a recorded element can no longer be found, the runner
tries the step's fallback locators, then asks an LLM for replacement selectors, checks
them against the live page, and saves a repair proposal that you approve before the YAML
changes. Secrets live in an encrypted vault and are bound to the domains they may be used
on. The design is clean-room and inspired by UiPath concepts; rpawright is not affiliated
with UiPath.

## Example bot

This is the planned workflow format (design spec section 6.1). It does not run yet.

```yaml
version: 1
name: download-invoices
description: Download last month's invoices from vendor portal
inputs:
  month: { type: string, default: "{{ today | prev_month | fmt('%Y-%m') }}" }
policy:
  allow_domains: [portal.vendor.com]
  headless: true
  timeout_ms: 15000
  heal: propose
steps:
  - goto: https://portal.vendor.com/login
  - fill:
      target: [{ role: textbox, name: Email }, { css: "input#email" }]
      value: "{{ secret.vendor_user }}"
  - click:
      target: [{ role: button, name: "Sign in" }, { text: "Sign in" }]
    retry: { times: 2, delay_ms: 1000 }
  - extract_table:
      target: [{ css: "table.invoices" }]
      into: rows
  - write_csv:
      path: "out/{{ inputs.month }}.csv"
      rows: "{{ rows }}"
```

## Planned features

Validated YAML workflows, `validate`, `schema`, locator fallback and `run` already work. Everything below beyond that is planned. Items marked (available) exist today.

**Authoring**
- Recorder that turns browser actions into YAML steps, with several ranked locators per target
- `rpawright pick` to choose an element and get locator candidates
- Typed, validated workflow format with a generated JSON Schema for editor autocomplete (available)

**Running**
- Steps for navigation, forms, extraction, downloads, uploads, HTTP, and CSV/XLSX files
- Variables, sandboxed `{{ }}` expressions, `if`, `for_each`, and `call`
- Per-step `retry` and `on_error`
- Debugging with `--headed`, `--step`, `pause:`, and Playwright traces (`--headed`, `--step` and traces are available; `pause:` is not)
- Run artifacts: redacted JSONL log, failure screenshot, optional trace (available; redaction is not built yet)

**Self-healing**
- Locator fallback chain (available), with a suggestion to reorder locators that keep falling back
- LLM repair proposals from Groq, Ollama, or Anthropic, verified on the live page
- YAML changes only after you review and confirm a diff (`heal review`)

**Security**
- Encrypted vault with OS keyring, passphrase, or key-file options
- Secrets bound to domains; navigation and HTTP limited to `allow_domains`
- Redaction of secrets in logs, notifications, screenshots, and LLM input

**Scheduling**
- Local daemon with cron and interval triggers, timeouts, and overlap control
- SQLite run history and `rpawright runs`
- Webhook or command notifications; autostart via systemd, launchd, or Task Scheduler

## How it compares

| | rpawright | UiPath | Robocorp | OpenRPA |
|---|---|---|---|---|
| Open source | yes (Apache-2.0) | no (commercial) | — | yes |
| Web automation | yes (planned) | yes | yes | yes |
| YAML / git-friendly bots | yes (planned) | — | — | — |
| LLM selector healing | yes (planned) | — | — | — |
| Desktop automation | planned (later) | yes | — | yes |
| Needs a server | no (local only) | — | — | — |

A dash means not verified here. The rpawright column describes the design goals, not
shipped behavior.

## Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M1 | Workflow models, `validate`, core runner, locator fallback, artifacts | complete (in review) |
| M2 | All v1 steps, control flow, expressions, CSV/XLSX/HTTP, retry/on_error | planned |
| M3 | Vault, policy guard, domain binding, redaction, masked screenshots | planned |
| M4 | Recorder, toolbar, locator generation, `pick` | planned |
| M5 | Healer, three providers, verification, `heal review` | planned |
| M6 | SQLite store, `runs`, daemon, notifications, `daemon install` | planned |
| M7 | Docs, examples, release automation, v0.1.0 | planned |

v2 backlog: work queues, file-watch and queue triggers, OCR and document extraction,
`llm_extract` step, human-in-the-loop `ask:` step, Windows desktop automation, local web
designer, optional Rust daemon.

## Quick start

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium
uv run rpawright validate examples/bots/demo-login.yaml
```

The demo bot logs in to the fixture site bundled in this repository, so serve that site
first (base URL `http://127.0.0.1:8765`). In one terminal:

```bash
python -m http.server 8765 --directory tests/fixtures/site
```

In another terminal:

```bash
uv run rpawright run examples/bots/demo-login.yaml --headed
```

`run` prints one line per step, then `run ok` or `run failed` with the run directory. The
email step lists `#email` first and a `textbox` named "Email" second; if the page's id
changes (try `login_v2.html`), the second locator still finds the field.

Artifacts are written to `runs/demo-login/<UTC timestamp>/` (change the root with
`--runs-dir`):

- `log.jsonl`: one record per step
- `fail-<step>.png`: screenshot of the page, only when a step fails
- `trace.zip`: Playwright trace, only with `--trace`

Exit codes: `0` run ok, `1` a step failed, `2` the bot file is invalid.

## Development

Prerequisites: Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                           # install dependencies
uv run playwright install chromium
uv run pytest                     # tests (85% coverage minimum)
uv run ruff check                 # lint
uv run mypy                       # type check (strict)
uv run rpawright --version        # prints 0.1.0.dev0
```

## Design docs

- Design spec: [docs/superpowers/specs/2026-11-02-open-rpa-design.md](docs/superpowers/specs/2026-11-02-open-rpa-design.md)
- Implementation plans: [docs/superpowers/plans/](docs/superpowers/plans/)

## License

Apache-2.0. See [LICENSE](LICENSE).
