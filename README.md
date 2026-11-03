# rpawright

Open-source, self-healing web RPA: record browser tasks to YAML, run them on a schedule.

[![CI](https://github.com/WickTech/rpawright/actions/workflows/ci.yml/badge.svg)](https://github.com/WickTech/rpawright/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Status: pre-alpha, not usable for real work yet. M1 (foundation: `validate` + `run`) is merged. M2 (steps, expressions, control flow) is partly done: validated workflows, sandboxed `{{ }}` expressions, `inputs`/`vars`, per-step `retry`/`on_error`, and the `goto`, `click`, `fill`, `press`, `wait`, `assert`, `set`, `log` and `pause` steps run today. Page extraction, files, HTTP, `if`, `for_each` and `call` validate but do not run yet. Recording, vault, healing and scheduling are not built.**

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

This is the planned workflow format (design spec section 6.1). It does not run yet: `extract_table`
and `write_csv` have no runtime handler (running them fails with `step type '...' is not
implemented yet`), and `{{ secret.* }}` is not available until M3. Of its steps, only `goto`, `fill`
and `click` run today. A smaller bot that runs today is in
[Example bot that runs today](#example-bot-that-runs-today).

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

## Example bot that runs today

`examples/bots/demo-inputs.yaml` uses only steps that run now (`goto`, `fill`, `click`, `assert`,
`set`, `log`), an `inputs:` section and a `vars:` section. It logs in to the bundled fixture site
(see Quick start for serving it):

```yaml
version: 1
name: demo-inputs
inputs:
  email: { type: string, default: me@example.com }
vars:
  greeting: "Signing in as {{ inputs.email }}"
steps:
  - log: { message: "{{ vars.greeting }}" }
  - goto: http://127.0.0.1:8765/login.html
  - fill:
      target: [{ css: "#email" }, { role: textbox, name: Email }]
      value: "{{ inputs.email }}"
  # ... password, click, assert, set, log (see the file)
```

Override an input with `--input name=value` (repeatable, short form `-i`).

## Planned features

Items marked (available) work at runtime today; everything else is planned.

**Authoring**
- Recorder that turns browser actions into YAML steps, with several ranked locators per target
- `rpawright pick` to choose an element and get locator candidates
- Typed, validated workflow format with a generated JSON Schema for editor autocomplete (available)

**Running**
- Steps for navigation and forms: `goto`, `click`, `fill`, `press`, `wait`, `assert` (available)
- `set`, `log` and `pause` steps (available)
- `inputs:` and `vars:` sections, and `rpawright run --input k=v` (available)
- Sandboxed `{{ }}` expressions over inputs, vars, loop variables, `today` and `env`, using filters only (no function or method calls) (available)
- Per-step `retry` and `on_error` (`fail`, `continue`, or a list of steps) (available)
- Debugging with `--headed`, `--step`, `pause:` and Playwright traces (available)
- Steps for extraction, downloads, uploads, HTTP, and CSV/XLSX files, plus `if`, `for_each` and `call` (see the list below)
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

**Accepted by `validate` but not runnable yet.** These step types pass `validate` and the JSON
Schema, but have no runtime handler. Running a bot that reaches one fails that step with
`step type '<name>' is not implemented yet` (exit code 1; `on_error` applies, `retry` does not):
`select`, `hover`, `extract_text`, `extract_table`, `download`, `upload`, `screenshot`, `http`,
`read_csv`, `write_csv`, `read_xlsx`, `write_xlsx`, `if`, `for_each`, `call`.

## Expressions

Only `{{ ... }}` is supported. There are no `{% %}` or `{# #}` blocks; to write a literal `{%` or
`{#` in text, use `{{ '{%' }}` or `{{ '{#' }}`. Transformations use filters (`{{ x | upper }}`),
not method calls or function calls. `secret` and `asset` namespaces do not exist until M3.

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
| M1 | Workflow models, `validate`, core runner, locator fallback, artifacts | complete (merged) |
| M2 | All v1 steps, control flow, expressions, CSV/XLSX/HTTP, retry/on_error | in progress — expressions, models, executor, inputs, set/log/pause done; page/flow/file/http steps and the invoice example next |
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
uv run python -m http.server 8765 --directory tests/fixtures/site
```

In another terminal:

```bash
uv run rpawright run examples/bots/demo-login.yaml
```

To run the bot with an input and the `inputs:` section (same server):

```bash
uv run rpawright validate examples/bots/demo-inputs.yaml
uv run rpawright run examples/bots/demo-inputs.yaml
uv run rpawright run examples/bots/demo-inputs.yaml --input email=you@example.com
```

Add `--headed` to watch the browser window (needs a display).

`run` prints one line per step, then `run ok` or `run failed` with the run directory. The
email step lists `#email` first and a `textbox` named "Email" second. To see the fallback,
change the bot's `goto` URL to `http://127.0.0.1:8765/login_v2.html` (that page renames
the field's id); the run still passes because the second locator finds the field.

Artifacts are written to `runs/demo-login/<UTC timestamp>/` (change the root with
`--runs-dir`):

- `log.jsonl`: one JSON record per step, each with `"event": "step"` (a failed `--trace` save adds a `"event": "trace_failed"` record)
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
