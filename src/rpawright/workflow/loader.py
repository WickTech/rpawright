"""Load and validate workflow YAML files."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from rpawright.workflow.models import Workflow


class WorkflowError(Exception):
    """A workflow file could not be read, parsed or validated."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def _format_loc(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


_STEP_MODELS = {
    "goto": "GotoStep",
    "click": "ClickStep",
    "fill": "FillStep",
    "press": "PressStep",
    "wait": "WaitStep",
    "assert": "AssertStep",
}


def _first_error(exc: ValidationError, data: dict[str, Any]) -> str:
    """Format the most relevant error.

    A step is a union of per-action models, so pydantic reports an error for every
    model. Prefer the errors of the model matching the step's single action key.
    """
    errors = exc.errors()
    first = errors[0]["loc"]
    steps = data.get("steps")
    if first[:1] == ("steps",) and len(first) > 2 and isinstance(steps, list):
        index = first[1]
        step = steps[index] if isinstance(index, int) and index < len(steps) else None
        actions = [k for k in step if k in _STEP_MODELS] if isinstance(step, dict) else []
        if len(actions) == 1:
            for err in errors:
                loc = err["loc"]
                if loc[:2] == ("steps", index) and loc[2:3] == (_STEP_MODELS[actions[0]],):
                    return f"{_format_loc((*loc[:2], *loc[3:]))}: {err['msg']}"
    return f"{_format_loc(first)}: {errors[0]['msg']}"


def load_workflow(path: Path) -> Workflow:
    """Parse and validate a workflow file, raising WorkflowError on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise WorkflowError(path, f"cannot read file ({e.strerror or e})") from e
    try:
        data = YAML(typ="safe").load(text)
    except YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark is not None else ""
        problem = getattr(e, "problem", None) or "invalid YAML"
        raise WorkflowError(path, f"{where}{problem}") from e
    if not isinstance(data, dict):
        raise WorkflowError(path, "top level must be a mapping")
    try:
        return Workflow.model_validate(data)
    except ValidationError as e:
        raise WorkflowError(path, _first_error(e, data)) from e
