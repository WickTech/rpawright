"""Run-wide and per-step context shared by the executor and the step handlers."""

import queue
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from playwright.sync_api import Download, Page

from rpawright.runner.artifacts import RunArtifacts
from rpawright.runner.errors import StepError
from rpawright.runner.locate import Resolved, describe, resolve_target
from rpawright.workflow.models import Policy, Step, StepCommon, Target

Status = Literal["ok", "failed", "continued", "handled"]
Outcome = Literal["ok", "continued", "handled"]


@dataclass
class StepRecord:
    step_id: str
    action: str
    status: Status
    attempts: int
    duration_ms: int
    locator_used: str | None
    error: str | None
    path: str = ""
    # Set when the failure was a policy failure; kept out of log.jsonl.
    policy: bool = False
    # Path of the innermost failed record when this step failed because a nested block did;
    # None for a failure of the step's own. Not written to log.jsonl.
    cause_path: str | None = None


@dataclass
class Scope:
    inputs: dict[str, object] = field(default_factory=dict)
    vars: dict[str, object] = field(default_factory=dict)
    loop: dict[str, object] = field(default_factory=dict)


def _block_not_set(steps: list[Step], path: str) -> None:
    raise StepError("", "run_block is not available outside run_workflow")


def _attempts_not_set(steps: list[Step], path: str, owner: StepCommon) -> Outcome:
    raise StepError("", "run_attempts is not available outside run_workflow")


@dataclass
class RunContext:
    page: Page
    artifacts: RunArtifacts
    policy: Policy
    scope: Scope
    headed: bool
    step_mode: bool
    confirm: Callable[[str], object]
    echo: Callable[[str], None]
    records: list[StepRecord]
    downloads: "queue.Queue[Download]"
    env: Mapping[str, str]
    today: date
    workspace: Path | None = None
    # Set by run_workflow so handlers never import the executor module.
    run_block: Callable[[list[Step], str], None] = _block_not_set
    run_attempts: Callable[[list[Step], str, StepCommon], Outcome] = _attempts_not_set


@dataclass
class StepContext:
    page: Page
    timeout_ms: int
    step_id: str
    locator_used: str | None = None
    run: RunContext | None = None
    path: str = ""
    # A block handler that applies retry/on_error per iteration sets this, so run_step does
    # not apply them again to the whole block.
    per_iteration: bool = False
    # Set by the handler when the step succeeded overall but some iteration failed.
    outcome: Outcome = "ok"

    def require_run(self) -> RunContext:
        if self.run is None:
            raise StepError(self.step_id, "this step needs a run context")
        return self.run

    def resolve(self, targets: list[Target], frame: list[Target] | None) -> Resolved:
        resolved = resolve_target(
            self.page, targets, frame=frame, timeout_ms=self.timeout_ms, step_id=self.step_id
        )
        self.locator_used = describe(targets[resolved.index])
        return resolved
