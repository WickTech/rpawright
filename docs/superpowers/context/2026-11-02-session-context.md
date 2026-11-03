# Session context: 2026-11-02 (rpawright design brainstorm)

Handoff note so a new Claude Code session, opened in this folder, can pick up exactly where the
design conversation stopped. The authoritative design is
`docs/superpowers/specs/2026-11-02-open-rpa-design.md`.

## How to resume
- Open `~/workspace/open-rpa` in VS Code (Remote-WSL). The user works in the VS Code Claude Code
  panel, not a separate terminal.
- Prompt: `continue the rpawright design work from docs/superpowers/context/2026-11-02-session-context.md`
- The project memory (`~/.claude/projects/-home-rishi-workspace-open-rpa/memory/`) loads automatically.

## Origin
- The design conversation started in the REA session (`~/workspace/REA`). The user asked whether REA
  could be used to build an open-source UiPath.
- Answer given: REA is a reverse-engineering toolkit, not an RPA platform. Decompiling UiPath breaks
  its EULA and creates copyright risk. The project is instead a clean-room design that borrows
  UiPath's concepts only.
- Process used: the `superpowers:brainstorming` skill, architectural path (questions → approaches →
  sectioned design → written spec → user review → writing-plans).

## Decisions, in the order they were made
1. Purpose: personal tool → later confirmed as a **public open-source package** (pipx install, CI, docs, Apache-2.0).
2. Targets: **web only** in v1 (Playwright).
3. Authoring: **recorder → editable YAML**.
4. Runs: **CLI + local scheduler daemon**, artifacts in folders, no web UI.
5. Healing: **pluggable LLM, Groq default**, Ollama and Anthropic as options; human approval before any YAML change.
6. Stack: approach **A, pure Python**. Rust options compared: A (Python + Rust vault), B (Rust engine + Python Playwright driver), C (all Rust).
   The user chose A with minimal Rust ("i want to build a rpa app open source not to learn rust"), which was
   then reduced to **zero hand-written Rust**. The vault uses `cryptography>=44` (Rust-backed) plus `keyring`.
7. UiPath features from the user's notes were mapped into v1, v2, later, or skip (spec §4).
8. All 7 design sections were approved in chat ("continue"): architecture, YAML format, recorder/pick,
   runner/healing, scheduler/history, vault/security, testing/CI/milestones.
9. **Name: `rpawright`** (PyPI package, CLI, import). It was free on PyPI and no GitHub repo used it.
   Alternatives offered: mendbot, webclerk, flowwright, autoclerk. `open-rpa` was rejected because it
   is easily confused with OpenRPA.
10. **GitHub: public repo `WickTech/rpawright`.** WickTech is the user's personal GitHub user account,
    not an org. The local folder name stays `open-rpa`.

## Inputs from the user (untracked files in repo root, intentionally not committed)
- `core-features of UI-path.md`: notes proposing an all-Rust UiPath clone (Tauri, Tokio, Axum,
  thirtyfour, tch-rs). Features were mapped into spec §4; most of the stack was rejected (spec §3).
- `Promt.md`: a prompt for auditing a **different repo (Task-Master)**. Not related to rpawright and
  not acted on. Its Robocorp video link was noted as background.

## State (updated 2026-11-03, paused by an API rate limit)
- Spec approved. Public repo https://github.com/WickTech/rpawright.
- **M1 is complete:** PR #1 (`m1-foundation` -> `main`) is open, CI green on all 7 jobs, 85 tests, 98% coverage. **Waiting for the user to merge it** (merge commit or rebase, never squash).
- **M2 (remaining steps, expressions, control flow, CSV/XLSX/HTTP) is in progress** on branch `m2-steps-flow`, stacked on `m1-foundation`, not pushed. Plan: `docs/superpowers/plans/2026-11-02-m2-steps-flow.md` (10 tasks, rulings R1-R25; reviewed by Opus before execution).
  - Task 1 expression sandbox: done and reviewed (adversarial Opus review plus re-review). Calls are denied, `**`/`*`/`%` are capped, join and output are capped, native results must be plain data.
  - Task 2 models for all steps, inputs and vars, nested ids, load-time expression validation, JSON Schema: done and reviewed.
  - Task 3 recursive executor with RunContext, on_error step lists, poll helper, and explicit failure-cause tracking: done and reviewed (two fix rounds).
  - Task 4 runtime templating, inputs/vars, `set`/`log`/`pause`, `--input`: built (`21d6bb9`) and reviewed; its performance fix round was interrupted and is **uncommitted in the working tree** (healthy: lint, types and tests pass).
  - Tasks 5-10 are not started.
- Test count on the branch: 248 at `21d6bb9`.
- The controller's local working files (git-ignored, on this machine only): the M2 ledger and rulings under `.superpowers/sdd/2026-11-02-m2-steps-flow/`, and the M1 ledger under `.superpowers/sdd/2026-11-02-m1-foundation/`. They hold every ruling (C1-C15), deferred minor and the exact resume steps. Do not run `git clean -fdx`.
- The user asked to continue later with **Sonnet 4.6** as the controller model (they switch it with `/model`).

## Next steps
1. Read `docs/superpowers/plans/2026-11-02-autonomous-runbook.md` (operating manual) and the PAUSE block at the end of `.superpowers/sdd/2026-11-02-m2-steps-flow/progress.md`.
2. Resume the interrupted Task 4 fix round, get it re-reviewed, then run Tasks 5-10, the whole-branch Opus review and one fix wave, push, and open the stacked M2 PR.
3. Then M3-M7 per the runbook. Stop points: merges, tags/releases/PyPI, secrets, real API calls.
