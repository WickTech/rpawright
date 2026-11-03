"""Flow-control and bookkeeping handlers: set, log, pause."""

from collections.abc import Callable

from rpawright.runner.context import StepContext
from rpawright.workflow.models import LogStep, PauseStep, SetStep, Step


def _emit(ctx: StepContext, message: str) -> None:
    run = ctx.require_run()
    run.artifacts.log(
        {"event": "log", "step_id": ctx.step_id, "path": ctx.path, "message": message}
    )
    run.echo(message)


def run_set(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, SetStep)
    ctx.require_run().scope.vars.update(step.set)


def run_log(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, LogStep)
    _emit(ctx, step.log.message)


def run_pause(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, PauseStep)
    run = ctx.require_run()
    if run.headed:
        ctx.page.pause()
    else:
        _emit(ctx, "pause skipped (headless)")


FLOW_HANDLERS: dict[str, Callable[[StepContext, Step], None]] = {
    "set": run_set,
    "log": run_log,
    "pause": run_pause,
}
