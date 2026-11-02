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

## State (updated 2026-11-02, after M1 execution)
- Spec approved. Public repo https://github.com/WickTech/rpawright.
- **M1 is complete** on branch `m1-foundation` (all 6 plan tasks plus README, per-task reviews, a whole-branch review and one fix wave).
  Result: 85 tests, 98% coverage, ruff and mypy strict clean.
- M1 delivers: typed YAML workflow models, loader with line and step errors, `rpawright validate`, JSON Schema export with a CI drift check,
  locator fallback (ordered candidates, ambiguity-safe, iframe support), run engine (retry, `on_error`, JSONL log, failure screenshot, optional trace),
  `rpawright run`, a demo bot with end-to-end tests, and a README with a quick start.
- The operating manual for the remaining work is `docs/superpowers/plans/2026-11-02-autonomous-runbook.md`
  (authority, stop points, model routing, M2-M7 steps, recovery). Section 0 there is a snapshot from before M1 finished; for current state trust `git log`,
  `gh pr list`, and this note.

## Next steps
1. The user reviews and merges the M1 PR (merge commit or rebase, never squash).
2. Continue with M2 per the runbook, section 5 (stacked branches).
3. M3 must route redaction through `RunArtifacts.log` and `.screenshot`, disable traces for bots that use secrets, and mask failure screenshots (see the final M1 review).
