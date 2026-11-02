"""Run a validated Workflow in Chromium with retries, on_error, a JSONL log and screenshots."""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from rpawright.runner.artifacts import RunArtifacts
from rpawright.runner.errors import StepError
from rpawright.runner.steps import HANDLERS, StepContext
from rpawright.workflow.models import Step, Workflow, action_name


@dataclass
class StepRecord:
    step_id: str
    action: str
    status: Literal["ok", "failed", "continued"]
    attempts: int
    duration_ms: int
    locator_used: str | None
    error: str | None


@dataclass
class RunResult:
    status: Literal["ok", "failed"]
    exit_code: int
    failed_step: str | None
    run_dir: Path
    steps: list[StepRecord] = field(default_factory=list)


def _attempt_step(
    page: Page, step: Step, step_id: str, timeout_ms: int
) -> tuple[int, str | None, str | None]:
    """Run one step with retries. Returns (attempts, locator_used, error or None)."""
    action = action_name(step)
    retry_times = step.retry.times if step.retry else 0
    delay_s = (step.retry.delay_ms if step.retry else 0) / 1000
    attempts = 0
    locator_used: str | None = None
    error: str | None = None
    for n in range(1 + retry_times):
        attempts = n + 1
        ctx = StepContext(page=page, timeout_ms=timeout_ms, step_id=step_id)
        try:
            HANDLERS[action](ctx, step)
            return attempts, ctx.locator_used, None
        except StepError as e:
            error = e.message
        except PlaywrightError as e:
            error = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        locator_used = ctx.locator_used
        if n < retry_times:
            time.sleep(delay_s)
    if page.is_closed():
        error = "page closed"
    return attempts, locator_used, error


def run_workflow(
    wf: Workflow,
    *,
    runs_root: Path,
    headed: bool = False,
    step_mode: bool = False,
    trace: bool = False,
    confirm: Callable[[str], object] = input,
) -> RunResult:
    artifacts = RunArtifacts(runs_root, wf.name)
    records: list[StepRecord] = []
    failed_step: str | None = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=wf.policy.headless and not headed)
        try:
            context = browser.new_context()
            if trace:
                context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            try:
                for step in wf.steps:
                    assert step.id is not None
                    step_id = step.id
                    if step_mode:
                        confirm(step_id)
                    timeout_ms = step.timeout_ms or wf.policy.timeout_ms
                    started = time.monotonic()
                    attempts, locator_used, error = _attempt_step(page, step, step_id, timeout_ms)
                    duration_ms = int((time.monotonic() - started) * 1000)
                    status: Literal["ok", "failed", "continued"] = "ok"
                    if error is not None:
                        status = "continued" if step.on_error == "continue" else "failed"
                        try:
                            artifacts.screenshot(page, step_id)
                        except Exception as e:  # screenshot must never crash the run
                            error += f" (screenshot failed: {e})"
                    record = StepRecord(
                        step_id=step_id,
                        action=action_name(step),
                        status=status,
                        attempts=attempts,
                        duration_ms=duration_ms,
                        locator_used=locator_used,
                        error=error,
                    )
                    records.append(record)
                    artifacts.log(dict(asdict(record)))
                    if status == "failed":
                        failed_step = step_id
                        break
            finally:
                if trace:
                    try:
                        context.tracing.stop(path=str(artifacts.dir / "trace.zip"))
                    except PlaywrightError:
                        pass
        finally:
            browser.close()
    ok = failed_step is None
    return RunResult(
        status="ok" if ok else "failed",
        exit_code=0 if ok else 1,
        failed_step=failed_step,
        run_dir=artifacts.dir,
        steps=records,
    )
