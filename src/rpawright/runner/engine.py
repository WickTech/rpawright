"""Run a validated Workflow in Chromium with retries, on_error, a JSONL log and screenshots."""

import queue
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from playwright.sync_api import Browser, BrowserContext, Download, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from rpawright.runner.artifacts import RunArtifacts
from rpawright.runner.context import RunContext, Scope, StepRecord
from rpawright.runner.errors import NestedFailure
from rpawright.runner.executor import run_attempts, run_steps
from rpawright.workflow.models import Workflow

__all__ = ["RunResult", "StepRecord", "run_workflow"]


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
) -> RunResult:
    """Run ``wf``. An injected ``browser`` is left open; the context created here is closed."""
    artifacts = RunArtifacts(runs_root, wf.name)
    records: list[StepRecord] = []
    failed = False
    with ExitStack() as stack:
        if browser is None:
            pw = stack.enter_context(sync_playwright())
            owned = pw.chromium.launch(headless=wf.policy.headless and not headed)
            stack.callback(owned.close)
            browser = owned
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
            scope=Scope(),
            headed=headed,
            step_mode=step_mode,
            confirm=confirm,
            echo=echo,
            records=records,
            downloads=downloads,
            workspace=workspace,
        )
        run.run_block = lambda steps, path: run_steps(run, steps, path)
        run.run_attempts = lambda steps, path, owner: run_attempts(run, steps, path, owner)
        try:
            run_steps(run, wf.steps)
        except NestedFailure:
            failed = True
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
    failed_record = next((r for r in records if r.status == "failed"), None) if failed else None
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
