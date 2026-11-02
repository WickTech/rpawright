# Session context: 2026-11-02 (design brainstorm)

Handoff note for the next session. The authoritative design is
`docs/superpowers/specs/2026-11-02-open-rpa-design.md`.

## Origin
- The user asked whether REA (the reverse-engineering toolkit in `~/workspace/REA`) could be used to build an open-source UiPath.
- Answer given: REA is a reverse-engineering toolkit, not an RPA platform. Decompiling UiPath breaks its EULA and creates copyright risk. The project is instead a clean-room design that borrows UiPath's concepts only.

## Decisions, in the order they were made
1. Purpose: personal tool → later confirmed as a **public open-source package** (pipx install, CI, docs, Apache-2.0).
2. Targets: **web only** in v1 (Playwright).
3. Authoring: **recorder → editable YAML**.
4. Runs: **CLI + local scheduler daemon**, artifacts in folders, no web UI.
5. Healing: **pluggable LLM, Groq default**, Ollama and Anthropic as options; human approval before any YAML change.
6. Stack: approach **A, pure Python**. Rust was discussed and reduced to **zero hand-written Rust**. The vault uses `cryptography` (Rust-backed). User: "i want to build a rpa app open source not to learn rust".
7. All 7 design sections were presented and approved in chat: architecture, YAML format, recorder/pick, runner/healing, scheduler/history, vault/security, testing/CI/milestones.

## Inputs from the user (untracked files in repo root)
- `core-features of UI-path.md`: notes proposing an all-Rust UiPath clone (Tauri, Tokio, Axum, thirtyfour, tch-rs). The features were mapped into the spec (§4). Most of its stack was rejected; reasons are in the spec, §3.
- `Promt.md`: a prompt for auditing a **different repo (Task-Master)**. Not related to open-rpa and not acted on. Its Robocorp video link was noted as background.

## State at end of session
- Repo: `~/workspace/open-rpa`, branch `main`, no remote.
- First commit contains the spec and this context note.
- **No code written.** Next gate: the user reviews the spec, then the `superpowers:writing-plans` skill produces the implementation plan, then the user picks how it gets executed.

## Next steps
1. User reviews the spec (§14 open questions: package name on PyPI; GitHub org and visibility).
2. Write the implementation plan for M1–M7 (one PR per milestone; the user merges with a merge commit or rebase, never squash).
3. Begin M1 after the plan is approved.
