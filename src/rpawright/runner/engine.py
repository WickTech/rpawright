"""Run a validated Workflow in Chromium with retries, on_error, a JSONL log and screenshots."""

import os
import queue
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from playwright.sync_api import Browser, BrowserContext, Download, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from rpawright.runner.artifacts import RunArtifacts
from rpawright.runner.context import RunContext, Scope, StepRecord
from rpawright.runner.errors import NestedFailure
from rpawright.runner.executor import run_attempts, run_steps
from rpawright.runner.inputs import build_namespace, init_vars, resolve_inputs
from rpawright.workflow.models import Workflow

__all__ = ["BrowserNotInstalledError", "RunResult", "StepRecord", "run_workflow"]


class BrowserNotInstalledError(Exception):
    """Playwright's Chromium build is missing; fix with ``playwright install chromium``."""


@dataclass
class RunResult:
    status: Literal["ok", "failed"]
    exit_code: int
    failed_step: str | None
    run_dir: Path
    steps: list[StepRecord] = field(default_factory=list)
    failed_path: str | None = None


def run_workflow(
    wf: Workflow,
    *,
    runs_root: Path,
    headed: bool = False,
    step_mode: bool = False,
    trace: bool = False,
    confirm: Callable[[str], object] = input,
    browser: Browser | None = None,
    workspace: Path | None = None,
    echo: Callable[[str], None] = print,
    inputs: Mapping[str, object] | None = None,
    env: Mapping[str, str] | None = None,
    today: date | None = None,
) -> RunResult:
    """Run ``wf``. An injected ``browser`` is left open; the context created here is closed.

    Raises ``InputError`` for bad inputs or vars and ``BrowserNotInstalledError`` if Chromium is
    missing; in both cases no run directory has been created.
    """
    env = os.environ if env is None else env
    today = today or date.today()
    scope = Scope(inputs=resolve_inputs(wf, inputs or {}, env=env, today=today))
    init_vars(wf, lambda: build_namespace(scope, env=env, today=today), scope)
    records: list[StepRecord] = []
    failed = False
    cause_path: str | None = None
    with ExitStack() as stack:
        if browser is None:
            pw = stack.enter_context(sync_playwright())
            try:
                owned = pw.chromium.launch(headless=wf.policy.headless and not headed)
            except PlaywrightError as e:
                if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
                    raise BrowserNotInstalledError(str(e)) from e
                raise
            stack.callback(owned.close)
            browser = owned
        artifacts = RunArtifacts(runs_root, wf.name)  # only after the browser is up
        context = browser.new_context(accept_downloads=True)
        stack.callback(_close_quietly, context)
        if trace:
            context.tracing.start(screenshots=True, snapshots=True)
        page = context.new_page()
        downloads: queue.Queue[Download] = queue.Queue()
        page.on("download", downloads.put)
        run = RunContext(
            page=page,
            artifacts=artifacts,
            policy=wf.policy,
            scope=scope,
            headed=headed,
            step_mode=step_mode,
            confirm=confirm,
            echo=echo,
            records=records,
            downloads=downloads,
            env=env,
            today=today,
            workspace=workspace,
        )
        run.run_block = lambda steps, path: run_steps(run, steps, path)
        run.run_attempts = lambda steps, path, owner: run_attempts(run, steps, path, owner)
        try:
            run_steps(run, wf.steps)
        except NestedFailure as e:
            failed = True
            cause_path = e.cause_path
        finally:
            if trace:
                try:
                    context.tracing.stop(path=str(artifacts.dir / "trace.zip"))
                except PlaywrightError as e:
                    first = str(e).strip().splitlines()
                    artifacts.log(
                        {"event": "trace_failed", "error": first[0] if first else repr(e)}
                    )
            while not downloads.empty():
                artifacts.log(
                    {"event": "unclaimed_download", "name": downloads.get().suggested_filename}
                )
    # The failure that ended the run, named explicitly by the NestedFailure chain (R10).
    failed_record = next((r for r in reversed(records) if r.path == cause_path), None)
    return RunResult(
        status="failed" if failed else "ok",
        exit_code=1 if failed else 0,
        failed_step=failed_record.step_id if failed_record else None,
        run_dir=artifacts.dir,
        steps=records,
        failed_path=failed_record.path if failed_record else None,
    )


def _close_quietly(context: BrowserContext) -> None:
    try:
        context.close()
    except PlaywrightError:
        pass  # the browser is already gone
