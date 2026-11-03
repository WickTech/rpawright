# rpawright: Autonomous Runbook (M1 finish → M7)

> **For the controller session (Sonnet 5.5):** this is your operating manual. Read it fully, then follow
> it top to bottom without asking the user anything, except at the **Stop points** listed below.
> REQUIRED SKILLS: `superpowers:subagent-driven-development` (per plan), `superpowers:writing-plans`
> (per milestone), `superpowers:finishing-a-development-branch` (per milestone, adapted below).

- **Written:** 2026-11-02 by the Opus 5.5 controller, at the user's request.
- **User instruction (verbatim intent):** "make a plan for the rest of the steps that you can continue
  without my inputs and complete the task autonomously … use sonnet to continue the work."
- **Spec (binding authority):** `docs/superpowers/specs/2026-11-02-open-rpa-design.md`
- **M1 plan:** `docs/superpowers/plans/2026-11-02-m1-foundation.md`
- **Repo:** local `~/workspace/open-rpa`, remote `origin` = https://github.com/WickTech/rpawright (public)

## 0. State (updated after M1 execution)

This section was a handoff snapshot. M1 is now implemented and in review; for current state use `git log --oneline main..HEAD`, `gh pr list --state all`, the
current plan's ledger under `.superpowers/sdd/`, and `docs/superpowers/context/2026-11-02-session-context.md`.

- M1 (`m1-foundation`): complete, with the whole-branch review and one fix wave done. The PR is opened by the controller after the push (section 4, A4).
- Rulings R1-R9 for M1 live in the M1 ledger and are copied into the PR body.
- Deferred items carried into M2's plan: add browser tests for the xpath, nth and exact locators (needed by M4); `time-sensitive` waits should use the shared poll helper;
  the conftest `_browser` workaround (a module that uses both the `page` fixture and `run_workflow` still cannot nest Playwright).

## 1. Authority: what you may do without asking

Allowed (user-authorized 2026-11-02 by the instruction above):
- Commit on milestone branches (`m<N>-<slug>`); never commit to `main`.
- Push milestone branches to `origin`, and open PRs with `gh pr create`.
- Watch CI with `gh run watch` / `gh run view --log-failed`, and fix failures through implementer subagents, then push again.
- Write plans, docs, memory and the context note. Make rulings, recorded in each plan's ledger, as the SDD skill describes.

## 2. Stop points: stop and ask the user, never do these yourself

1. Merging any PR, or pushing to `main`. **The user merges, with a merge commit or rebase, never squash.**
2. Tags, GitHub Releases, PyPI publishing, PyPI Trusted Publisher setup (M7 `v0.1.0`).
3. Repo settings, secrets, or branch protection; adding API keys anywhere.
4. Anything needing real credentials or paid calls (real Groq, Anthropic or Ollama requests). Tests use fake providers and mocked HTTP only.
5. Force-push, history rewrite on pushed branches, or deleting branches or files outside this repo.
6. Installing services on the user's machine for real (`daemon install` must be tested against temp dirs only).
7. A plan so broken that every path forward is a guess (SDD skill rule).

At a stop point, finish all other independent work first, then send one message listing exactly what needs the user.

## 3. Model routing (always pass `model` explicitly)

| Role | Model |
|---|---|
| Controller (this session) | sonnet |
| Implementer, when the brief contains complete code or the change is small and mechanical | haiku |
| Implementer, from prose / multi-file / browser work | sonnet |
| Task reviewer | sonnet |
| Scoped re-review of a small fix | haiku |
| Fix rounds 4–5 (fresh implementer) | opus |
| Plan review for M2–M7 (before execution) | opus |
| Final whole-branch review, per milestone | opus |

## 4. Step A: finish M1

**A1. Review Task 5.**
- Run `bash <sdd>/scripts/review-package docs/superpowers/plans/2026-11-02-m1-foundation.md 4aeffe0 efd8c65`, where `<sdd>` is `~/.claude/plugins/cache/superpowers-dev/superpowers/6.4.2/skills/subagent-driven-development`.
- Dispatch the task reviewer (template `task-reviewer-prompt.md`). Give it the brief `.superpowers/sdd/2026-11-02-m1-foundation/task-5-brief.md`, the report `task-5-report.md`, the package path, and the M1 Global Constraints plus rulings R1, R3 and R6 from the ledger.
- Tell the reviewer about the 3 implementer concerns so it judges them on their merits.
- Run the fix loop as the skill describes. Record minors in the ledger.

**A2. Task 6** (example bot, e2e test, README quick start).
- Extract the brief with `scripts/task-brief … 6`. Dispatch a sonnet implementer.
- Rulings to carry into the dispatch:
  - R2: `login_v2.html` exists and submits.
  - The README already has a "Development" section written by the README task. Add a "Quick start" section above it, and change the roadmap's M1 status to "complete (PR open)".
- The plan's Step 6 says "ask the user before pushing". **Superseded:** pushing is authorized (section 1). The implementer commits only; the controller pushes in A4.
- Then review and fix loop as for any task.

**A3. Final whole-branch review.**
- Run `review-package … $(git merge-base main HEAD) HEAD`.
- Dispatch one **opus** reviewer using `../requesting-code-review/code-reviewer.md`. Point it at the ledger's `minor (deferred)` lines and rulings, and ask it to triage which must be fixed before merge.
- Then one fix dispatch (sonnet) with the full findings list, and one scoped re-review (haiku/sonnet). Record residual findings with rulings in the ledger.

**A4. Push and PR.**
- `git push -u origin m1-foundation`.
- `gh pr create --base main --head m1-foundation --title "M1: foundation (models, validate, runner, locator fallback, artifacts)"`. The PR body contains:
  - a summary;
  - the M1 exit criterion and how it is proven (test names);
  - test and coverage numbers;
  - the plan's Review Focus list;
  - **"Rulings made autonomously"**, every `Ruling:` line from the ledger with its cost-if-wrong;
  - deferred minors;
  - and it ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
- `gh run watch`. If any of the 6 matrix jobs fail, especially macOS or Windows, which have never run, fix the failure through an implementer subagent and a scoped re-review, push, and watch again. Repeat until green; after 3 failed CI fix attempts on the same job, record a ruling and continue.
- Do not merge.

**A5. Bookkeeping.**
- Copy the rulings into the PR body (done in A4), then `rm -rf .superpowers/sdd/2026-11-02-m1-foundation`.
- Update the context note and the memory status file (section 7).

## 5. Step B: M2 → M7 (stacked branches, no user checkpoints)

The user waived per-milestone plan approval and execution-method choice: always use **subagent-driven**. For each milestone N = 2…7, in order:

1. **Branch:** `git switch -c m<N>-<slug>` from the previous milestone branch's head, not from `main`, because earlier PRs aren't merged yet.
2. **Plan:** invoke `superpowers:writing-plans`, scope = spec §12 row M<N>.
   - Save to `docs/superpowers/plans/<date>-m<N>-<slug>.md`.
   - Read the actual code for the interfaces you consume (`src/rpawright/**`). Never rely on memory or earlier plans for names.
   - Keep the M1 header format, Global Constraints, Review Focus, and the Interfaces blocks.
3. **Plan review:** dispatch one **opus** subagent to check the plan against the spec section and the current code. It reports gaps, contradictions, and wrong interface names. Fix the plan, then commit it.
4. **Execute:** `superpowers:subagent-driven-development` with the pre-flight table, rulings and ledger, exactly as in M1.
5. **Finish:**
   - Final opus review, then one fix wave.
   - Push, then `gh pr create --base m<N-1>-<slug> --head m<N>-<slug>`. That gives a stacked PR, and GitHub retargets it to `main` when the base PR merges and its branch is deleted.
   - CI must be green.
   - Copy the rulings into the PR body, delete that plan's SDD workspace, and update the context note and memory.

Milestone anchors. These are the binding spec references plus traps the plan must handle:

| N | Slug | Spec | Must-handle notes |
|---|---|---|---|
| 2 | `m2-steps-flow` | §6.2–6.5, §12 | Remaining step types (§6.4), `if/for_each/call/set`, `inputs` + `rpawright run --input k=v`, Jinja2 `SandboxedEnvironment` with a filter allowlist (`fmt`, `where`, `prev_month`, `default`). The sandbox-escape test `{{ ''.__class__ }}` must fail. `on_error` accepts a step list. CSV, XLSX (openpyxl), `http` (httpx). `http` domain enforcement waits for M3; record a ruling. `call` is confined to `bots/`. File paths are confined to the workspace (no `../`). Regenerate the JSON Schema. (`WaitBody.frame` was already added in M1's fix wave.) |
| 3 | `m3-vault-policy` | §10, §8 | `cryptography>=44` (Argon2id m=64 MiB, t=3, p=4; AES-256-GCM), `keyring`, `RPAWRIGHT_VAULT_KEY` / key file `0600`, atomic writes. Domain-bound secrets give `PolicyViolation` and exit code 3. `allow_domains` is enforced via `context.route`. The redactor masks raw, URL-encoded and base64 forms. Screenshots use `mask=`. Traces are off for secret-using bots unless `--unsafe-trace`. `validate` warns on secret-looking literals. Tests use temp vault dirs and a fake keyring backend, never the real OS keyring. |
| 4 | `m4-recorder` | §7 | Recorder and `pick`. CI has no display, so the recorder must run headless in tests, driven by Playwright actions with the injected script. Golden-YAML tests. Password fields go to the vault (M3 API). `ruamel.yaml` keeps comments when appending. |
| 5 | `m5-healer` | §8 | Provider interface plus `groq`, `ollama` and `anthropic` over httpx. **All tests use a fake provider or mocked HTTP; no real API calls.** Model ids come from config, never hard-coded. Strict JSON parsing. Live verification checks uniqueness, visibility and the right kind of element for the action. `heal review` writes a diff only on confirmation (test with CliRunner input). Exit code 4. Reorder suggestions come from step stats; the data may need M6's store, so keep an in-memory or file stub with a ruling, or reorder M5 and M6. |
| 6 | `m6-scheduler` | §9 | SQLite store with numbered SQL migrations, the `runs` commands, the APScheduler daemon (subprocess per run, timeout, overlap, coalesce, hot reload, lock file), and notifications (webhook via httpx mocked, `command` with `shlex.quote`). Tests use `time-machine`. `daemon install` writes unit files to a temp dir in tests and never installs for real. |
| 7 | `m7-release` | §11–12 | Docs (getting-started, yaml-reference, security, healing, scheduling), 3 example bots plus a bundled demo site command, a `release.yml` workflow (tag `v*` builds and publishes to PyPI via Trusted Publishing), CHANGELOG. **Stop point:** do not tag, release or configure PyPI. Ask the user. |

## 6. Step C: final report to the user

When M7's PR is open and green, or at a stop point, send one message containing:
- the PR links in merge order;
- what each milestone delivers;
- every autonomous ruling, with its cost-if-wrong;
- deferred items;
- exactly what needs the user: merges, the PyPI/Trusted Publisher setup, and the `v0.1.0` tag.

## 7. Bookkeeping after every milestone (and before any long pause)

- `docs/superpowers/context/2026-11-02-session-context.md`: update "State" and "Next steps". Commit it on the current milestone branch.
- Memory `~/.claude/projects/-home-rishi-workspace-open-rpa/memory/project_status_2026-11-02.md` and the matching `MEMORY.md` line: current milestone, open PRs, next action.

## 8. Recovery after context compaction or a new session

1. Read this runbook.
2. `git branch -a`, `git log --oneline main..HEAD`, `gh pr list --state all`.
3. Read the current plan's ledger `.superpowers/sdd/<plan>/progress.md`. Tasks with a `complete` line are done; resume at the first task without one.
4. Continue from the first unfinished step in sections 4–6.
