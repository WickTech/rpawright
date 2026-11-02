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

## State at end of session
- Repo: `~/workspace/open-rpa`, branch `main`, **no remote**. Commits: `dbc14e5` (spec + context), `bb1f6b7` (rename to rpawright).
- **No code written.**

## Pending (ask the user; nothing done yet)
1. **Spec approval.** The user has not yet explicitly approved the written spec. Ask for approval or changes.
2. **Create the public repo and push.** This needs an explicit yes, because it is a public action.
   Planned commands: `gh repo create WickTech/rpawright --public --source . --push`, pushing `main`
   with the docs commits only; leave `Promt.md` and `core-features of UI-path.md` untracked.

## Next steps after approval
1. Invoke `superpowers:writing-plans`. Write the implementation plan for M1–M7 to `docs/superpowers/plans/`.
2. The user picks the execution method (subagent-driven, inline, or the `/ship` pipeline).
3. One PR per milestone; the user merges with a merge commit or rebase, never squash.
