# rpawright M1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the rpawright foundation. A hand-written YAML bot validates, runs in Chromium against the bundled demo site, uses fallback locators, and leaves a run folder with a step log and a failure screenshot.

**Architecture:** Pydantic v2 models describe the YAML exactly as users write it (one model per step type, unioned), so the generated JSON Schema matches the files users edit. A runner polls each step's locator candidates in priority order, dispatches each step to a handler, applies `retry`/`on_error`, and writes artifacts. A Typer CLI exposes `validate`, `schema` and `run`.

**Tech Stack:** Python 3.12+, uv, hatchling, Typer, Pydantic v2, ruamel.yaml, Playwright (sync API, Chromium), pytest + pytest-cov, ruff, mypy --strict.

**Spec:** `docs/superpowers/specs/2026-11-02-open-rpa-design.md` (approved 2026-11-02). M1 scope = spec §12 row M1. Later milestones (M2–M7) get their own plans after M1 merges.

## Global Constraints

- Package, CLI command and import name: `rpawright`. License: Apache-2.0.
- `requires-python = ">=3.12"`. CI matrix: ubuntu, macos, windows × Python 3.12, 3.13.
- `mypy --strict` must pass on `src/`. `ruff check` and `ruff format --check` must pass.
- Coverage minimum 85% (`--cov-fail-under=85`).
- Browser tests use only the local fixture site in `tests/fixtures/site/`, never live websites.
- Workflow `version` must equal `1`.
- Locator candidate kinds, in this order: `testid`, `role` (+ `name`), `label`, `text`, `css`, `xpath`. Each candidate has exactly one kind; optional modifiers are `nth` and `exact`.
- Locator polling interval: 250 ms. Default `policy.timeout_ms`: 15000. Default `policy.headless`: true.
- `on_error` defaults to `fail`. Allowed values in M1: `fail`, `continue`. A step list for `on_error` arrives in M2.
- Exit codes: `0` ok, `1` step failed, `2` invalid bot. Codes `3` and `4` arrive in M3 and M5.
- Run artifacts go to `runs/<bot-name>/<UTC timestamp YYYYMMDDTHHMMSSZ>/`.
- `policy.allow_domains` and `policy.heal` are parsed and validated in M1 but not enforced. Enforcement arrives in M3 and M5.
- Dependencies are locked with `uv.lock`, which is committed.
- One PR for M1, branch `m1-foundation`. The user merges it with a merge commit or rebase, never squash.

## Review Focus

1. **Invalid YAML syntax or a step with zero or two action keys:** expected is a one-line error with the file, step index and reason, exit code 2, and no traceback. Tests: Task 2.
2. **A locator candidate that matches several elements:** it must never be chosen. The runner falls through to the next candidate. If every candidate is ambiguous or missing, the error lists each candidate with its match count. Tests: Task 4.
3. **An element that appears late (about 1 s after page load):** it is still found within the timeout, and a slow or missing first candidate doesn't use up the whole timeout before the second is tried. Tests: Task 4.
4. **Unreachable URL or navigation error in `goto`:** the step fails with `StepError`, the run log and screenshot are still written, the browser is closed, and the exit code is 1. Tests: Task 5.
5. **Bot name containing spaces, slashes or unicode:** the run folder name is sanitized to `[A-Za-z0-9._-]` and the run doesn't crash. Tests: Task 5.

---

## File structure

```
pyproject.toml                      package metadata, deps, tool config (ruff, mypy, pytest, coverage)
LICENSE                             Apache-2.0 text
README.md                           what it is, install, quick start for M1
.gitignore                          .venv, runs/, __pycache__, .coverage, dist/
.github/workflows/ci.yml            lint-type + test matrix
src/rpawright/__init__.py           __version__ = "0.1.0.dev0"
src/rpawright/cli.py                Typer app: validate, schema, run, --version
src/rpawright/workflow/models.py    Target, Retry, Policy, step models, Workflow
src/rpawright/workflow/loader.py    load_workflow(), WorkflowError
src/rpawright/workflow/schema.py    workflow_json_schema()
schema/workflow.schema.json         generated, committed
src/rpawright/runner/errors.py      StepError, LocatorNotFound, AssertionFailed
src/rpawright/runner/locate.py      build_locator(), resolve_target()
src/rpawright/runner/steps.py       one handler per M1 action, HANDLERS map
src/rpawright/runner/artifacts.py   RunArtifacts (run dir, log.jsonl, screenshots, trace)
src/rpawright/runner/engine.py      run_workflow() -> RunResult
tests/conftest.py                   site_url fixture (threaded http.server), page fixture
tests/fixtures/site/*.html          demo login site, v2 "changed" page, late-element page, ambiguous page, iframe page
tests/unit/test_models.py, test_loader.py, test_schema.py
tests/browser/test_locate.py, test_engine.py
tests/e2e/test_demo_login.py
examples/bots/demo-login.yaml
```

---

### Task 1: Project scaffold, CI and fixture site

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `README.md`, `.gitignore`, `.github/workflows/ci.yml`, `src/rpawright/__init__.py`, `src/rpawright/cli.py`, `tests/conftest.py`, `tests/fixtures/site/login.html`, `tests/fixtures/site/dashboard.html`, `tests/unit/test_cli_version.py`

**Interfaces:**
- Produces:
  - `rpawright.__version__: str`
  - `rpawright.cli.app: typer.Typer` (entry point `rpawright = "rpawright.cli:app"`)
  - pytest fixture `site_url() -> str`, session-scoped, e.g. `"http://127.0.0.1:<port>"`, serving `tests/fixtures/site/`
  - pytest fixture `page() -> playwright.sync_api.Page`, a function-scoped headless Chromium page that is closed after each test

- [ ] **Step 1: Create the branch and write `pyproject.toml`.**
  - Run `git switch -c m1-foundation`.
  - Build backend: hatchling. Runtime deps: `typer>=0.12`, `pydantic>=2.7`, `ruamel.yaml>=0.18`, `playwright>=1.47`. Dev group: `pytest>=8`, `pytest-cov`, `mypy`, `ruff`.
  - Tool config: ruff `line-length = 100`, `target-version = "py312"`; mypy `strict = true` with `packages = ["rpawright"]`; pytest `testpaths = ["tests"]`, `addopts = "--cov=rpawright --cov-report=term-missing --cov-fail-under=85"`.

- [ ] **Step 2: Write the fixture site.**
  - `login.html`: an `<input id="email" aria-label="Email">`, an `<input id="password" type="password">` with `<label for="password">Password</label>`, and `<button id="signin">Sign in</button>`. Clicking the button navigates to `dashboard.html` only when both fields are non-empty.
  - `dashboard.html`: `<h1>Welcome</h1>` and `<table class="invoices">` with 2 rows.

- [ ] **Step 3: Write the failing test** in `tests/unit/test_cli_version.py`

```python
from typer.testing import CliRunner
from rpawright.cli import app
from rpawright import __version__

def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
```

- [ ] **Step 4: Run it and see it fail.** Run `uv sync && uv run pytest tests/unit/test_cli_version.py -v --no-cov`. Expected: FAIL (ImportError).

- [ ] **Step 5: Implement the code.** `src/rpawright/__init__.py` sets `__version__ = "0.1.0.dev0"`. `cli.py` defines a Typer app with a `--version` eager callback. Also write `tests/conftest.py` with `site_url` (`http.server.ThreadingHTTPServer` on port 0 in a daemon thread, directory `tests/fixtures/site`) and `page` (Playwright `sync_playwright`, Chromium launched headless).

- [ ] **Step 6: Run the test and see it pass.** Run `uv run playwright install chromium && uv run pytest tests/unit/test_cli_version.py -v --no-cov`. Expected: PASS.

- [ ] **Step 7: Write CI.** `.github/workflows/ci.yml` has two jobs:
  - `lint-type` (ubuntu, py3.12): `uv sync`, `ruff check`, `ruff format --check`, `mypy`.
  - `test` (matrix ubuntu/macos/windows × 3.12/3.13): `uv sync`, `uv run playwright install --with-deps chromium`, `uv run pytest`.

  Also add the LICENSE (Apache-2.0 full text), a README stub (name, one-line description, "pre-alpha"), and `.gitignore`.

- [ ] **Step 8: Commit.**
```bash
git add -A && git commit -m "chore: scaffold rpawright package, CI and fixture site"
```

### Task 2: Workflow models, loader and `validate`

**Files:**
- Create: `src/rpawright/workflow/__init__.py`, `src/rpawright/workflow/models.py`, `src/rpawright/workflow/loader.py`, `tests/unit/test_models.py`, `tests/unit/test_loader.py`
- Modify: `src/rpawright/cli.py` (add `validate`)

**Interfaces:**
- Produces (all models use `ConfigDict(extra="forbid")`):
  - `Target`: optional fields `testid`, `role`, `name`, `label`, `text`, `css`, `xpath` (all `str | None`), `nth: int | None`, `exact: bool = False`. Validator: exactly one of `testid/role/label/text/css/xpath` is set. `name` is allowed only with `role`. Property `kind -> str`.
  - `Retry`: `times: int = 0` (≥0), `delay_ms: int = 500` (≥0).
  - `Policy`: `allow_domains: list[str] = []`, `headless: bool = True`, `timeout_ms: int = 15000`, `heal: Literal["propose","apply_runtime","off"] = "propose"`.
  - `StepCommon`: `id: str | None`, `retry: Retry | None`, `on_error: Literal["fail","continue"] = "fail"`, `timeout_ms: int | None`.
  - Action bodies:
    - `TargetBody(target: list[Target] (min 1), frame: list[Target] | None)`
    - `FillBody(TargetBody + value: str)`
    - `PressBody(key: str, target: list[Target] | None, frame: list[Target] | None)`
    - `WaitBody(ms: int | None, target: list[Target] | None, state: Literal["visible","hidden"] = "visible", url_contains: str | None)`, with exactly one of `ms`, `target`, `url_contains`
    - `AssertBody(target: list[Target] | None, frame: list[Target] | None, text_contains: str | None, visible: bool | None, url_contains: str | None)`, which needs either a `target` or a `url_contains`
  - Step models (each subclasses `StepCommon`, each has exactly one action field):
    - `GotoStep(goto: str)`
    - `ClickStep(click: TargetBody)`
    - `FillStep(fill: FillBody)`
    - `PressStep(press: str | PressBody)`
    - `WaitStep(wait: int | WaitBody)`
    - `AssertStep(assert_: AssertBody = Field(alias="assert"))`
  - `Step = GotoStep | ClickStep | FillStep | PressStep | WaitStep | AssertStep`. Helper `action_name(step: Step) -> str` returns the YAML key (e.g. `"assert"`).
  - `Workflow`: `version: Literal[1]`, `name: str`, `description: str = ""`, `policy: Policy = Policy()`, `steps: list[Step]` (min 1). After validation, assign missing ids as `f"{action_name}-{index+1}"` and reject duplicate ids.
  - `loader.WorkflowError(Exception)` with fields `path: Path`, `message: str`; `str()` gives `"<path>: <message>"`.
  - `loader.load_workflow(path: Path) -> Workflow`, which raises `WorkflowError`.
  - CLI: `rpawright validate PATH...` prints `ok  <path>` or the error for each file, and exits 2 if any file is invalid.

- [ ] **Step 1: Write the failing tests.**

```python
# tests/unit/test_models.py
import pytest
from pydantic import ValidationError
from rpawright.workflow.models import Workflow, Target, action_name

def wf(steps: list[dict]) -> dict:
    return {"version": 1, "name": "t", "steps": steps}

def test_target_requires_exactly_one_kind() -> None:
    with pytest.raises(ValidationError):
        Target.model_validate({"css": "a", "text": "b"})
    with pytest.raises(ValidationError):
        Target.model_validate({"nth": 1})
    assert Target.model_validate({"role": "button", "name": "Go"}).kind == "role"

def test_name_only_with_role() -> None:
    with pytest.raises(ValidationError):
        Target.model_validate({"css": "a", "name": "x"})

def test_step_with_two_actions_rejected() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"goto": "http://x", "click": {"target": [{"css": "a"}]}}]))

def test_step_with_no_action_rejected() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"id": "lonely"}]))

def test_ids_autofilled_and_unique() -> None:
    w = Workflow.model_validate(wf([{"goto": "http://x"}, {"press": "Enter"}]))
    assert [s.id for s in w.steps] == ["goto-1", "press-2"]
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"id": "a", "goto": "http://x"}, {"id": "a", "press": "Enter"}]))

def test_assert_alias_and_action_name() -> None:
    w = Workflow.model_validate(wf([{"assert": {"url_contains": "/dash"}}]))
    assert action_name(w.steps[0]) == "assert"

def test_version_must_be_1_and_defaults() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate({"version": 2, "name": "t", "steps": [{"goto": "http://x"}]})
    w = Workflow.model_validate(wf([{"goto": "http://x"}]))
    assert (w.policy.timeout_ms, w.policy.headless, w.policy.heal) == (15000, True, "propose")
    assert w.steps[0].on_error == "fail"

def test_wait_body_needs_exactly_one_mode() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"wait": {"ms": 5, "url_contains": "x"}}]))
```

```python
# tests/unit/test_loader.py
from pathlib import Path
import pytest
from typer.testing import CliRunner
from rpawright.cli import app
from rpawright.workflow.loader import load_workflow, WorkflowError

def test_yaml_syntax_error_reports_line(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"; p.write_text("version: 1\nname: x\nsteps: [\n")
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert "line" in str(e.value) and str(p) in str(e.value)

def test_schema_error_reports_step_index(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("version: 1\nname: x\nsteps:\n  - goto: http://x\n  - click: {}\n")
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert "steps[1]" in str(e.value)

def test_validate_cli_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "g.yaml"; good.write_text("version: 1\nname: g\nsteps:\n  - goto: http://x\n")
    bad = tmp_path / "b.yaml"; bad.write_text("version: 1\nname: b\nsteps: []\n")
    r = CliRunner().invoke(app, ["validate", str(good)])
    assert r.exit_code == 0 and "ok" in r.stdout
    r = CliRunner().invoke(app, ["validate", str(good), str(bad)])
    assert r.exit_code == 2 and "Traceback" not in r.stdout
```

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/unit/test_models.py tests/unit/test_loader.py -v --no-cov`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the models** described in Interfaces, in `models.py`. Use `model_validator(mode="after")` for the one-of checks and for filling in ids. `Step` is a plain union; `extra="forbid"` makes each YAML step match exactly one model.

- [ ] **Step 4: Implement `load_workflow`.** Parse with `ruamel.yaml.YAML(typ="safe")`, turning `YAMLError` into `WorkflowError` with its `problem_mark.line + 1`. Validate with `Workflow.model_validate`, and turn the first `ValidationError` location into a path like `steps[1].click.target`. Then add the `validate` command.

- [ ] **Step 5: Run the tests and see them pass.** Run `uv run pytest tests/unit -v --no-cov`. Expected: all PASS. Then `uv run mypy` must report no errors.

- [ ] **Step 6: Commit.**
```bash
git add -A && git commit -m "feat(workflow): typed YAML models, loader and validate command"
```

### Task 3: JSON Schema export and drift check

**Files:**
- Create: `src/rpawright/workflow/schema.py`, `schema/workflow.schema.json`, `tests/unit/test_schema.py`
- Modify: `src/rpawright/cli.py` (add `schema`), `.github/workflows/ci.yml` (add a drift check to `lint-type`)

**Interfaces:**
- Consumes: `Workflow` (Task 2)
- Produces: `workflow_json_schema() -> dict[str, Any]`, which is `Workflow.model_json_schema(by_alias=True)` with `$id` set to `"https://github.com/WickTech/rpawright/schema/workflow.schema.json"`. The CLI command `rpawright schema [--out PATH]` prints the schema, or writes it when `--out` is given, as indented JSON with sorted keys and a trailing newline.

- [ ] **Step 1: Write the failing test.**

```python
import json
from pathlib import Path
from rpawright.workflow.schema import workflow_json_schema

def test_schema_uses_yaml_surface_names() -> None:
    text = json.dumps(workflow_json_schema())
    for key in ('"goto"', '"click"', '"fill"', '"assert"', '"testid"'):
        assert key in text
    assert '"assert_"' not in text

def test_committed_schema_is_current() -> None:
    committed = json.loads(Path("schema/workflow.schema.json").read_text())
    assert committed == workflow_json_schema()
```

- [ ] **Step 2: Run it and see it fail.** Run `uv run pytest tests/unit/test_schema.py -v --no-cov`. Expected: FAIL.

- [ ] **Step 3: Implement the code.** Write `schema.py` and the `schema` command, then generate the file with `uv run rpawright schema --out schema/workflow.schema.json`.

- [ ] **Step 4: Run it and see it pass.** Expected: PASS. Then add a CI step to `lint-type`: `uv run rpawright schema --out schema/workflow.schema.json && git diff --exit-code schema/`.

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(workflow): export JSON Schema with CI drift check"
```

### Task 4: Locator resolution with fallback

**Files:**
- Create: `src/rpawright/runner/__init__.py`, `src/rpawright/runner/errors.py`, `src/rpawright/runner/locate.py`, `tests/browser/test_locate.py`, plus fixture pages `tests/fixtures/site/login_v2.html` (the `#email` id renamed to `#user-email`; aria-label still `Email`), `late.html` (button added by `setTimeout` after 1000 ms), `ambiguous.html` (two `<button>Save</button>` and one `<button data-testid="save-main">Save</button>`), `frame.html` (an `<iframe title="Login" src="login.html">`)

**Interfaces:**
- Consumes: `Target` (Task 2)
- Produces:
  - `errors.StepError(Exception)` with `step_id: str`, `message: str`
  - `errors.LocatorNotFound(StepError)` with `tried: list[tuple[str, int]]`, i.e. (candidate description, match count)
  - `errors.AssertionFailed(StepError)`
  - `locate.build_locator(scope: Page | FrameLocator, t: Target) -> Locator`, which maps:
    - `testid` → `get_by_test_id`
    - `role` → `get_by_role(role, name=, exact=)`
    - `label` → `get_by_label(exact=)`
    - `text` → `get_by_text(exact=)`
    - `css` → `locator(css)`
    - `xpath` → `locator("xpath=" + xpath)`
    - and applies `.nth(n)` when `nth` is set
  - `locate.Resolved` (dataclass): `locator: Locator`, `index: int` (position of the winning candidate in the list)
  - `locate.resolve_target(page: Page, targets: list[Target], *, frame: list[Target] | None, timeout_ms: int, step_id: str, poll_ms: int = 250) -> Resolved`
    - Every poll, check the candidates in list order and return the first whose `count() == 1` and whose `.is_visible()` is true. Raise `LocatorNotFound` at the deadline.
    - When `frame` is set, first resolve it the same way on the page, then use that element's `.content_frame` as the scope.
  - `locate.describe(t: Target) -> str`, e.g. `role=button[name="Sign in"]`

- [ ] **Step 1: Write the failing tests** in `tests/browser/test_locate.py`

```python
import time
import pytest
from rpawright.workflow.models import Target
from rpawright.runner.locate import resolve_target
from rpawright.runner.errors import LocatorNotFound

T = Target.model_validate

def test_first_unique_candidate_wins(page, site_url) -> None:
    page.goto(f"{site_url}/login.html")
    r = resolve_target(page, [T({"css": "#email"}), T({"label": "Email"})], frame=None, timeout_ms=2000, step_id="s")
    assert r.index == 0

def test_falls_back_when_first_breaks(page, site_url) -> None:
    page.goto(f"{site_url}/login_v2.html")
    r = resolve_target(page, [T({"css": "#email"}), T({"role": "textbox", "name": "Email"})], frame=None, timeout_ms=2000, step_id="s")
    assert r.index == 1

def test_ambiguous_candidate_never_chosen(page, site_url) -> None:
    page.goto(f"{site_url}/ambiguous.html")
    r = resolve_target(page, [T({"text": "Save"}), T({"testid": "save-main"})], frame=None, timeout_ms=2000, step_id="s")
    assert r.index == 1

def test_all_fail_lists_counts(page, site_url) -> None:
    page.goto(f"{site_url}/ambiguous.html")
    with pytest.raises(LocatorNotFound) as e:
        resolve_target(page, [T({"text": "Save"}), T({"css": "#nope"})], frame=None, timeout_ms=600, step_id="s")
    assert [c for _, c in e.value.tried] == [3, 0]

def test_late_element_found_and_missing_first_does_not_block(page, site_url) -> None:
    page.goto(f"{site_url}/late.html")
    start = time.monotonic()
    r = resolve_target(page, [T({"css": "#never"}), T({"role": "button", "name": "Ready"})], frame=None, timeout_ms=5000, step_id="s")
    assert r.index == 1 and time.monotonic() - start < 3.0

def test_frame_scope(page, site_url) -> None:
    page.goto(f"{site_url}/frame.html")
    r = resolve_target(page, [T({"label": "Password"})], frame=[T({"css": "iframe[title=Login]"})], timeout_ms=3000, step_id="s")
    assert r.locator.count() == 1
```

  The `late.html` button text is `Ready`. In `ambiguous.html` all three buttons read `Save`, so the `text` candidate matches 3 elements.

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/browser/test_locate.py -v --no-cov`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `errors.py` and `locate.py`** as specified in Interfaces. Use `time.monotonic()` for the deadline and `page.wait_for_timeout(poll_ms)` between polls.

- [ ] **Step 4: Run the tests and see them pass.** Expected: 6 PASS, and `uv run mypy` is clean.

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(runner): locator fallback resolution with frame support"
```

### Task 5: Step handlers, engine, artifacts and `run`

**Files:**
- Create: `src/rpawright/runner/steps.py`, `src/rpawright/runner/artifacts.py`, `src/rpawright/runner/engine.py`, `tests/browser/test_engine.py`
- Modify: `src/rpawright/cli.py` (add `run`)

**Interfaces:**
- Consumes:
  - `Workflow`, `Step`, `action_name` (Task 2)
  - `resolve_target`, `describe`, `StepError`, `LocatorNotFound`, `AssertionFailed` (Task 4)
- Produces:
  - `steps.StepContext` (dataclass): `page: Page`, `timeout_ms: int`, `step_id: str`, `locator_used: str | None` (set by handlers that resolve a target)
  - `steps.HANDLERS: dict[str, Callable[[StepContext, Step], None]]`, with keys `goto, click, fill, press, wait, assert`
    - `goto`: turns any Playwright `Error` or timeout into a `StepError`
    - `press`: with a target, focus it then press; without one, use `page.keyboard.press`
    - `assert`: raises `AssertionFailed` with the expected and actual values
  - `artifacts.safe_name(s: str) -> str`: replaces anything outside `[A-Za-z0-9._-]` with `-`, collapses repeats, and returns `"bot"` if the result is empty
  - `artifacts.RunArtifacts(root: Path, bot_name: str)`
    - `.dir: Path` is `root/safe_name(bot_name)/<YYYYMMDDTHHMMSSZ>`, created on init
    - `.log(record: dict[str, object]) -> None` appends one JSON line to `log.jsonl`
    - `.screenshot(page: Page, step_id: str) -> Path` writes `fail-<step_id>.png`
  - `engine.StepRecord` (dataclass): `step_id, action, status: Literal["ok","failed","continued"], attempts: int, duration_ms: int, locator_used: str | None, error: str | None`
  - `engine.RunResult` (dataclass): `status: Literal["ok","failed"]`, `exit_code: int`, `failed_step: str | None`, `run_dir: Path`, `steps: list[StepRecord]`
  - `engine.run_workflow(wf: Workflow, *, runs_root: Path, headed: bool = False, step_mode: bool = False, trace: bool = False, confirm: Callable[[str], None] = input) -> RunResult`
    - Launches Chromium (headless = `wf.policy.headless and not headed`) and opens a fresh context and page.
    - For each step: build a `StepContext` with the timeout (`step.timeout_ms or wf.policy.timeout_ms`), call `confirm(step_id)` first when `step_mode` is on, and make up to `1 + retry.times` attempts with `retry.delay_ms` between them.
    - On final failure: take a screenshot and log the record. With `on_error == "continue"`, record the step as `continued` and carry on; otherwise stop with `exit_code = 1`.
    - With `trace`, record a Playwright trace and save `trace.zip`.
    - The browser is always closed in a `finally` block.
  - CLI: `rpawright run BOT [--headed] [--step] [--trace] [--runs-dir PATH (default ./runs)]`. A bot that fails to load exits 2 with the `WorkflowError` text. Otherwise it prints one line per step and exits with `RunResult.exit_code`.

- [ ] **Step 1: Write the failing tests** in `tests/browser/test_engine.py`. Build `Workflow` objects inline, using `site_url`.

```python
import json
from pathlib import Path
from rpawright.workflow.models import Workflow
from rpawright.runner.engine import run_workflow
from rpawright.runner.artifacts import safe_name

def login_steps(base: str, email_target: list[dict]) -> list[dict]:
    return [
        {"goto": f"{base}/login.html"},
        {"fill": {"target": email_target, "value": "me@x.dev"}},
        {"fill": {"target": [{"label": "Password"}], "value": "pw"}},
        {"click": {"target": [{"role": "button", "name": "Sign in"}]}},
        {"assert": {"target": [{"role": "heading", "name": "Welcome"}], "visible": True}},
    ]

def test_login_ok_writes_log(tmp_path: Path, site_url: str) -> None:
    wf = Workflow.model_validate({"version": 1, "name": "demo", "steps": login_steps(site_url, [{"css": "#email"}])})
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 0 and res.status == "ok"
    lines = (res.run_dir / "log.jsonl").read_text().splitlines()
    assert len(lines) == 5 and json.loads(lines[1])["locator_used"] == "css=#email"

def test_failure_stops_screenshots_exit1(tmp_path: Path, site_url: str) -> None:
    steps = login_steps(site_url, [{"css": "#missing"}])
    wf = Workflow.model_validate({"version": 1, "name": "demo", "policy": {"timeout_ms": 500}, "steps": steps})
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 1 and res.failed_step == "fill-2"
    assert (res.run_dir / "fail-fill-2.png").exists() and len(res.steps) == 2

def test_retry_counts_attempts(tmp_path: Path, site_url: str) -> None:
    wf = Workflow.model_validate({"version": 1, "name": "r", "policy": {"timeout_ms": 300}, "steps": [
        {"goto": f"{site_url}/login.html"},
        {"click": {"target": [{"css": "#nope"}]}, "retry": {"times": 2, "delay_ms": 10}}]})
    assert run_workflow(wf, runs_root=tmp_path).steps[1].attempts == 3

def test_on_error_continue(tmp_path: Path, site_url: str) -> None:
    wf = Workflow.model_validate({"version": 1, "name": "c", "policy": {"timeout_ms": 300}, "steps": [
        {"goto": f"{site_url}/login.html"},
        {"click": {"target": [{"css": "#nope"}]}, "on_error": "continue"},
        {"assert": {"url_contains": "login"}}]})
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 0 and [s.status for s in res.steps] == ["ok", "continued", "ok"]

def test_unreachable_goto_is_step_error(tmp_path: Path) -> None:
    wf = Workflow.model_validate({"version": 1, "name": "u", "policy": {"timeout_ms": 2000},
                                  "steps": [{"goto": "http://127.0.0.1:9/"}]})
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 1 and (res.run_dir / "log.jsonl").exists()

def test_safe_name_and_step_mode(tmp_path: Path, site_url: str) -> None:
    assert safe_name("my bot/ünï") == "my-bot-n"
    assert safe_name("///") == "bot"
    seen: list[str] = []
    wf = Workflow.model_validate({"version": 1, "name": "a b", "steps": [{"goto": f"{site_url}/login.html"}]})
    res = run_workflow(wf, runs_root=tmp_path, step_mode=True, confirm=seen.append)
    assert seen == ["goto-1"] and res.run_dir.parent.name == "a-b"
```

  Note on `safe_name("my bot/ünï")`: `ü` and `ï` are outside the allowed set and become `-`; repeated dashes collapse; trailing dashes are stripped. The result is `"my-bot-n"`.

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/browser/test_engine.py -v --no-cov`. Expected: FAIL (ImportError).

- [ ] **Step 3: Implement `artifacts.py`.** `safe_name` uses `re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "bot"`.

- [ ] **Step 4: Implement `steps.py` and `engine.py`** as specified in Interfaces. Each log record holds the fields of `StepRecord`, via `dataclasses.asdict`.

- [ ] **Step 5: Run the tests and see them pass.** Expected: 6 PASS, and `uv run mypy` is clean.

- [ ] **Step 6: Add the `run` command, with a CLI test** in `tests/browser/test_engine.py`. A bot file that fails validation must give exit 2. A good login bot written to `tmp_path` must give exit 0. Run `uv run pytest tests/browser -v --no-cov`. Expected: PASS.

- [ ] **Step 7: Commit.**
```bash
git add -A && git commit -m "feat(runner): step handlers, run engine, artifacts and run command"
```

### Task 6: End-to-end demo bot, docs and M1 PR

**Files:**
- Create: `examples/bots/demo-login.yaml`, `tests/e2e/test_demo_login.py`
- Modify: `README.md` (quick start)

**Interfaces:**
- Consumes: the `rpawright run` and `rpawright validate` commands (Tasks 2 and 5), and the `site_url` fixture (Task 1)

- [ ] **Step 1: Write `examples/bots/demo-login.yaml`.**
  - It uses the base URL placeholder `http://127.0.0.1:8765` and the login steps from Task 5.
  - The email target lists `{css: "#email"}` first and `{role: textbox, name: Email}` second, to show fallback.
  - Each step has a short comment.

- [ ] **Step 2: Write the failing e2e test.** It copies the example, replaces the base URL with `site_url`, and runs the CLI against both `login.html` and `login_v2.html`. For the v2 variant, replace `login.html` with `login_v2.html` and make `login_v2.html` submit to the same dashboard.

```python
from pathlib import Path
from typer.testing import CliRunner
from rpawright.cli import app

def run_example(tmp_path: Path, site_url: str, page_name: str) -> int:
    src = Path("examples/bots/demo-login.yaml").read_text()
    bot = tmp_path / "bot.yaml"
    bot.write_text(src.replace("http://127.0.0.1:8765", site_url).replace("login.html", page_name))
    return CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")]).exit_code

def test_example_validates() -> None:
    assert CliRunner().invoke(app, ["validate", "examples/bots/demo-login.yaml"]).exit_code == 0

def test_demo_login_original_site(tmp_path: Path, site_url: str) -> None:
    assert run_example(tmp_path, site_url, "login.html") == 0

def test_demo_login_survives_changed_id(tmp_path: Path, site_url: str) -> None:
    assert run_example(tmp_path, site_url, "login_v2.html") == 0
```

- [ ] **Step 3: Run it and see it fail, then fix.** Run `uv run pytest tests/e2e -v --no-cov`. The expected failure is a missing example file or `login_v2.html` not submitting. Fix the fixtures or the example only; the engine should need no changes.

- [ ] **Step 4: Run the full suite.**
  - Run `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest`.
  - Expected: all pass, coverage ≥ 85%, schema check clean.

- [ ] **Step 5: Update the README quick start.**
  - Install: `uv sync && uv run playwright install chromium`.
  - Commands: `rpawright validate`, `rpawright run examples/bots/demo-login.yaml --headed`.
  - Explain where run artifacts are written.

- [ ] **Step 6: Commit, push and open the PR.**
  - Commit:
```bash
git add -A && git commit -m "test(e2e): demo login bot with fallback locator; README quick start"
```
  - Push the `m1-foundation` branch and open a PR against `main` titled `M1: foundation (models, validate, runner, locator fallback, artifacts)`. The body lists the M1 exit criterion, test evidence and the Review Focus items.
  - Ask the user before pushing. Wait for CI to pass on all 6 matrix jobs. The user merges, never with squash.
