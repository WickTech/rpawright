"""Recursive step executor: retries, ``on_error`` and one log record per step."""

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

from playwright.sync_api import Error as PlaywrightError

from rpawright.runner.context import Outcome, RunContext, Status, StepContext, StepRecord
from rpawright.runner.errors import NestedFailure, PolicyViolation, StepError
from rpawright.runner.handlers import HANDLERS
from rpawright.workflow.models import Step, StepCommon, action_name

__all__ = ["NestedFailure", "run_attempts", "run_step", "run_steps"]


@dataclass
class _Attempts:
    count: int
    locator_used: str | None
    error: str | None  # None means success
    outcome: Outcome = "ok"
    policy: bool = False
    nested: bool = False
    per_iteration: bool = False


def _first_line(e: Exception) -> str:
    text = str(e).strip()
    return text.splitlines()[0] if text else type(e).__name__


def _attempt(
    run: RunContext,
    owner: StepCommon,
    step_id: str,
    path: str,
    timeout_ms: int,
    work: Callable[[StepContext], None],
) -> _Attempts:
    """Run ``work`` up to ``1 + retry.times`` times; never raises for step failures."""
    retry_times = owner.retry.times if owner.retry else 0
    delay_s = (owner.retry.delay_ms if owner.retry else 0) / 1000
    count = 0
    locator_used: str | None = None
    error = ""
    policy = nested = per_iteration = False
    for n in range(1 + retry_times):
        count = n + 1
        ctx = StepContext(page=run.page, timeout_ms=timeout_ms, step_id=step_id, run=run, path=path)
        policy = nested = False
        try:
            work(ctx)
            return _Attempts(count, ctx.locator_used, None, outcome=ctx.outcome)
        except PolicyViolation as e:
            error, policy = e.message, True
        except NestedFailure as e:
            error, policy, nested = e.message, e.policy, True
        except StepError as e:
            error = e.message
        except PlaywrightError as e:
            error = _first_line(e)
        except Exception as e:  # safety net: a handler bug must not crash the run
            error = f"{type(e).__name__}: {e}"
        locator_used = ctx.locator_used
        per_iteration = ctx.per_iteration
        if policy or per_iteration or n >= retry_times:
            break
        time.sleep(delay_s)
    if not nested and not policy and run.page.is_closed():
        error = "page closed"
    return _Attempts(
        count, locator_used, error, policy=policy, nested=nested, per_iteration=per_iteration
    )


def _recover(
    run: RunContext, owner: StepCommon, path: str, step_id: str, res: _Attempts
) -> tuple[Status, str, bool]:
    """Apply ``on_error`` to a failed attempt run. Returns (status, error text, policy)."""
    assert res.error is not None
    error = res.error
    if res.policy or res.per_iteration:
        status: Status = "failed"
    elif owner.on_error == "continue":
        status = "continued"
    elif isinstance(owner.on_error, list):
        status = "handled"
    else:
        status = "failed"
    # A nested failure already left a screenshot at the innermost step (R10).
    if not res.nested and not res.per_iteration:
        try:
            run.artifacts.screenshot(run.page, path)
        except Exception as e:  # screenshot must never crash the run
            error += f" (screenshot failed: {e})"
    if status == "handled":
        assert isinstance(owner.on_error, list)
        try:
            run_steps(run, owner.on_error, path + ".on_error")
        except NestedFailure as e:
            return "failed", f"{error}; on_error handler failed: {e.message}", e.policy
    return status, error, res.policy


def run_step(run: RunContext, step: Step, base_path: str) -> StepRecord:
    """Execute one step (confirm, retry, on_error), log and return its record."""
    assert step.id is not None
    step_id = step.id
    path = f"{base_path}/{step_id}" if base_path else step_id
    action = action_name(step)
    if run.step_mode:
        run.confirm(step_id)
    timeout_ms = step.timeout_ms if step.timeout_ms is not None else run.policy.timeout_ms
    started = time.monotonic()
    res = _attempt(run, step, step_id, path, timeout_ms, lambda ctx: HANDLERS[action](ctx, step))
    status: Status = res.outcome
    error = res.error
    policy = res.policy
    if res.error is not None:
        status, error, policy = _recover(run, step, path, step_id, res)
    record = StepRecord(
        step_id=step_id,
        action=action,
        status=status,
        attempts=res.count,
        duration_ms=int((time.monotonic() - started) * 1000),
        locator_used=res.locator_used,
        error=error,
        path=path,
        policy=policy,
    )
    run.records.append(record)
    entry = asdict(record)
    del entry["policy"]
    run.artifacts.log({"event": "step", **entry})
    return record


def run_steps(run: RunContext, steps: list[Step], base_path: str = "") -> None:
    """Run ``steps`` in order; the first failed step raises NestedFailure."""
    for step in steps:
        record = run_step(run, step, base_path)
        if record.status == "failed":
            raise NestedFailure(
                record.step_id,
                f"nested step {record.step_id} failed: {record.error}",
                policy=record.policy,
            )


def run_attempts(run: RunContext, steps: list[Step], path: str, owner: StepCommon) -> Outcome:
    """Run a block under ``owner``'s retry/on_error. Writes no record of its own.

    Returns ``ok``, ``continued`` or ``handled``; raises NestedFailure when the block ends up
    failed (``on_error: fail``, a failed handler, or a policy failure).
    """
    step_id = owner.id or ""
    timeout_ms = owner.timeout_ms if owner.timeout_ms is not None else run.policy.timeout_ms
    res = _attempt(run, owner, step_id, path, timeout_ms, lambda ctx: run_steps(run, steps, path))
    if res.error is None:
        return "ok"
    status, error, policy = _recover(run, owner, path, step_id, res)
    if status == "failed":
        raise NestedFailure(step_id, error, policy=policy)
    return "continued" if status == "continued" else "handled"
