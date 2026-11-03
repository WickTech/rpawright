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
