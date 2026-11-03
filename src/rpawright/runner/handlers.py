"""Merged registry of step handlers, keyed by YAML action name."""

from collections.abc import Callable

from rpawright.runner.context import StepContext
from rpawright.runner.steps import M1_HANDLERS
from rpawright.workflow.models import Step

HANDLERS: dict[str, Callable[[StepContext, Step], None]] = {**M1_HANDLERS}
