"""Errors raised while running a workflow step."""


class StepError(Exception):
    """A step failed; carries the step id and a human-readable message."""

    def __init__(self, step_id: str, message: str) -> None:
        super().__init__(f"step {step_id}: {message}")
        self.step_id = step_id
        self.message = message


class LocatorNotFound(StepError):
    """No locator candidate matched exactly one visible element before the timeout."""

    def __init__(self, step_id: str, message: str, tried: list[tuple[str, int]]) -> None:
        super().__init__(step_id, message)
        self.tried = tried


class AssertionFailed(StepError):
    """An assert step did not hold."""


class PolicyViolation(StepError):
    """A bot broke a safety policy; never retried, handled or continued by any ``on_error``."""


class NestedFailure(StepError):
    """A step inside a nested block failed; ``policy`` is set when it was a policy failure."""

    def __init__(self, step_id: str, message: str, *, policy: bool = False) -> None:
        super().__init__(step_id, message)
        self.policy = policy
