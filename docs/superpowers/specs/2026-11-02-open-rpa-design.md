# rpawright: Design Spec

- **Date:** 2026-11-02
- **Status:** Draft, awaiting user review
- **Author:** Rishabh Verma (with Claude Code)
- **Repo:** local folder `~/workspace/open-rpa`; public GitHub repo `github.com/WickTech/rpawright` (not created yet)
- **Name:** `rpawright`, used for the PyPI package, the CLI command, and the Python import name. PyPI name verified free on 2026-11-02.

## 1. Summary

rpawright is an open-source, Python-based Robotic Process Automation (RPA) tool for **web** automation. A user records a browser task once; the recorder writes a readable, git-friendly YAML workflow. Bots run from a CLI or on a schedule via a local daemon. When a site changes and a recorded element can no longer be found, the runner tries the step's fallback locators, then asks a pluggable LLM for replacement locators, verifies them against the live page, and stores a repair proposal that the user approves before the YAML is changed.

It borrows UiPath's concepts (activities, selectors, assets, credential store, triggers, retry scopes, run monitoring) but is a clean-room design. No UiPath code, binaries, or proprietary formats are reverse-engineered or copied.

## 2. Goals and non-goals

### Goals (v1)
- Record web tasks to YAML; edit, version, and validate them as code.
- Reliable replay: multi-locator targets, retries, structured error handling.
- Self-healing selectors: fallback chain, then LLM proposal, then human-approved patch.
- Unattended runs: cron/interval scheduling, per-run process isolation, run history, notifications.
- Secrets handled safely: encrypted vault, domain-bound secrets, redaction everywhere.
- Ship as a public open-source package installable with `pipx install rpawright` on Linux, macOS, and Windows.

### Non-goals (v1)
- Visual drag-and-drop designer (UiPath Studio canvas).
- Windows/desktop application automation.
- Multi-robot Orchestrator, multi-user, RBAC, cloud hosting.
- Work queues / transactions, OCR / document understanding, human-in-the-loop steps (all v2).
- Natural-language "describe the task" bot authoring.
- Hand-written Rust. Rust appears only inside the `cryptography` dependency.

## 3. Key decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Purpose: open-source RPA app, started as a personal tool; build quality is for public release | User goal: "build an RPA app open source, not to learn Rust" |
| D2 | Web automation only in v1 | Fastest path to reliability; Playwright works from WSL and Windows |
| D3 | Authoring: recorder that writes YAML, edited by hand | Readable, diffable, git-versioned; LLM only used for repair |
| D4 | Run modes: CLI plus local scheduler daemon; artifacts to folders; no web UI in v1 | Small surface area |
| D5 | LLM healing: pluggable provider interface; Groq default, Ollama and Anthropic built in; YAML changes only after user approval | Free default, offline option, best-quality option |
| D6 | Language: **pure Python** engine (approach A) | Playwright has official Python bindings but no Rust ones; Python is strongest for data, OCR, and LLM work; one stack is easiest to maintain |
| D7 | **No hand-written Rust**; vault uses `cryptography` (Rust-backed) | A Rust vault cannot zeroize secrets once they become Python strings for Playwright; a native extension adds a per-OS build matrix for an OSS package |
| D8 | Keep a Rust-ready seam: language-neutral JSON Schema for workflows; vault and redactor behind interfaces | A future Tauri designer or Rust daemon can be added without a rewrite |
| D9 | License Apache-2.0 | Permissive, with a patent grant |

Rejected alternatives: (B) Rust engine with a Python Playwright driver over JSON-RPC, rejected for its cross-process protocol, two codebases, and harder debugging. (C) All-Rust with thirtyfour or headless_chrome, rejected because those libraries are much weaker than Playwright and the recorder and healing would be rebuilt from scratch. A Robot Framework backend was also rejected: too heavy, a two-language workflow, and it conflicts with the healing design.

## 4. UiPath feature mapping

| UiPath feature | rpawright equivalent | Phase |
|---|---|---|
| Activities library | Built-in step types (§6.4) | v1 |
| Variables / arguments | `inputs:`, `vars:`, `set:`, sandboxed `{{ }}` expressions | v1 |
| Control flow | `if`, `for_each`, `call` | v1 |
| Try/Catch, Retry Scope | `retry:` and `on_error:` per step or block | v1 |
| Selectors + UI Explorer | Multi-locator `target` lists + `rpawright pick` | v1 |
| Debugging / breakpoints | `--headed`, `--step`, `pause:` step, Playwright traces | v1 |
| Assets + Credential store | `assets.yaml` + encrypted vault | v1 |
| Time triggers | `schedules.yaml` + daemon | v1 |
| Jobs / logs monitoring | SQLite run history + `rpawright runs` | v1 |
| Packages / versioning | Git (bots are YAML) | v1 |
| Attended vs unattended robot | `--headed` vs headless | v1 |
| AI Center | LLM healer (v1); `llm_extract` step (v2) | v1/v2 |
| Queues + transactions (REFramework) | SQLite work queue, per-item status and retry | v2 |
| Queue / file-watch triggers | Daemon watches queue or folder | v2 |
| Document Understanding / OCR | Tesseract + LLM field extraction | v2 |
| Action Center (human in the loop) | `ask:` step that pauses for input or approval | v2 |
| Desktop automation | Windows-side UIA driver | later |
| Studio visual designer | Local web designer reading the JSON Schema | later |
| Multi-robot Orchestrator | n/a (single user) | skip |

## 5. Architecture

```
rpawright/   (local folder: ~/workspace/open-rpa)
├── src/rpawright/
│   ├── cli.py         Typer: record | pick | run | validate | schema | heal | vault | daemon | schedule | runs | init
│   ├── workflow/      models.py · loader.py · expressions.py · schema.py
│   ├── runner/        engine.py · steps/ · locate.py · artifacts.py
│   ├── recorder/      session.py · inject.js · locators.js · postprocess.py · pick.py
│   ├── healer/        base.py · snapshot.py · validate.py · providers/{groq,ollama,anthropic}.py · review.py
│   ├── policy/        guard.py · redact.py
│   ├── vault/         store.py · keys.py
│   ├── scheduler/     daemon.py · config.py · notify.py · install.py
│   └── store/         db.py · migrations/
├── bots/              user workflows (*.yaml)
├── runs/              run artifacts
├── schema/            workflow.schema.json (generated)
├── examples/bots/     example bots against the bundled demo site
└── docs/
```

### Unit responsibilities and dependencies

| Unit | Responsibility | Depends on |
|---|---|---|
| workflow | Converts between YAML and the typed `Workflow` model; validation; expression sandbox; JSON Schema export | none |
| recorder | Turns browser events into a `Workflow` | workflow, vault, Playwright |
| runner | Executes a `Workflow` and returns a `RunResult` plus artifacts; resolves locators; requests healing through an interface | workflow, policy, vault, store |
| healer | Turns a failed step plus a page snapshot into a verified `HealProposal`; never writes files | policy (redaction) |
| policy | Wraps the browser context (domain allowlist, secret domain binding); redactor for every outbound text | vault |
| vault | Encrypted secret storage: `put/get/list/delete/rotate`; supplies the redactor with the set of secret values | `cryptography`, `keyring` |
| scheduler | Daemon: triggers, per-run subprocess, timeouts, overlap control, notifications | workflow, store |
| store | SQLite run history and step stats; numbered SQL migrations | none |

### Run data flow
CLI or scheduler → load and validate YAML → resolve inputs → open vault and register secrets with the redactor → new browser context with policy applied → execute steps (secrets resolved only at step execution) → for a missing element: fallback chain, then healer proposal → write `runs/<bot>/<timestamp>/` and the SQLite rows → exit code.

## 6. Workflow format

### 6.1 Example
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
  - fill:
      target: [{ label: Password }, { css: "input[type=password]" }]
      value: "{{ secret.vendor_pass }}"
  - click:
      target: [{ role: button, name: "Sign in" }, { text: "Sign in" }]
    retry: { times: 2, delay_ms: 1000 }
  - extract_table:
      target: [{ css: "table.invoices" }]
      into: rows
  - for_each:
      in: "{{ rows | where('Month', inputs.month) }}"
      as: inv
      steps:
        - click:
            target: [{ role: link, name: "{{ inv.Number }}" }]
        - download:
            to: "downloads/{{ inv.Number }}.pdf"
      on_error: continue
  - write_csv:
      path: "out/{{ inputs.month }}.csv"
      rows: "{{ rows }}"
```

### 6.2 Step rules
- Each step has exactly one action key, plus optional common fields: `id`, `retry: {times, delay_ms}`, `on_error: fail | continue | [steps]` (default `fail`), `timeout_ms`, `if:`, `pause:`.
- Step ids are generated by the recorder (e.g. `click-sign-in`) and must be unique within a workflow.

### 6.3 Targets
- `target` is an ordered list of locator candidates. Each candidate has exactly one of: `role` (+ `name`), `label`, `text`, `testid`, `css`, `xpath`. Optional modifiers: `nth`, `exact`.
- Optional `frame:` holds a locator list for the containing iframe.

### 6.4 v1 step types
`goto, click, fill, select, press, hover, wait, assert, extract_text, extract_table, download, upload, screenshot, http, read_csv, write_csv, read_xlsx, write_xlsx, set, if, for_each, call, pause, log`

### 6.5 Expressions
- `{{ }}` is evaluated with Jinja2 `SandboxedEnvironment` and a filter allowlist (`fmt`, `where`, `prev_month`, `default`, and others defined in code).
- Namespaces: `inputs`, `vars`, `secret`, `asset`, `env`, `today`, and loop variables.
- `secret.*` values are resolved only when a step executes. They are never stored in `vars`, never logged, and never sent to the LLM.

### 6.6 Validation and schema
- Pydantic v2 models are the single source of truth. `rpawright schema` generates `schema/workflow.schema.json`, which is committed and drift-checked in CI and usable for editor autocomplete via yaml-language-server.
- `rpawright validate bots/*.yaml` checks structure, unique ids, expression syntax, and secret-looking literals (warning).
- `version: 1` enables future format migrations.

## 7. Recorder and `pick`

### Commands
`rpawright record <bot.yaml> --url <url> [--append]`; `rpawright pick --url <url>`; `rpawright pick --bot <bot.yaml> --step <id>`.

### Mechanism
- Headed Playwright Chromium. The injected script is added with `context.add_init_script` and reaches every frame. Events go to Python through `expose_binding`.
- A toolbar sits in a closed shadow root with: pause, add assert, extract table/text, screenshot, stop. Events on the toolbar are ignored.

### Event to step mapping
URL typed at start or in the toolbar → `goto`; click → `click` (any navigation it causes is not recorded); input, committed on blur/change → `fill`; select change → `select`; Enter, Tab, Escape, or shortcuts → `press`; file chooser → `upload`; download → `download`; toolbar assert → `assert`; toolbar extract → `extract_table` / `extract_text`.

### Locator generation
1. Candidates are tried in priority order: `testid` (`data-testid`, `data-test`, `data-qa`) → `role` + accessible name → `label` → `text` (≤ 50 chars) → `css` (stable id or attributes; generated class names such as `css-*`, `sc-*`, hashed classes are rejected) → `xpath` (last resort).
2. Each candidate is checked for uniqueness on the live page. Up to 3 unique candidates are kept. If none is unique, the step is annotated `# WARN: ambiguous` and the best candidate gets `nth`.

### Post-processing
- Merge consecutive inputs into one `fill`.
- Drop focus-only clicks that come right before a fill.
- Generate step ids.
- Write YAML with `ruamel.yaml`, which keeps comments when appending.

### Security
- Password fields are never captured as plain text. The recorder prompts to store the value as a vault secret and writes `{{ secret.<name> }}`. The toolbar can mark any other field as secret.
- Domains visited during recording are proposed as `policy.allow_domains` and confirmed on stop.

### Limits
- Iframes are supported through `frame:`. Shadow DOM is supported through the event's `composedPath`.
- Canvas-rendered apps are unsupported in v1.
- Headed mode in WSL needs WSLg, or running from Windows Python.

## 8. Runner and self-healing

### Commands
`rpawright run <bot.yaml> [--input k=v]... [--headed] [--step] [--trace] [--unsafe-trace]`; `rpawright heal review [--run <id>]`.

### Locator resolution
- Candidate types map to Playwright: `get_by_role`, `get_by_label`, `get_by_text`, `get_by_test_id`, `locator(css|xpath)`, plus frame and nth handling.
- All candidates are polled together every 250 ms until the step timeout. The highest-priority candidate that matches exactly one visible element wins.
- When a lower-priority candidate wins, `fallback_used` is recorded in `step_stats`. After 3 consecutive such runs, `heal review` suggests reordering the list (no LLM involved).

### LLM healing (only when every candidate fails after retries)
1. Snapshot: `aria_snapshot()` plus a pruned DOM (scripts, styles, and event handlers removed; attribute allowlist; all `value` attributes and form state removed; about 8k tokens max).
2. Redaction: vault values, emails, and long digit runs.
3. `HealProvider.propose(ctx) -> list[Target]` with the step intent, old candidates, and the snapshot. The response must be strict JSON; anything else is discarded.
4. Each returned candidate is verified on the live page: it must be unique, visible, and an element kind compatible with the action (`fill` needs an editable element, `select` needs a select or listbox, and so on).
5. Verified candidates are saved to `runs/.../heal.json`.

`policy.heal` options:
- `propose` (default): the step fails and the proposal is saved.
- `apply_runtime` (opt-in per bot): use the verified candidate for this run only and still save the proposal.
- `off`: no healing.

The YAML is changed only by `heal review`, which shows the diff and requires confirmation. The LLM may only return locators. It cannot add steps, change values, or navigate.

### Providers
`groq` (default), `ollama`, `anthropic`. Model ids are set in `~/.config/rpawright/config.toml` (not hard-coded). API keys are stored in the vault.

### Errors
| Error | Retried | Healing |
|---|---|---|
| LocatorNotFound | yes | yes, after retries are exhausted |
| Timeout, StepError | yes | no |
| AssertionFailed | yes | no |
| PolicyViolation | never; the run fails immediately | no |
| ValidationError | caught before the run starts | no |

### Exit codes
`0` ok · `1` step failed · `2` invalid bot · `3` policy violation · `4` failed with a pending heal proposal.

### Artifacts (`runs/<bot>/<timestamp>/`)
- `log.jsonl`, redacted: step id, action, locator used, duration, status.
- Screenshot on failure, with password fields and secret-filled fields masked.
- `trace.zip` on failure or with `--trace`. Disabled for bots that use secrets unless `--unsafe-trace` is passed.
- `heal.json` when a proposal exists.

### Debugging
`--headed`; `--step` waits for Enter before each step; a `pause:` step opens the Playwright Inspector.

## 9. Scheduler and run history

### `schedules.yaml`
```yaml
timezone: Asia/Kolkata
max_parallel: 1
defaults: { timeout_min: 30, notify: on_failure }
schedules:
  - bot: bots/invoice.yaml
    cron: "0 9 1 * *"
    inputs: { month: "{{ today | prev_month | fmt('%Y-%m') }}" }
  - bot: bots/report.yaml
    every: 6h
    enabled: false
notify:
  on_failure:
    - webhook: https://ntfy.sh/my-rpa-topic
    - command: notify-send "rpawright" "{{ bot }} failed ({{ exit_code }})"
```

### Commands
`rpawright daemon [--foreground] | status | stop | install`; `rpawright schedule ls | run <bot>`; `rpawright runs ls [--bot] [--failed] | show <id> | prune --older <age>`.

### Daemon behaviour
- APScheduler, using cron and interval triggers.
- Each run is a subprocess with a timeout: SIGTERM, then kill after 10 s; recorded as `timeout`.
- No overlap per bot (`skipped_overlap`). A global `max_parallel` semaphore limits concurrent runs.
- Misfires: coalesce, and run once on wake if less than 1 h late; older misfires are recorded as `missed`.
- Hot-reloads `schedules.yaml` on change. An invalid file keeps the previous schedule and logs an error.
- Single-instance lock at `~/.local/state/rpawright/daemon.lock`.
- Notifications (webhook or local command) on `on_failure`, `on_heal_proposal`, or `always`. Messages are redacted, and template values are passed through `shlex.quote`.
- `daemon install` sets up autostart with systemd `--user` (Linux), launchd (macOS), or Task Scheduler (Windows). On WSL, systemd needs `systemd=true` in `wsl.conf` and the VM idles out, so the docs recommend running the daemon on the Windows side.

### SQLite (`~/.local/share/rpawright/rpawright.db`)
```
runs(id, bot, bot_hash, trigger, started_at, ended_at, status, exit_code,
     failed_step, heal_pending, artifacts_dir)
step_stats(bot, step_id, locator_used, fallback_used, duration_ms, run_id)
```
- `status` ∈ ok | failed | timeout | policy | skipped_overlap | missed.
- Migrations are plain numbered SQL files (no ORM).
- Retention: 30 days by default, always keeping the last 20 runs per bot.

## 10. Vault, secrets and security model

### Vault (`~/.local/share/rpawright/vault.enc`)
- **File format:** JSON header (version, KDF parameters, salt, nonce) followed by one AES-256-GCM-encrypted JSON blob. Writes are atomic (temp file + rename). File mode `0600`.
- **Key hierarchy:** a random 32-byte data key encrypts the vault. The data key is held in one of:
  1. the OS keyring (default);
  2. a passphrase-derived key (Argon2id, m=64 MiB, t=3, p=4);
  3. the `RPAWRIGHT_VAULT_KEY` environment variable or a `0600` key file, for headless or WSL daemons (risk documented).
- `vault rotate` re-wraps the data key.
- Requires `cryptography>=44`, the first release with Argon2id.
- **CLI:** `vault init | set <name> [--domains] | ls | rm | rotate | get <name> --reveal` (`--reveal` asks for confirmation and is never logged).
- **Domain binding:** every secret has `domains:`. Using `secret.x` on a page or in an `http` request whose domain is not in that list raises `PolicyViolation`.
- **Logged-in sessions:** `storage_state: vault:<name>` stores session cookies in the vault, never as plain files.
- **Assets:** `assets.yaml` holds non-secret configuration, read as `{{ asset.x }}`.

### Threat model
| Threat | Mitigation |
|---|---|
| Secrets committed in YAML | Only `{{ secret.x }}` references; recorder auto-vaults password fields; `validate` warns on secret-looking literals |
| Secrets in logs or notifications | Redactor masks every vault value, including its URL-encoded and base64 forms |
| Secrets in screenshots | Playwright `mask=` on password and secret-filled fields |
| Secrets in Playwright traces | Traces disabled for secret-using bots unless `--trace --unsafe-trace` |
| Page data sent to the LLM | Value attributes and form state removed, redaction applied; `heal: off` available |
| Prompt injection into the healer | Output limited to locators; live verification of uniqueness and element kind; `propose` default with human review; `apply_runtime` opt-in |
| Untrusted shared bots | Sandboxed Jinja; no shell step in v1; `http` and navigation limited to `allow_domains`; file paths confined to the workspace; `call` confined to `bots/`; domain-bound secrets |
| Shell injection through notification commands | `shlex.quote` on template values; commands only from the user's own `schedules.yaml` |
| Malicious downloads | Saved inside the workspace, never executed |
| Browser state leaking between bots | Fresh context per run; no persistent profile by default |
| Supply-chain attack | `uv.lock`, `pip-audit`, Dependabot, CodeQL, gitleaks, PyPI Trusted Publishing |

## 11. Testing and CI

- **Tooling:** Python 3.12+, uv, ruff, `mypy --strict`, pytest + pytest-playwright, 85% coverage minimum. Browser tests use only local fixture sites (no live websites).
- **Unit tests:** models, expressions, sandbox escapes (`{{ ''.__class__ }}` must fail), redaction, vault round-trip, tamper detection, wrong passphrase, rotation, locator scoring.
- **Browser tests:** fixture site v1 and v2 (v2 has changed DOM). Recorder output is compared against golden YAML. Covered: fallback order, rejection of ambiguous or wrong-kind heal candidates, domain allowlist, secret domain binding, masked screenshots.
- **End-to-end tests:** record → run → break the page → heal (fake provider) → review → run again; daemon tests with `time-machine` and stub subprocesses (cron, coalesce, overlap, timeout, hot reload); migrations from a fresh database and from the previous version.
- **CI jobs (GitHub Actions):**
  - `lint-type`: ruff, mypy, schema drift check.
  - `test`: ubuntu/macos/windows × py3.12/3.13.
  - `security`: pip-audit, CodeQL, gitleaks; runs on PRs and weekly.
  - `release`: on a `v*` tag, build and publish to PyPI with Trusted Publishing, then create a GitHub Release.

## 12. Milestones (one PR each; the user merges with a merge commit or rebase, never squash)

| # | Scope | Exit criterion |
|---|---|---|
| M1 | Workflow models, `validate`, core runner (goto/click/fill/press/wait/assert), locator fallback, artifacts | A hand-written bot logs into the demo site |
| M2 | All v1 steps, control flow, expressions, CSV/XLSX/HTTP, retry/on_error | The invoice example runs end to end |
| M3 | Vault, policy guard, domain binding, redaction, masked screenshots | Leak tests pass; a cross-domain secret is blocked |
| M4 | Recorder, toolbar, locator generation, `pick` | A recorded demo login replays cleanly |
| M5 | Healer, 3 providers, verification, `heal review`, reorder suggestions | A broken demo page heals and the approved diff is applied |
| M6 | SQLite store, `runs`, daemon, notifications, `daemon install` | A cron run works; timeout and overlap are handled; an ntfy alert arrives |
| M7 | Docs, examples, release automation, v0.1.0 | `pipx install rpawright` works on all 3 operating systems (release requires explicit user approval) |

## 13. v2 backlog
SQLite work queue with a REFramework-style item loop; file-watch and queue triggers; OCR and document extraction; `llm_extract` step; `ask:` human-in-the-loop step; Windows desktop automation; local web designer driven by the JSON Schema; optional Rust daemon if a need appears.

## 14. Resolved questions
- **Name:** `rpawright` (chosen 2026-11-02). It was free on PyPI and no GitHub repo used it. `open-rpa` was rejected because it is easily confused with the existing OpenRPA project. Register the PyPI name early, at the first release or with a placeholder, so it stays available.
- **GitHub:** public repo on the user's personal account `WickTech` (a GitHub user account, not an org), public from day one. Creating the repo and pushing requires explicit user confirmation.
