# rpawright M2 (Steps and Flow) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship every remaining v1 step type, sandboxed `{{ }}` expressions, control flow (`if`, `for_each`, `call`), CSV/XLSX/HTTP steps, and `retry`/`on_error` with step lists. The invoice example (spec §6.1 minus login) runs end to end through the CLI against a local fixture page and produces a CSV plus downloaded files.

**Architecture:** The M1 engine loop becomes a recursive executor: `run_steps` runs a step list, `run_step` applies retry/`on_error` and writes one log record with a `path`, and block steps (`if`, `for_each`, `call`, `on_error` lists) call back into it through `RunContext.run_block`, so handler modules never import the executor. Templating happens at execution time: a model walker renders every string field of a step into a copy of the step just before its handler runs, using a Jinja2 sandbox with an explicit filter allowlist. New handlers live in small modules grouped by concern and are merged into the existing `HANDLERS` map.

**Tech Stack:** M1 stack plus `jinja2`, `httpx` (tests inject `httpx.MockTransport`), `openpyxl`.

**Spec:** `docs/superpowers/specs/2026-11-02-open-rpa-design.md` (approved 2026-11-02). M2 scope = spec §12 row M2; relevant detail in §6, §8 and §10. Branch `m2-steps-flow` is stacked on `m1-foundation`.

## Global Constraints

- `requires-python = ">=3.12"`. CI matrix stays ubuntu, macos, windows × Python 3.12, 3.13. No shell-specific commands in tests; paths through `pathlib`.
- `mypy --strict` must pass on `src/`. `ruff check` and `ruff format --check` must pass.
- Coverage minimum 85% (`--cov-fail-under=85`).
- Browser tests use only the local fixture site in `tests/fixtures/site/`, never live websites. `http` tests use `httpx.MockTransport`, never the network. No secrets, no real API calls.
- Expressions: Jinja2 `SandboxedEnvironment` with a filter allowlist. Namespaces: `inputs`, `vars`, `secret`, `asset`, `env`, `today`, loop variables. `secret.*` resolves only in M3.
- Step ids are unique within a workflow, including nested steps. `on_error` defaults to `fail`; allowed values are `fail`, `continue` or a step list.
- Exit codes unchanged: `0` ok, `1` step failed, `2` invalid bot. Codes `3` and `4` arrive in M3 and M5.
- `policy.allow_domains` is enforced in M2 for the `http` step only. Navigation enforcement, the vault, domain-bound secrets and redaction remain M3. `policy.heal` stays unenforced until M5.
- Run artifacts go to `runs/<bot-name>/<UTC timestamp YYYYMMDDTHHMMSSZ>/`.
- Dependencies are locked with `uv.lock`, which stays committed. CI keeps using `uv sync --locked`.
- One PR for M2, branch `m2-steps-flow`, base `m1-foundation` until M1 merges. The user merges with a merge commit or rebase, never squash.

## Review Focus

1. **A path that escapes the workspace** (`../x`, an absolute path elsewhere, a symlink inside the workspace pointing outside): expected is a `StepError` naming the step and path; nothing is read or written outside the root. Tests: Task 5 (`test_workspace_*`), Task 7.
2. **An `http` request that redirects to a host outside `allow_domains`:** the redirect target is never contacted and the step fails naming the host. Tests: Task 8.
3. **A `download` step whose download never starts:** it fails with a `StepError` within the step timeout (no hang), the run exits 1 and the screenshot is written. Tests: Task 6.
4. **A CSV with unicode, commas, quotes and embedded newlines:** write then read returns identical rows, and the file is valid when opened by another tool. Tests: Task 7.
5. **Nested blocks:** an empty `for_each` list is a no-op and later steps still run; a failure or bad expression inside a nested step names the step id and its path (`for_each-6[2]/click-7`), and validate errors give the full YAML path. Tests: Tasks 2, 4, 5.

---

## Rulings (decisions where the spec is silent or ambiguous)

| # | Ruling | Why | Cost if wrong |
|---|---|---|---|
| R1 | `if` and `pause` are step types only. No common `if:` gating field or `pause:` field (spec §6.2 lists both as common fields and §6.4 lists both as step types). To gate one step, wrap it in an `if` step. | A common `if:` key cannot coexist with an `if` action key under "exactly one action key". | A `when:` common field can be added later without breaking files. |
| R2 | Variables are readable both as `vars.x` and as bare `x` (spec §6.1 uses bare `rows`). Lookup precedence: reserved namespaces, then loop variables, then vars. `into:`, `set:` keys, `as:`, input names and `vars:` keys must be identifiers and not reserved names. | Matches the spec example. | Low; bare access can be dropped with a deprecation. |
| R3 | `env.NAME` exposes only process variables named `RPAWRIGHT_ENV_NAME`; the prefix is stripped. | Spec says only the prefix rule. Stripped keeps bots readable. | Rename in docs and one test. |
| R4 | `secret.*` and `asset.*` raise `ExpressionError`: "secrets arrive with the vault in M3" / "assets arrive with assets.yaml in M3". | Spec places both in M3. | None. |
| R5 | The environment is `ImmutableSandboxedEnvironment` (a `SandboxedEnvironment` subclass that also blocks `append` and other mutation). Only `{{ }}` expressions are allowed; `{% %}` and `{# #}` are rejected. Filters allowed: `fmt, where, prev_month, default, length, lower, upper, trim, first, last, int, float, string, join`. Tests allowed: `defined, undefined, none, string, number`. Globals: none. | Smallest attack surface. | Adding a filter later is one line. |
| R6 | Only string fields are templated; numbers, booleans, enums and `id` are literal. A rendered string field always becomes text. Fields marked native (`set` values, `if`, `for_each.in`, `call.inputs`, `write_csv.rows`, `write_xlsx.rows`, `http.json`, `http.params`) keep the native object when a string is exactly one `{{ expr }}`. | Pydantic-typed `str` fields cannot hold a list; native only where a value is wanted. | A new native field is a one-line marker. |
| R7 | `if:` takes a whole-string `{{ expr }}` or a literal bool; Python truthiness decides. | Avoids "false"-the-string ambiguity. | Loader error, easy to relax. |
| R8 | Auto-generated ids use a single pre-order counter over the whole workflow (`goto-1`, `for_each-2`, `click-3`, `press-4`). Flat workflows keep their M1 ids. Log `path` is `id`, joined by `/`; `[i]` (0-based) follows a `for_each` id per iteration; `.then`, `.else`, `.on_error` follow the owning step id. | Nested index-based ids would collide across blocks. | Ids of steps after a block shift; no user-visible contract yet. |
| R9 | `retry` and `on_error` on a block step apply to the whole block: an inner failure that is not handled aborts the loop and fails the block. To skip failing items, put `on_error: continue` on the inner steps. | Spec example is silent on granularity; per-step is composable. | Docs note only. |
| R10 | `RunResult.failed_step` is the innermost failed step (the first record with status `failed`); the enclosing block records `nested step <id> failed: ...` and gets no extra screenshot. Failure screenshots are named from the path: `fail-<safe(path)>.png`. | Points at the real cause. | Cosmetic. |
| R11 | `on_error: [steps]`: on final failure take the screenshot, run the handler steps, record the step as `handled` and continue; exit code stays 0. A failing handler makes the step `failed`. No `error` variable is exposed. | Spec: "recorded as handled". | An `error` namespace can be added. |
| R12 | `call`: `bot` is workspace-relative and must resolve (symlinks resolved) inside `<workspace>/bots/`. Same page, downloads and artifacts; isolated vars; inputs passed explicitly and validated against the callee's `inputs:`; the callee's `policy` is ignored (caller's wins). Depth limit 5 (root = 0, so at most 5 nested calls); a callee whose resolved path is already on the call stack is a cycle. Calling the same bot twice in sequence is fine. Callee failure fails the caller's `call` step. | Spec §10. | Limits are constants. |
| R13 | All data file paths (csv/xlsx/download/upload/screenshot) resolve inside the workspace root (default: cwd; `--workspace PATH`); absolute paths inside the root are allowed; `..` and symlink escapes fail. Violations raise `StepError` in M2; M3 turns policy violations into exit 3. Run artifacts are exempt (engine-owned). Checks are at use time (a TOCTOU race is accepted). | Spec §10; exit code 3 is M3. | Exit-code change in M3. |
| R14 | `http`: the URL host must match `policy.allow_domains` (exact hostname, case-insensitive, or `*.example.com`); every redirect hop is checked before it is requested (max 5 hops); default expectation is any 2xx, overridden by `expect_status` (int or list); `into` holds `{status, headers (lower-case keys), json}` for JSON content types that parse, else `{status, headers, text}`. | Spec §10; M3 generalizes the guard. | M3 replaces `host_allowed`. |
| R15 | `download`: engine registers `page.on("download")` into a FIFO queue; the step waits for the next entry up to the step timeout and saves it. `suggested_name` is skipped (not trivial). Unconsumed downloads at the end are logged as `unclaimed_download`. | Matches the spec example. | Add later. |
| R16 | `pause`: headed runs call `page.pause()`; headless runs log "pause skipped (headless)" and continue. | Avoids hangs in unattended runs. | None. |
| R17 | `extract_table`: the target must be a `<table>`. Header row = the first row (its `<th>` or `<td>` cells), per spec "header from `<th>` or first row". Blank header names become `col<N>` (1-based); duplicates get `_2`, `_3`. Cell text is whitespace-collapsed `textContent`. Short rows are padded with `""`. | Spec says "header from `<th>` or first row". | Local to one function. |
| R18 | CSV: read as `utf-8-sig`, every value is text; written as UTF-8 with `\n` line endings; header = union of row keys in first-seen order; an empty row list writes an empty file. XLSX: first row is the header, empty cells become `""`, dates become ISO strings, fully empty rows are skipped; `sheet` defaults to the active sheet. | Cross-OS stable output. | Local. |
| R19 | `where(rows, key, value)` keeps rows whose `str(row[key]).strip() == str(value).strip()`; a missing key never matches. | Table cells are text; inputs may be numbers. | Local. |
| R20 | Inputs: types `string, int, float, bool`; CLI values are text coerced to the type (bool accepts true/false/yes/no/1/0, case-insensitive); `call` passes native values (an int may pass as `string`). A default may be a template (rendered with `today` and `env` only). Unknown or missing inputs, or a bad coercion, raise `InputError` and the CLI exits 2 before any browser starts. A repeated `--input k=v` keeps the last value. | Spec §12 and §6.1. | Local. |
| R21 | `run_workflow` accepts an optional `browser`; when given it is used and left open. Tests share a browser through a `run_bot` fixture; the module-scoped `_browser` fixture stays. | Falls out of the engine refactor; removes the nested-Playwright trap for flow tests. | None. |
| R22 | `log` writes `{"event": "log", "step_id", "path", "message"}` to `log.jsonl` and calls the `echo` callback (CLI prints `log  <message>` live, before the step summary). | Spec §6.4 lists `log`; M6 will read these records. | Cosmetic. |

## File structure

```
pyproject.toml                         + jinja2, httpx, openpyxl; dev + types-openpyxl
uv.lock                                refreshed
src/rpawright/workflow/expressions.py  NEW  sandbox env, evaluate(), check_syntax(), filters, ExpressionError
src/rpawright/workflow/templating.py   NEW  render_step(), expression_errors(): model-walking over fields
src/rpawright/workflow/models.py       + InputSpec, 18 step models, recursive Step, child_blocks(), ids
src/rpawright/workflow/loader.py       nested error paths, expression syntax errors
src/rpawright/runner/context.py        NEW  Scope, RunContext, StepContext (moved), StepRecord (moved)
src/rpawright/runner/executor.py       NEW  run_steps(), run_step(), NestedFailure (moved from engine)
src/rpawright/runner/inputs.py         NEW  InputError, resolve_inputs(), coerce helpers, build_namespace()
src/rpawright/runner/workspace.py      NEW  Workspace.resolve()
src/rpawright/runner/net.py            NEW  host_allowed(), make_client()
src/rpawright/runner/steps.py          M1 handlers + merged HANDLERS (StepContext re-exported)
src/rpawright/runner/steps_flow.py     NEW  set, log, pause, if, for_each, call
src/rpawright/runner/steps_page.py     NEW  select, hover, extract_text, extract_table, upload, screenshot, download
src/rpawright/runner/steps_data.py     NEW  read_csv, write_csv, read_xlsx, write_xlsx
src/rpawright/runner/steps_http.py     NEW  http
src/rpawright/runner/locate.py         + poll_until()
src/rpawright/runner/engine.py         run_workflow(): browser setup + run_steps
src/rpawright/cli.py                   run: --input, --workspace, echo
schema/workflow.schema.json            regenerated
tests/conftest.py                      + run_bot fixture
tests/unit/                            test_expressions, test_templating, test_inputs, test_workspace, test_net, test_models/test_loader additions
tests/browser/                         test_flow, test_page_steps, test_data_steps, test_http_step, test_engine additions
tests/fixtures/site/                   invoices.html, invoice_files/*, table.html, downloads.html, form.html
tests/e2e/test_invoices.py             the exit criterion
examples/bots/invoices.yaml            the invoice example
docs/yaml-reference.md                 NEW  every step, one example each
README.md                              feature marks, step reference link, roadmap
```

---

### Task 1: Dependencies and the expression sandbox

**Files:**
- Modify: `pyproject.toml` (deps), `uv.lock`
- Create: `src/rpawright/workflow/expressions.py`, `tests/unit/test_expressions.py`

**Interfaces:**
- Produces:
  - `ExpressionError(Exception)` with `expression: str`, `message: str`, `where: str = ""` (set by templating); `str()` gives `"<message> in {{ ... }}"` with the expression truncated to 80 chars.
  - `make_environment() -> ImmutableSandboxedEnvironment`: `StrictUndefined`, `filters`/`tests`/`globals` cleared then filled from the R5 allowlist, `autoescape=False`.
  - `evaluate(text: str, namespace: Mapping[str, object], *, native: bool) -> object`: when `native` and `text` is exactly one `{{ expr }}` (surrounding whitespace allowed), returns the object itself; otherwise returns a `str`. Any Jinja or sandbox error becomes `ExpressionError`.
  - `check_syntax(text: str) -> str | None`: compiles without running; returns a message or `None`. Rejects `{% %}`/`{# #}` and unknown filters.
  - `Unavailable(kind: str, message: str)`: namespace object whose attribute and item access raises `ExpressionError(message)`.
  - `SECRET: Unavailable`, `ASSET: Unavailable` (R4).
  - Filters `fmt(value, spec)` (date/datetime → `strftime`; int/float → `format(value, spec)`; else `ExpressionError`), `prev_month(value)` (date, datetime or ISO `YYYY-MM-DD` string → `date` on day 1 of the previous month), `where(rows, key, value)` (R19).
- Consumes: nothing.

- [ ] **Step 1: Add dependencies.** In `pyproject.toml` add runtime deps `jinja2>=3.1`, `httpx>=0.27`, `openpyxl>=3.1` and dev dep `types-openpyxl`. Run `uv lock && uv sync`. Expected: `uv.lock` changes; `uv run pytest -q` still passes (85 tests).

- [ ] **Step 2: Write the failing tests** in `tests/unit/test_expressions.py`.

```python
from datetime import date
import pytest
from rpawright.workflow.expressions import (ASSET, SECRET, ExpressionError, check_syntax, evaluate)

NS = {"n": 5, "rows": [{"Month": "2026-10", "Number": "INV-1"}], "today": date(2026, 1, 15)}

def test_whole_expression_returns_native_object() -> None:
    assert evaluate("{{ rows }}", NS, native=True) == NS["rows"]
    assert evaluate("  {{ n }} ", NS, native=True) == 5

def test_mixed_text_and_two_expressions_render_string() -> None:
    assert evaluate("INV-{{ n }}", NS, native=True) == "INV-5"
    assert evaluate("{{ n }}{{ n }}", NS, native=True) == "55"

def test_native_false_always_returns_text() -> None:
    assert evaluate("{{ n }}", NS, native=False) == "5"
    assert evaluate("no braces", NS, native=True) == "no braces"

def test_undefined_name_is_a_clear_error() -> None:
    with pytest.raises(ExpressionError, match="'missing' is undefined"):
        evaluate("{{ missing }}", NS, native=True)

@pytest.mark.parametrize("expr", [
    "{{ ''.__class__ }}", "{{ ().__class__.__mro__ }}", "{{ lipsum.__globals__ }}",
    "{{ inputs.__class__ }}", "{{ inputs.__init__.__globals__ }}", "{{ cycler }}",
    "{{ range(3) }}", "{{ dict }}", "{{ '{0.__class__}'.format('') }}",
    "{{ n | attr('__class__') }}", "{{ rows.append(1) }}", "{% for i in rows %}x{% endfor %}",
])
def test_sandbox_escapes_fail_with_expression_error(expr: str) -> None:
    with pytest.raises(ExpressionError):
        evaluate(expr, {**NS, "inputs": {"a": 1}}, native=True)

def test_secret_and_asset_raise_milestone_message() -> None:
    with pytest.raises(ExpressionError, match="secrets arrive with the vault in M3"):
        evaluate("{{ secret.vendor_pass }}", {"secret": SECRET}, native=True)
    with pytest.raises(ExpressionError, match="M3"):
        evaluate("{{ asset['x'] }}", {"asset": ASSET}, native=True)

def test_check_syntax() -> None:
    assert check_syntax("plain") is None and check_syntax("{{ n | length }}") is None
    assert check_syntax("{{ 1 + }}") is not None
    assert "nope" in (check_syntax("{{ n | nope }}") or "")
    assert "only {{ }}" in (check_syntax("{% if n %}x{% endif %}") or "")

def test_filters() -> None:
    ev = lambda s, **ns: evaluate(s, {**NS, **ns}, native=True)  # noqa: E731
    assert ev("{{ today | prev_month | fmt('%Y-%m') }}") == "2025-12"
    assert ev("{{ d | prev_month }}", d=date(2026, 3, 31)) == date(2026, 2, 1)
    assert ev("{{ rows | where('Month', '2026-10') }}") == NS["rows"]
    assert ev("{{ rows | where('Month', '2026-09') }}") == []
    assert ev("{{ rows | where('Nope', 1) }}") == []
    assert ev("{{ missing | default('d') }}") == "d"
    assert ev("{{ ' A ' | trim | lower }}-{{ 'b' | upper }}") == "a-B"
    assert ev("{{ 7 | fmt('03d') }}") == "007"
    assert ev("{{ [1, 2] | join(',') }}{{ rows | length }}") == "1,21"
```

- [ ] **Step 3: Run the tests and see them fail.** Run `uv run pytest tests/unit/test_expressions.py --no-cov -q`. Expected: FAIL (ImportError).

- [ ] **Step 4: Implement `expressions.py`.** Build the environment per R5; reuse Jinja's own `default`, `length`, `lower`, `upper`, `trim`, `first`, `last`, `int`, `float`, `string`, `join` implementations from `jinja2.defaults.DEFAULT_FILTERS` and the five tests from `DEFAULT_TESTS`; clear `globals`. Whole-expression rule (the non-obvious part):

```python
def _whole_inner(env: Environment, text: str) -> str | None:
    s = text.strip()
    kinds = [tok[1] for tok in env.lex(s)]          # (lineno, token_type, value)
    if (s.startswith("{{") and s.endswith("}}") and not s.startswith("{{-")
            and not s.endswith("-}}") and kinds.count("variable_begin") == 1
            and kinds.count("variable_end") == 1 and "data" not in kinds
            and not {"block_begin", "comment_begin"} & set(kinds)):
        return s[2:-2]
    return None   # then: env.compile_expression(inner, undefined_to_none=False)()
```

  Everything else renders with `env.from_string(text).render(**namespace)`. Wrap every exception (`TemplateError`, `SecurityError`, `TypeError`, ...) in `ExpressionError`. Statements: `check_syntax` and `evaluate` both reject any parsed node that is not `Output`/`TemplateData` (`env.parse(text).body`) with "only {{ }} expressions are allowed". `Unavailable` implements `__getattr__` and `__getitem__`.

- [ ] **Step 5: Run the tests and see them pass.** Run `uv run pytest tests/unit/test_expressions.py --no-cov -q && uv run mypy && uv run ruff check`. Expected: PASS, clean.

- [ ] **Step 6: Commit.**
```bash
git add -A && git commit -m "feat(workflow): sandboxed expression engine with filter allowlist"
```

### Task 2: Models for all steps, inputs/vars, nested ids, loader paths, syntax validation, schema

**Files:**
- Modify: `src/rpawright/workflow/models.py`, `src/rpawright/workflow/loader.py`, `schema/workflow.schema.json`, `tests/unit/test_models.py`, `tests/unit/test_loader.py`, `tests/unit/test_schema.py`
- Create: `src/rpawright/workflow/templating.py`, `tests/unit/test_templating.py`

**Interfaces:**
- Consumes: `check_syntax`, `ExpressionError`, `evaluate` (Task 1); M1 `_Model`, `StepCommon`, `TargetBody`, `Target`, `Workflow`, `action_name`.
- Produces in `models.py` (all `extra="forbid"`; YAML key aliases for Python keywords; `populate_by_name` stays off for new models):
  - `RESERVED_NAMES = frozenset({"inputs","vars","secret","asset","env","today"})`; `VarName = Annotated[str, AfterValidator]` (identifier, not reserved).
  - `InputSpec(type: Literal["string","int","float","bool"]="string", default: str|int|float|bool|None=None)`; a non-template `default` must match `type`.
  - `Workflow` gains `inputs: dict[str, InputSpec] = {}` (keys are `VarName`) and `vars: dict[VarName, Any] = {}`.
  - `StepCommon.on_error: Literal["fail","continue"] | list[Step]`.
  - Bodies: `SelectBody(TargetBody; value: str|None, label: str|None)` exactly one; `ExtractBody(TargetBody; into: VarName)`; `DownloadBody(to: str)`; `UploadBody(TargetBody; file: str)`; `ScreenshotBody(path: str|None=None, full_page: bool=False)`; `HttpBody(method: Literal["GET","POST","PUT","PATCH","DELETE","HEAD"]="GET", url: str, headers: dict[str,str]={}, params: dict[str,Any]={}, json_: Any=None (alias "json"), body: str|None=None, into: VarName|None=None, expect_status: int|list[int]|None=None)` with `json` and `body` mutually exclusive; `ReadCsvBody(path: str, into: VarName)`; `WriteCsvBody(path: str, rows: str|list[dict[str,Any]])`; `ReadXlsxBody(path, sheet: str|None, into)`; `WriteXlsxBody(path, rows, sheet: str|None)`; `ForEachBody(in_: str|list[Any] (alias "in"), as_: VarName (alias "as"), steps: list[Step] (min 1))`; `CallBody(bot: str, inputs: dict[str,Any]={})`; `LogBody(message: str)`.
  - Steps: `SelectStep`, `HoverStep(hover: TargetBody)`, `ExtractTextStep(extract_text: ExtractBody)`, `ExtractTableStep`, `DownloadStep`, `UploadStep`, `ScreenshotStep`, `HttpStep`, `ReadCsvStep`, `WriteCsvStep`, `ReadXlsxStep`, `WriteXlsxStep`, `SetStep(set: dict[VarName, Any], min 1)`, `IfStep(if_: str|bool alias "if", then: list[Step] (min 1), else_: list[Step]=[] alias "else")`, `ForEachStep(for_each: ForEachBody)`, `CallStep(call: CallBody)`, `PauseStep(pause: str|None)` (required key, nullable message), `LogStep(log: LogBody)`.
  - `Step` = the M1 union plus these 18. `_ACTION_NAMES` extended; `ACTION_NAMES: dict[type, str]` becomes public.
  - Class markers on models: `NATIVE_FIELDS: ClassVar[frozenset[str]]` and `LAZY_FIELDS: ClassVar[frozenset[str]]` (R6): native = `SetStep:{set}`, `IfStep:{if_}`, `ForEachBody:{in_}`, `CallBody:{inputs}`, `WriteCsvBody/WriteXlsxBody:{rows}`, `HttpBody:{json_,params}`; lazy (never rendered up front) = `StepCommon:{on_error}`, `IfStep:{then,else_}`, `ForEachBody:{steps}`.
  - `child_blocks(step: Step) -> list[tuple[str, list[Step]]]`: labels `then`, `else`, `steps`, `on_error`, in that order, only non-empty lists.
  - `iter_steps(steps: list[Step]) -> Iterator[Step]`: pre-order, uses `child_blocks`.
  - `Workflow` id pass: fill missing ids with `f"{action}-{n}"`, `n` = 1-based position in `iter_steps`; reject duplicates across the whole tree with `duplicate step id 'x'`.
- Produces in `templating.py`:
  - `iter_strings(model: BaseModel, path: str) -> Iterator[tuple[str, str]]`: every string field (skipping `id` and LAZY fields), path in YAML names (aliases), e.g. `fill.target[0].name`.
  - `render_step(step: Step, namespace: Mapping[str, object]) -> Step`: returns a copy with every string field rendered via `evaluate` (`native` per marker, R6, inherited by the subtree below a native field), using `model_copy(update=...)` recursively through nested models, lists and dicts; lazy fields and `id` are passed through; on `ExpressionError` sets `.where` to the field path (e.g. `fill.value`) and re-raises.
  - `expression_errors(wf: Workflow) -> list[str]`: `steps[i]<nested path>.<field>: bad expression: <msg>` for every string in every step (recursing into `child_blocks`, e.g. `steps[2].for_each.steps[0].click.target[0].name`), plus `vars.<k>` and `inputs.<k>.default`.

- [ ] **Step 1: Write the failing tests.**
  - `test_models.py`: `test_ids_unique_across_nested_blocks` (`for_each` containing `{"id":"a"}` and a top-level `{"id":"a"}` is rejected with `duplicate step id 'a'`); `test_auto_ids_use_preorder_counter` (`[goto, for_each{click}, press]` → ids `goto-1, for_each-2, click-3, press-4`); `test_if_for_each_call_aliases` (YAML keys `if/then/else`, `in/as` validate; `if_`/`in_` rejected); `test_pause_requires_key` (`{"id": "x"}` alone is rejected: no action); `test_on_error_accepts_step_list`; `test_select_needs_exactly_one_of_value_label`; `test_http_json_and_body_exclusive`; `test_input_default_must_match_type`; `test_reserved_names_rejected` (`into: inputs`, `as: today`, `vars: {secret: 1}`).
  - `test_loader.py`: `test_nested_error_names_full_path`: a bot whose `for_each.steps[0]` is `click: {}` reports `steps[1].for_each.steps[0].click.target: ...` (plus `Field required`-style text), not a union member name; `test_on_error_list_error_path` (`on_error: [{click: {}}]` → `steps[0].on_error[0].click.target`); `test_bad_expression_reported_with_path`: `fill.value: "{{ 1 + }}"` → message contains `steps[1].fill.value: bad expression:` and `validate` exits 2; `test_nested_bad_expression_path`; `test_vars_and_input_default_expression_checked`; all M1 loader tests stay unchanged.
  - `test_templating.py`: `test_render_step_renders_target_values` (`click: target: [{role: link, name: "{{ inv.Number }}"}]` → name `INV-1`, `exact` untouched); `test_native_field_keeps_list` (`write_csv.rows: "{{ rows }}"` → the list; `set: {a: "{{ n }}"}` → int `5`); `test_text_field_never_native` (`fill.value: "{{ n }}"` → `"5"`); `test_lazy_fields_not_rendered` (`for_each.steps` contain `{{ inv }}` unrendered while `in` is rendered); `test_id_not_rendered`; `test_expression_error_sets_where` (`.where == "fill.value"`).
  - `test_schema.py`: add `test_schema_has_new_steps_and_yaml_names`: JSON text contains `"for_each"`, `"extract_table"`, `"expect_status"`, `"then"`, `"else"`, `"if"`, `"in"`, `"as"`, `"json"`; does not contain `"if_"`, `"else_"`, `"in_"`, `"as_"`, `"json_"`. The committed-schema test fails until Step 5.

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/unit --no-cov -q`. Expected: new tests FAIL; the 85-test baseline for untouched tests still passes.

- [ ] **Step 3: Implement the models.** Forward references: `Step` is defined after the step classes that mention it, so annotate nested lists as `list["Step"]` and call `model_rebuild()` on every step and body model that holds one (`StepCommon` subclasses, `IfStep`, `ForEachBody`, `ForEachStep`) once `Step` exists; confirm `Workflow.model_json_schema()` works with the recursion. New-field defaults must not let a step with no action key validate (hence `PauseStep.pause` has no default).

- [ ] **Step 4: Implement the loader changes.** `_STEP_MODELS` and `_COMMON_FIELDS` come from `ACTION_NAMES` (no hand-kept list). Generalize `_first_error` for nesting: walk each error's `loc` together with the raw `data`; whenever the walk reaches a step dict inside a list under `steps`, `then`, `else` or `on_error`, keep the error only if its next `loc` segment is the model name for that step's single action key (zero or two keys → the existing "needs exactly one action key" message with the full path prefix), then drop that segment; also drop union-branch segments that start with `literal[` or `list[` (the `on_error` union). Then format with `_format_loc`, mapping `then`/`else_`... to YAML names via the error's field alias. After a successful `model_validate`, call `expression_errors(wf)` and raise `WorkflowError(path, first)` (pydantic path wording preserved).

- [ ] **Step 5: Implement `templating.py`, regenerate the schema.** Run `uv run rpawright schema --out schema/workflow.schema.json`.

- [ ] **Step 6: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check && uv run ruff format --check`. Expected: all PASS (85 existing plus new), coverage >= 85%.

- [ ] **Step 7: Commit.**
```bash
git add -A && git commit -m "feat(workflow): models for all v1 steps, inputs, nested ids and expression validation"
```

### Task 3: Recursive executor, RunContext, on_error step lists, poll helper

This is the engine refactor. All 85 existing tests must stay green after it; the new behavior is additive.

**Files:**
- Create: `src/rpawright/runner/context.py`, `src/rpawright/runner/executor.py`, `tests/unit/test_executor.py` (pure-logic parts), additions to `tests/browser/test_engine.py`
- Modify: `src/rpawright/runner/engine.py`, `src/rpawright/runner/steps.py`, `src/rpawright/runner/locate.py`, `tests/conftest.py`, `tests/browser/test_locate.py`
- Existing tests touched: `tests/browser/test_steps.py::run_step` keeps working unchanged (`StepContext(page=, timeout_ms=, step_id=)` still constructs; the new `run` and `path` fields default). `tests/browser/test_engine.py` keeps calling `run_workflow(wf, runs_root=...)`; record fields only gain `path`. `tests/e2e/test_demo_login.py` is untouched. Check these three modules first and run them before and after.

**Interfaces:**
- Consumes: `Step`, `Workflow`, `Policy`, `action_name`, `child_blocks` (Task 2); `RunArtifacts`, `StepError`, `HANDLERS`, `resolve_target`.
- Produces in `context.py`:
  - `StepRecord` (moved from `engine.py`, re-exported there): existing fields plus `path: str = ""`, and `status: Literal["ok","failed","continued","handled"]`.
  - `Scope(inputs: dict[str, object], vars: dict[str, object], loop: dict[str, object])` (dataclass, defaults empty).
  - `RunContext` (dataclass): `page: Page`, `artifacts: RunArtifacts`, `policy: Policy`, `scope: Scope`, `headed: bool`, `step_mode: bool`, `confirm: Callable[[str], object]`, `echo: Callable[[str], None]`, `records: list[StepRecord]`, `downloads: queue.Queue[Download]`, `run_block: Callable[[list[Step], str], None]` (set by the executor), plus fields added by later tasks with defaults (`workspace`, `env`, `today`, `http_transport`, `call_stack`).
  - `StepContext` (moved from `steps.py`, re-exported there): existing `page, timeout_ms, step_id, locator_used`, plus `run: RunContext | None = None`, `path: str = ""`, and method `require_run() -> RunContext` (raises `StepError` if `run` is None).
- Produces in `executor.py`:
  - `NestedFailure(StepError)`.
  - `run_step(run: RunContext, step: Step, base_path: str) -> StepRecord`: never raises for step failures. Path = `base_path + "/" + id` (just `id` when `base_path` is empty). Confirms (`--step`) first, then up to `1 + retry.times` attempts with `retry.delay_ms`; catches `StepError`, `PlaywrightError`, and, as a safety net, any other `Exception` (message `"<ExceptionType>: <text>"`) so a handler bug yields exit 1 with a log and screenshot, not a traceback. Failure handling: `continue` → `continued`; step list → screenshot, then `run_steps(run, step.on_error, path + ".on_error")`, success → `handled`, failure → `failed` with `"...; on_error handler failed: ..."`; otherwise `failed`. `NestedFailure` errors skip the screenshot (R10). Writes the record to `log.jsonl` (`{"event":"step", ..., "path": path}`) and appends it to `run.records`.
  - `run_steps(run: RunContext, steps: list[Step], base_path: str = "") -> None`: runs in order; on a `failed` record raises `NestedFailure(step_id, f"nested step {id} failed: {error}")` (R9, R10).
- Produces in `locate.py`: `poll_until(page: Page, check: Callable[[], T | None], *, timeout_ms: int, poll_ms: int = 250) -> T | None`: always calls `check` once, returns its first non-None result, or `None` at the deadline; each sleep is `min(poll_ms, remaining)` so it never overshoots. `_poll` also clamps its sleep (M1 ledger).
- Produces in `engine.py`: `run_workflow(wf, *, runs_root, headed=False, step_mode=False, trace=False, confirm=input, browser: Browser | None = None, echo: Callable[[str], None] = ..., ...)` (later tasks add `inputs`, `workspace`, `bot_path`, `http_transport`, `env`, `today`). When `browser` is given it is used and not closed (R21). The context is created with `accept_downloads=True` and `page.on("download", run.downloads.put)`; leftover downloads at the end are logged as `{"event": "unclaimed_download", "name": ...}`. `failed_step` = first `failed` record (R10).
- Produces in `tests/conftest.py`: fixture `run_bot(_browser, tmp_path) -> Callable[..., RunResult]` taking a dict `{"steps": [...], ...}` (adds `version: 1`, `name: "t"`), calling `run_workflow(..., runs_root=tmp_path/"runs", browser=_browser, workspace=tmp_path)`; extra keyword arguments pass through.

- [ ] **Step 1: Write the failing tests.**
  - `tests/browser/test_locate.py` (page fixture): `test_poll_until_returns_first_value`; `test_poll_until_times_out_and_does_not_overshoot` (timeout 300 ms, poll 250 ms, `time.monotonic()` elapsed `< 0.45`, returns `None`); `test_build_locator_xpath_nth_exact` against `ambiguous.html` (three `Save` buttons): `{"xpath": "//button"}` has count 3; `{"text":"Save","nth":1}` resolves to the second; `{"role":"button","name":"Sav","exact":True}` matches 0 while `exact: False` matches 3 (M1 ledger, needed by M4).
  - `tests/browser/test_engine.py`: `test_on_error_step_list_runs_handler_and_continues` (steps: `goto login.html`; `click` of `#missing` with `timeout_ms: 300`, `on_error: [{"fill": {"target":[{"css":"#email"}], "value":"fallback@x.dev"}}]`; then `assert` the email field visible): result `ok`, exit 0, record statuses `["ok","handled","ok","ok"]`, a `fail-*.png` exists; `test_on_error_handler_failure_fails_step` (handler also fails → status `failed`, exit 1, error contains `on_error handler failed`); `test_unexpected_exception_is_logged_not_traceback` (monkeypatch a handler to raise `RuntimeError("boom")`: exit 1, log has `RuntimeError: boom`); `test_run_workflow_uses_injected_browser` (a module that requests both the `page` and `run_bot` fixtures runs a bot without a nested-Playwright error, and `_browser.is_connected()` is still true afterwards).
  - `tests/browser/test_flow.py` (new, only uses `run_bot`): `test_records_carry_path_and_failed_step_is_innermost` is added in Task 5 once blocks exist; here add `test_log_records_have_path_equal_to_id_for_top_level_steps`.

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/browser/test_locate.py tests/browser/test_engine.py --no-cov -q`. Expected: new tests FAIL, old ones pass.

- [ ] **Step 3: Implement `context.py` and move `StepContext`/`StepRecord`.** Keep `from rpawright.runner.steps import StepContext, HANDLERS` and `from rpawright.runner.engine import StepRecord, RunResult` working.

- [ ] **Step 4: Implement `executor.py`** by moving `_attempt_step` and the per-step body of `run_workflow` into `run_step`; `RunContext.run_block` is set to `lambda steps, path: run_steps(run, steps, path)` by `run_workflow` before the first step.

- [ ] **Step 5: Implement `poll_until` and convert M1 polling to it:** `_wait_url`, the `text_contains` loop in `_assert`, and `_wait_hidden` in `steps.py`. Behavior and all M1 error messages stay identical.

- [ ] **Step 6: Slim `run_workflow`** to browser/context/trace setup, download listener, `run_steps` in a `try/except NestedFailure`, and the result. Add the `run_bot` fixture.

- [ ] **Step 7: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check`. Expected: all 85 original tests PASS plus the new ones.

- [ ] **Step 8: Commit.**
```bash
git add -A && git commit -m "refactor(runner): recursive executor, RunContext, on_error step lists, poll helper"
```

### Task 4: Runtime templating, inputs and vars, `set`/`log`/`pause`, `--input`

**Files:**
- Create: `src/rpawright/runner/inputs.py`, `src/rpawright/runner/steps_flow.py`, `tests/unit/test_inputs.py`
- Modify: `src/rpawright/runner/executor.py` (render before dispatch), `src/rpawright/runner/engine.py`, `src/rpawright/runner/steps.py` (merge `FLOW_HANDLERS`), `src/rpawright/cli.py`, `tests/browser/test_flow.py`, `tests/e2e/test_demo_login.py` (add one CLI test)

**Interfaces:**
- Consumes: `evaluate`, `SECRET`, `ASSET`, `ExpressionError` (Task 1); `render_step`, `InputSpec`, `Workflow` (Task 2); `RunContext`, `Scope`, `run_step` (Task 3).
- Produces in `inputs.py`:
  - `InputError(Exception)`.
  - `build_namespace(scope: Scope, *, env: Mapping[str, str], today: date) -> dict[str, object]`: bare vars, then loop variables, then `inputs`, `vars`, `secret`, `asset`, `env` (only `RPAWRIGHT_ENV_*`, prefix stripped, R3), `today` (R2 precedence).
  - `resolve_inputs(wf: Workflow, provided: Mapping[str, object], *, env: Mapping[str, str], today: date) -> dict[str, object]` (R20).
  - `init_vars(wf: Workflow, namespace_factory: Callable[[], dict[str, object]], scope: Scope) -> None`: renders `vars:` in order (native), each seeing the earlier ones.
  - `parse_input_pairs(pairs: list[str]) -> dict[str, str]`: `k=v`, split on the first `=`; a pair without `=` raises `InputError`.
- Produces in `steps_flow.py`: `FLOW_HANDLERS: dict[str, Callable[[StepContext, Step], None]]` with `set`, `log`, `pause` (this task); `if`, `for_each`, `call` arrive in Task 5.
  - `set`: writes each rendered value into `run.scope.vars`.
  - `log`: R22. `pause`: R16.
- `executor.run_step` now calls `render_step(step, build_namespace(run.scope, env=run.env, today=run.today))` inside each attempt; `ExpressionError` becomes `StepError(step_id, f"{where}: {message}")` and is not retried.
- Changes `run_workflow(...)`: new keyword parameters `inputs: Mapping[str, object] | None = None`, `env: Mapping[str, str] | None = None` (default `os.environ`), `today: date | None = None`; raises `InputError` before launching a browser. `RunContext` gains `env: Mapping[str, str]` and `today: date`.
- CLI `run`: `--input/-i` (repeatable `k=v`); `InputError` prints `error  <message>` and exits 2.

- [ ] **Step 1: Write the failing tests.**
  - `test_inputs.py`: `test_env_namespace_only_prefixed` (`{"RPAWRIGHT_ENV_REGION":"eu","HOME":"/h","PATH":"x"}` → `env == {"REGION":"eu"}`); `test_namespace_precedence` (a loop variable shadows a var of the same name; `vars.x` and bare `x` agree); `test_resolve_inputs_coercion` (`int "7"` → 7, `float "1.5"`, bool `"Yes"` → True, `"maybe"` raises); `test_missing_required_input` (`InputError` matches `missing required input 'month'`); `test_unknown_input` (matches `unknown input 'bogus' (declared: month)`); `test_default_template_rendered` (`default: "{{ today | prev_month | fmt('%Y-%m') }}"` with `today=date(2026,11,2)` → `"2026-10"`); `test_call_style_native_values` (an int accepted for `string`); `test_parse_input_pairs` (`"a=b=c"` → `{"a":"b=c"}`; `"novalue"` raises).
  - `test_flow.py` (via `run_bot`): `test_set_keeps_native_and_text` (`set: {n: "{{ inputs.k }}", rows: [...]}`... assert via a following `assert`-free route: use `log` with `"{{ n }}"` and read `log.jsonl`); `test_expression_error_names_step_expression_and_field`: step `{"id":"f1","log":{"message":"{{ nope }}"}}` fails, exit 1, record error contains `f1`... (via `StepError` text) `log.message`, and `'nope' is undefined`, with attempts == 1 even with `retry: {times: 3}`; `test_secret_expression_fails_step_with_m3_message`; `test_log_step_writes_event_and_echoes` (`echo` collects the message; `log.jsonl` has `{"event":"log","message":"hello 5"}` with `step_id`); `test_pause_headless_skipped` (log record message `pause skipped (headless)`, step `ok`); `test_vars_section_and_inputs_in_templates`.
  - CLI (`tests/e2e/test_demo_login.py`): `test_run_missing_input_exits_2_without_traceback` (bot with `inputs: {month: {type: string}}` and no `--input` → exit 2, output contains `missing required input 'month'`, no `Traceback`, and no `runs/` directory created); `test_run_input_flag_is_repeatable_and_typed`.

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/unit/test_inputs.py tests/browser/test_flow.py --no-cov -q`. Expected: FAIL.

- [ ] **Step 3: Implement `inputs.py`, the render hook in `run_step`, the three handlers and the `run_workflow` / CLI parameters.** `run_workflow` order: resolve inputs (before any browser, so an error leaves no run dir: build `RunArtifacts` after resolving), init vars, launch.

- [ ] **Step 4: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check`. Expected: PASS.

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(runner): execution-time templating, inputs, vars, set/log/pause, --input"
```

### Task 5: Workspace confinement and control flow (`if`, `for_each`, `call`)

**Files:**
- Create: `src/rpawright/runner/workspace.py`, `tests/unit/test_workspace.py`
- Modify: `src/rpawright/runner/steps_flow.py`, `src/rpawright/runner/context.py`, `src/rpawright/runner/engine.py`, `src/rpawright/cli.py`, `tests/browser/test_flow.py`

**Interfaces:**
- Consumes: `RunContext.run_block`, `Scope`, `resolve_inputs`, `load_workflow`, `init_vars` (Tasks 3, 4).
- Produces:
  - `Workspace(root: Path)` with `.root: Path` (resolved) and `.resolve(step_id: str, raw: str) -> Path`: relative paths join the root; the candidate is `Path.resolve()`d (symlinks followed); it must satisfy `is_relative_to(root)`, else `StepError(step_id, f"path {raw!r} is outside the workspace {root}")`. Never creates anything.
  - `RunContext.workspace: Workspace`, `RunContext.call_stack: tuple[Path, ...]`.
  - `run_workflow(..., workspace: Path | None = None, bot_path: Path | None = None)`: workspace defaults to `Path.cwd()`; `bot_path` (resolved) seeds `call_stack`.
  - Handlers `if`, `for_each`, `call` added to `FLOW_HANDLERS`:
    - `if`: condition (rendered natively; a bool or any value) → truthiness; runs `run.run_block(step.then, ctx.path + ".then")` or `".else"` for `else_`.
    - `for_each`: `items = step.for_each.in_` (rendered natively); must be a `list` or `tuple`, else `StepError("for_each 'in' must be a list, got <type>")`; for item `i`: set `run.scope.loop[as_] = item`, `run.run_block(steps, f"{ctx.path}[{i}]")`, and in a `finally` restore the previous loop value (or delete the key). An empty list runs zero iterations.
    - `call`: path = `run.workspace.resolve(...)` of `bot`, additionally required to be inside `<root>/bots/` (message names `bots/`); depth/cycle checks per R12; `load_workflow(path)` (a `WorkflowError` → `StepError` with its message); `resolve_inputs(callee, step.call.inputs, ...)`; swap `run.scope` for a fresh `Scope` with the callee's inputs and `init_vars`, push `path` on `call_stack`, `run.run_block(callee.steps, ctx.path)`, and restore scope and stack in a `finally`.
  - CLI `run --workspace PATH` (default cwd); a non-directory exits 2 with `error  workspace ... is not a directory`; `bot_path=bot`.

- [ ] **Step 1: Write the failing tests.**
  - `test_workspace.py`: `test_relative_and_absolute_inside_allowed` (both return paths under root); `test_dotdot_escape_rejected` (`../x`, `a/../../x`); `test_absolute_outside_rejected` (`str(tmp_path.parent / "x")`); `test_workspace_symlink_escape_rejected`: create `tmp_path/ws/link -> tmp_path/outside` with `os.symlink`, skip via `pytest.skip` on `OSError`/`NotImplementedError` (Windows without privilege); `resolve("s", "link/secret.txt")` raises `StepError` matching `outside the workspace`; `test_symlink_pointing_inside_allowed`.
  - `test_flow.py` (via `run_bot`, `goto` the `late.html`-free `login.html` where a page is needed, otherwise `set`/`log` only): `test_if_then_else_branches` (log message proves the branch; the untaken branch's `log` absent); `test_if_literal_bool_and_falsey_native` (`"{{ [] }}"` is false); `test_for_each_iterates_list_with_loop_variable`; `test_for_each_empty_list_runs_zero_iterations` (a following `log` still runs, result `ok`, exit 0); `test_for_each_non_list_fails_clearly`; `test_loop_variable_does_not_leak_after_loop` (log of `{{ inv }}` after the loop fails with `'inv' is undefined`); `test_log_records_carry_nested_path`: `[set, for_each{id: loop, in: [a,b], steps:[log{id: inner}]}]` → paths `loop[0]/inner`, `loop[1]/inner`, `loop`; `test_failed_step_is_innermost_and_parent_names_it`: inner `click` of a missing target inside `for_each` → `RunResult.failed_step == inner id`, the `for_each` record error contains `nested step`, exactly one `fail-*.png` named from the path; `test_inner_on_error_continue_keeps_loop_going`; `test_retry_on_for_each_reruns_whole_block`; `test_call_runs_callee_with_isolated_vars_and_explicit_inputs` (callee sets `x`; caller cannot read `x` afterwards; callee cannot read the caller's vars; callee `inputs:` validated: unknown input → step fails); `test_call_outside_bots_dir_rejected` (`bot: other/x.yaml` and `bot: ../x.yaml`); `test_call_symlink_escape_rejected` (skip on `OSError`); `test_call_cycle_detected` (a.yaml → b.yaml → a.yaml, error names the chain, exit 1); `test_call_depth_limit` (chain of 7 files fails with `depth`); `test_call_same_bot_twice_is_not_a_cycle`; `test_call_failure_propagates_to_caller_step`; `test_call_shares_page` (callee `goto`, caller `assert`s on the same page).

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/unit/test_workspace.py tests/browser/test_flow.py --no-cov -q`. Expected: FAIL.

- [ ] **Step 3: Implement `workspace.py`, the three handlers, and the engine/CLI parameters.**

- [ ] **Step 4: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check`. Expected: PASS.

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(runner): workspace confinement and if/for_each/call control flow"
```

### Task 6: Page steps (`select`, `hover`, `extract_text`, `extract_table`, `upload`, `screenshot`, `download`)

**Files:**
- Create: `src/rpawright/runner/steps_page.py`, `tests/browser/test_page_steps.py`, fixtures `tests/fixtures/site/form.html`, `tests/fixtures/site/table.html`, `tests/fixtures/site/downloads.html`, `tests/fixtures/site/files/hello.txt`
- Modify: `src/rpawright/runner/steps.py` (merge `PAGE_HANDLERS`)

**Interfaces:**
- Consumes: `StepContext.require_run()`, `Workspace.resolve`, `resolve_target` / `_resolve` in `steps.py`, `poll_until`, `RunContext.downloads` (Tasks 3, 5).
- Produces: `PAGE_HANDLERS: dict[str, Callable[[StepContext, Step], None]]`; pure helper `table_to_rows(header: list[str], rows: list[list[str]]) -> list[dict[str, str]]` (R17 padding and header naming) so the naming rules are unit-testable.
  - `select`: `locator.select_option(value=...)` or `label=...`; `hover`: `locator.hover`; `extract_text`: `inner_text` stripped into `run.scope.vars[into]`; `upload`: `locator.set_input_files(workspace.resolve(file))` (must exist: `StepError` if not).
  - `extract_table`: resolve the target, then `locator.evaluate(JS)` returning `{header: string[], rows: string[][]}`; non-table → `StepError("extract_table: target is not a <table>")`. The JS (the only non-obvious part):

```js
(t) => {
  if (t.tagName !== "TABLE") return null;
  const text = (c) => c.textContent.replace(/\s+/g, " ").trim();
  const rows = [...t.rows].filter((r) => r.cells.length).map((r) => [...r.cells].map(text));
  return { header: rows.length ? rows[0] : [], rows: rows.slice(1) };
}
```
    Python then builds the dicts with `table_to_rows`.
  - `screenshot`: `path` resolved in the workspace, parent dirs created; default `run.artifacts.dir / f"shot-{safe_name(ctx.path)}.png"`; `full_page` honored; target-less.
  - `download`: `poll_until(page, lambda: queue.get_nowait() or None, ...)` with `queue.Empty` → `None`; on timeout `StepError("download: no download started within N ms")`; `download.failure()` non-None → `StepError`; save with `save_as(workspace.resolve(to))` after creating the parent dir.

- [ ] **Step 1: Write the fixtures.**
  - `form.html`: `<select id="color" aria-label="Color">` options `red`/`green` (labels "Red", "Green"); a `<button id="hov">Hover me</button>` whose mouseover sets `document.title="hovered"` and shows `<span id="out">hovered</span>`; `<input type="file" id="up" aria-label="Upload">` with a change handler writing the first file name to `<span id="fname">`; `<p id="msg">  Hello   world </p>`.
  - `table.html`: three tables: `#t1` with `<thead><tr><th>Month</th><th>Number</th></tr></thead>` and two body rows; `#t2` with no `<th>` (first row `td` cells become header); `#t3` with an empty header cell, a duplicate header (`A`,`A`) and a short row; plus `<div id="notatable">`.
  - `downloads.html`: `<a id="dl" href="files/hello.txt" download>Get file</a>` and `<a id="nodl" href="#">No download</a>`. `files/hello.txt` contains `hello`.

- [ ] **Step 2: Write the failing tests** in `test_page_steps.py` (via `run_bot` and `site_url`, plus a `Workspace` rooted at `tmp_path`).
  - `test_table_to_rows_names_and_padding` (unit-style): blank header → `col2`, duplicates → `A`, `A_2`, short row padded with `""`.
  - `test_select_by_value_and_label`, `test_hover_triggers_handler`, `test_extract_text_collapses_whitespace_into_var` (`into: msg`, then `log "{{ msg }}"` equals `Hello world`).
  - `test_extract_table_uses_th_header` (`#t1` → `[{"Month": "2026-10", "Number": "INV-1"}, ...]`); `test_extract_table_without_th_uses_first_row`; `test_extract_table_non_table_fails_clearly` (`#notatable`, message `not a <table>`).
  - `test_upload_sets_file_and_missing_file_fails` (file `tmp_path/"up.txt"` is shown in `#fname`; a missing file is a `StepError`); `test_upload_outside_workspace_rejected`.
  - `test_screenshot_default_in_run_dir_and_custom_path` (default file exists under `result.run_dir`; `path: shots/a.png` exists under `tmp_path`; `path: ../a.png` fails with `outside the workspace`).
  - `test_download_click_then_download_saves_file` (`click #dl`, then `download: {to: "out/{{ name }}.txt"}` after `set name`; file content `hello`; parent directory created).
  - `test_download_never_arrives_fails_within_timeout` (`click #nodl`, `download` with `timeout_ms: 500`): exit 1, message `no download started within 500 ms`, elapsed `< 5 s`, `fail-*.png` present.
  - `test_download_path_escape_rejected` (`to: ../x.txt`, no file created outside).
  - Locator tests with `xpath`/`nth`/`exact` for these new steps are covered in Task 3; here add one `select` step using `{"xpath": "//select"}` as the target.

- [ ] **Step 3: Run the tests and see them fail.** Run `uv run pytest tests/browser/test_page_steps.py --no-cov -q`. Expected: FAIL.

- [ ] **Step 4: Implement `steps_page.py` and merge `PAGE_HANDLERS` into `HANDLERS`.**

- [ ] **Step 5: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check`. Expected: PASS.

- [ ] **Step 6: Commit.**
```bash
git add -A && git commit -m "feat(runner): select, hover, extract, upload, screenshot and download steps"
```

### Task 7: CSV and XLSX steps

**Files:**
- Create: `src/rpawright/runner/steps_data.py`, `tests/browser/test_data_steps.py` (uses `run_bot`; a page is required by the engine, nothing is navigated)
- Modify: `src/rpawright/runner/steps.py` (merge `DATA_HANDLERS`)

**Interfaces:**
- Consumes: `Workspace.resolve`, `StepContext.require_run()` (Tasks 3, 5).
- Produces: `DATA_HANDLERS` with `read_csv`, `write_csv`, `read_xlsx`, `write_xlsx` (R18). Pure helpers (unit-testable without a browser): `read_csv_rows(path: Path) -> list[dict[str, str]]`, `write_csv_rows(path: Path, rows: list[dict[str, object]]) -> None`, `read_xlsx_rows(path: Path, sheet: str | None) -> list[dict[str, object]]`, `write_xlsx_rows(path: Path, rows: list[dict[str, object]], sheet: str | None) -> None`.
  - Handlers validate `rows` at run time: not a list of mappings → `StepError("write_csv: rows must be a list of mappings, got <type>")`. Parent directories are created after the workspace check. `openpyxl` is imported inside the XLSX functions. Unknown `sheet` → `StepError` listing the available sheets. `read_*` of a missing file → `StepError` naming the path.

- [ ] **Step 1: Write the failing tests.**
  - `test_csv_roundtrip_unicode_commas_quotes_newlines`: rows `[{"Name": "Zoë, \"Z\"", "Note": "line1\nline2", "City": "東京"}, {"Name": "plain", "Note": "", "City": "x,y"}]` → `write_csv_rows` then `read_csv_rows` equals the input; also `csv.reader(path.open(newline="", encoding="utf-8"))` yields 3 records and the bytes contain no `\r`.
  - `test_write_csv_header_is_union_of_keys_in_first_seen_order`; `test_write_csv_empty_rows_writes_empty_file`; `test_read_csv_strips_bom_and_returns_text_values` (file written with `utf-8-sig`, value `"007"` stays `"007"`).
  - `test_xlsx_roundtrip` (str, int, float, empty → `""`, `datetime` → ISO string); `test_xlsx_sheet_selection_and_missing_sheet_message`; `test_read_xlsx_skips_empty_rows`.
  - Via `run_bot`: `test_read_csv_into_var_feeds_for_each` (`read_csv` then `for_each` logging each row's field); `test_write_csv_rows_from_extract_style_var` (`set: {rows: [...]}` then `write_csv: {path: "out/{{ inputs.m }}.csv", rows: "{{ rows }}"}` → file under `tmp_path/out/`); `test_write_csv_rows_not_a_list_fails_clearly`; `test_data_paths_confined` (`../x.csv` for read and write → `outside the workspace`, nothing written); `test_symlink_escape_for_csv_rejected` (skip on `OSError`).

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/browser/test_data_steps.py --no-cov -q`. Expected: FAIL.

- [ ] **Step 3: Implement `steps_data.py`.** `csv.DictReader` / `csv.writer(lineterminator="\n")`, files opened with `newline=""` and `encoding="utf-8"` (`utf-8-sig` on read); `openpyxl.load_workbook(read_only=True, data_only=True)` for reads.

- [ ] **Step 4: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check`. Expected: PASS (mypy uses `types-openpyxl`).

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(runner): read/write CSV and XLSX steps"
```

### Task 8: `http` step with `allow_domains` guard

**Files:**
- Create: `src/rpawright/runner/net.py`, `src/rpawright/runner/steps_http.py`, `tests/unit/test_net.py`, `tests/browser/test_http_step.py`
- Modify: `src/rpawright/runner/steps.py` (merge `HTTP_HANDLERS`), `src/rpawright/runner/context.py`, `src/rpawright/runner/engine.py`

**Interfaces:**
- Consumes: `RunContext.policy` (`allow_domains`), `HttpBody` (Task 2).
- Produces:
  - `host_allowed(host: str, allow_domains: list[str]) -> bool` (R14: exact lower-case match or `*.suffix`; ports are not part of the host).
  - `make_client(allow_domains: list[str], *, step_id: str, timeout_ms: int, transport: httpx.BaseTransport | None) -> httpx.Client`: `follow_redirects=True`, `max_redirects=5`, and a `request` event hook that raises `StepError(step_id, f"http: host {host!r} is not in policy.allow_domains")` before every hop, so a redirect target is never contacted.
  - `RunContext.http_transport: httpx.BaseTransport | None`; `run_workflow(..., http_transport: httpx.BaseTransport | None = None)`.
  - `HTTP_HANDLERS = {"http": ...}`: sends `method`, `url`, `headers`, `params`, and `json` or `body` (as content); status check (R14) raises `StepError(f"http: expected status {expected}, got {status}")`; `httpx.HTTPError` → `StepError`; stores `{status, headers, json|text}` in `run.scope.vars[into]` when `into` is set.

- [ ] **Step 1: Write the failing tests.**
  - `test_net.py`: `test_host_allowed_exact_case_insensitive_and_wildcard` (`Portal.Vendor.com` vs `portal.vendor.com` ok; `*.vendor.com` allows `a.vendor.com`, not `vendor.com`, not `evilvendor.com`); `test_empty_allow_list_denies_everything`.
  - `test_http_step.py` (via `run_bot(..., http_transport=httpx.MockTransport(handler))`, with `policy.allow_domains: ["api.test"]`): `test_get_json_into_var` (handler returns `{"id": 7}`; a following `log "{{ resp.json.id }}"` logs `7`, `resp.status == 200`); `test_post_json_body_and_params_templated` (handler asserts method, `?page=2`, header, JSON `{"n": 5}` rendered natively from `"{{ n }}"`); `test_text_response_when_not_json`; `test_non_2xx_fails_by_default_and_expect_status_overrides` (404 fails; `expect_status: [200, 404]` passes; `expect_status: 201` fails on 200); `test_host_not_in_allow_domains_fails_before_request` (handler records calls: empty); `test_redirect_to_disallowed_host_is_blocked`: first request `https://api.test/a` → `302 Location: https://evil.example/steal`; step fails, message contains `evil.example`, and the handler saw only the first request; `test_redirect_within_allowed_host_followed`; `test_transport_error_becomes_step_error` (handler raises `httpx.ConnectError`); `test_retry_applies_to_http` (first 500 then 200 with `retry: {times: 1, delay_ms: 0}` → `attempts == 2`).

- [ ] **Step 2: Run the tests and see them fail.** Run `uv run pytest tests/unit/test_net.py tests/browser/test_http_step.py --no-cov -q`. Expected: FAIL.

- [ ] **Step 3: Implement `net.py`, `steps_http.py` and the engine parameter.**

- [ ] **Step 4: Run everything.** Run `uv run pytest -q && uv run mypy && uv run ruff check`. Expected: PASS.

- [ ] **Step 5: Commit.**
```bash
git add -A && git commit -m "feat(runner): http step with allow_domains guard on every redirect hop"
```

### Task 9: The invoice example and end-to-end test (exit criterion)

**Files:**
- Create: `examples/bots/invoices.yaml`, `tests/fixtures/site/invoices.html`, `tests/fixtures/site/invoice_files/INV-0901.pdf`, `INV-0902.pdf`, `INV-1001.pdf`, `INV-1002.pdf`, `INV-1003.pdf`, `tests/e2e/test_invoices.py`
- Modify: none in `src/` (if the e2e finds a bug, fix it in the owning module with a regression test there, not here).

**Interfaces:**
- Consumes: everything above, through the CLI only.
- Produces: the fixture page and bot described below.

- [ ] **Step 1: Write the fixtures.**
  - `invoices.html` (no login): `<table class="invoices">` with `<th>` header `Month | Number | Amount` and five rows: `2026-09 INV-0901 90.00`, `2026-09 INV-0902 45.50`, `2026-10 INV-1001 120.00`, `2026-10 INV-1002 75.25`, `2026-10 INV-1003 310.00`. In each row the Number cell is `<a href="invoice_files/INV-1001.pdf" download>INV-1001</a>`.
  - Each `invoice_files/*.pdf` is a tiny stub: `%PDF-1.4\n% stub invoice <number>\n%%EOF\n` (ASCII, a few dozen bytes).

- [ ] **Step 2: Write `examples/bots/invoices.yaml`** modeled on spec §6.1 without login: `inputs` `base_url` (string, default `http://127.0.0.1:8765`) and `month` (string, default `"{{ today | prev_month | fmt('%Y-%m') }}"`); `policy.timeout_ms: 5000`; steps: `goto "{{ inputs.base_url }}/invoices.html"`; `extract_table` of `table.invoices` into `rows`; `set: {wanted: "{{ rows | where('Month', inputs.month) }}"}`; `if: "{{ wanted | length == 0 }}"` with `then: [log "no invoices for {{ inputs.month }}"]`; `for_each` over `{{ wanted }}` as `inv` with `click` of `{role: link, name: "{{ inv.Number }}", exact: true}` and `download: {to: "downloads/{{ inv.Number }}.pdf"}`, `on_error: continue` on the `for_each`'s inner `click` and `download` per R9; `write_csv: {path: "out/{{ inputs.month }}.csv", rows: "{{ wanted }}"}`. Header comment: serve with `uv run python -m http.server 8765 --directory tests/fixtures/site`.

- [ ] **Step 3: Write the failing e2e tests** in `tests/e2e/test_invoices.py` (CLI via `CliRunner`; `EXAMPLE` anchored on `__file__`; args `run <bot> --workspace <tmp> --runs-dir <tmp>/runs --input base_url=<site_url> --input month=...`; the module must not use the `page` fixture).
  - `test_invoice_example_validates`.
  - `test_invoices_run_end_to_end`: `month=2026-10` → exit 0; `out/2026-10.csv` bytes equal `"Month,Number,Amount\n2026-10,INV-1001,120.00\n2026-10,INV-1002,75.25\n2026-10,INV-1003,310.00\n"`; the three `downloads/INV-100x.pdf` exist, start with `%PDF` and contain their own number; `downloads/INV-0901.pdf` does not exist; `log.jsonl` records for the loop have paths like `for_each-<n>[2]/click-<m>` and `for_each-<n>[2]/download-<k>`, and step statuses are all `ok`.
  - `test_invoices_month_with_no_rows_is_a_clean_noop`: `month=2026-01` → exit 0, the `log` event `no invoices for 2026-01` present, no downloads, the CSV exists and is empty.
  - `test_invoices_default_month_expression_used`: no `--input month` → exit 0 and the CSV path is `out/<prev month of today>.csv` (compute with `datetime.date.today()` in the test).
  - `test_invoices_bad_input_type_exits_2` (`--input base_url` without `=` → exit 2).

- [ ] **Step 4: Run the tests and see them fail, then fix.** Run `uv run pytest tests/e2e/test_invoices.py --no-cov -q`. Expected: FAIL until the fixtures and bot exist; once they exist all must PASS. Any engine defect found here gets a regression test in its own module.

- [ ] **Step 5: Run everything three times** to catch flakiness (`for i in 1 2 3; do uv run pytest -q; done`). Expected: PASS each time.

- [ ] **Step 6: Commit.**
```bash
git add -A && git commit -m "test(e2e): invoice example runs end to end against the fixture site"
```

### Task 10: Docs, schema, README, final gates

**Files:**
- Create: `docs/yaml-reference.md`, `tests/unit/test_handlers_complete.py`
- Modify: `README.md`, `schema/workflow.schema.json`, `examples/bots/demo-login.yaml` (comment fix only if needed)

**Interfaces:**
- Consumes: `HANDLERS`, `ACTION_NAMES`.
- Produces: nothing new in code.

- [ ] **Step 1: Write the failing test** `test_handlers_complete.py`: `test_every_step_type_has_exactly_one_handler`: `set(HANDLERS) == set(ACTION_NAMES.values())` and `len(ACTION_NAMES) == 24`; `test_yaml_reference_lists_every_step`: every action name appears as a `### <name>` heading in `docs/yaml-reference.md` (path anchored on `__file__`); `test_example_bots_validate` runs `load_workflow` on every `examples/bots/*.yaml`.

- [ ] **Step 2: Run it and see it fail.** Run `uv run pytest tests/unit/test_handlers_complete.py --no-cov -q`. Expected: FAIL (no reference yet).

- [ ] **Step 3: Write `docs/yaml-reference.md`.** Short: workflow header (`inputs`, `vars`, `policy`), common step fields (`id`, `retry`, `on_error` including step lists, `timeout_ms`), the targets block, then one `### <step>` heading per step (all 24) with a 3-6 line YAML example; sections for expressions (namespaces, whole-expression rule, filters, `secret`/`asset` M3 note, `env` prefix), paths and the workspace, and `http`'s `allow_domains` rule. Link it from the README.

- [ ] **Step 4: Update `README.md`.** Mark the Running features that now exist `(available)` (steps, variables/expressions/control flow, retry and on_error, `pause:` for headed runs); keep security items planned; add a quick-start section for the invoice example (serve the fixture site, `uv run rpawright run examples/bots/invoices.yaml --input month=2026-10`), the new flags `--input` and `--workspace`, and the link to `docs/yaml-reference.md`; keep the §6.1 example's "does not run yet" note (it uses `secret`). Set the roadmap row M2 to `complete (in review)` and the status line to M1 and M2.

- [ ] **Step 5: Regenerate the schema and run every gate.** Run `uv run rpawright schema --out schema/workflow.schema.json && git diff --stat schema/`, then `uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest -q`. Expected: clean, all tests PASS, coverage >= 85%. Confirm `uv sync --locked` succeeds.

- [ ] **Step 6: Commit.**
```bash
git add -A && git commit -m "docs: YAML step reference, README feature marks and M2 roadmap status"
```

---

## Self-review (run 2026-11-02, before commit)

- **Spec coverage:** §6.2 common fields (`retry`, `on_error` list: Tasks 2, 3; `if:`/`pause:` common fields: R1), §6.3 targets (unchanged), §6.4 all 24 step types (Task 10 test pins the count), §6.5 expressions (Tasks 1, 4), §6.6 expression-syntax validation (Task 2), §8 exit codes and artifacts (Tasks 3, 5; unchanged codes), §10 path confinement, `call` confined to `bots/`, `http` limited to `allow_domains`, sandboxed Jinja (Tasks 1, 5, 7, 8; navigation allowlist and vault stay M3), §12 M2 exit criterion (Task 9). M1 ledger items: xpath/nth/exact tests and poll helper and clamp (Task 3), injected browser (Task 3, R21), `frame` on `WaitBody` already done in M1 (R8 there).
- **Step scan:** every code step names file and signature; bodies appear only for the whole-expression rule and the table JS.
- **Type consistency:** `StepContext.require_run()`, `RunContext.run_block`, `Workspace.resolve(step_id, raw)`, `poll_until`, `table_to_rows`, `host_allowed`, `make_client`, `ACTION_NAMES`, `child_blocks` and `iter_steps` are each defined in exactly one task and used with the same names later.
- **Review Focus:** line 1 pinned by `test_workspace_symlink_escape_rejected`, `test_data_paths_confined`, `test_download_path_escape_rejected`; line 2 by `test_redirect_to_disallowed_host_is_blocked`; line 3 by `test_download_never_arrives_fails_within_timeout`; line 4 by `test_csv_roundtrip_unicode_commas_quotes_newlines`; line 5 by `test_for_each_empty_list_runs_zero_iterations`, `test_log_records_carry_nested_path`, `test_expression_error_names_step_expression_and_field`, `test_nested_error_names_full_path`.
- **Proportion:** kept to signatures, test names with exact values and one-line approaches.
