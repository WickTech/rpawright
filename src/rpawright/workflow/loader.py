"""Load and validate workflow YAML files."""

from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from rpawright.workflow.models import Workflow
from rpawright.workflow.templating import expression_errors


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


_COMMON_FIELDS = ("id", "retry", "on_error", "timeout_ms")


def _clean_msg(msg: str) -> str:
    return msg.removeprefix("Value error, ")


def _join(loc: tuple[int | str, ...], msg: str) -> str:
    where = _format_loc(loc)
    return f"{where}: {_clean_msg(msg)}" if where else _clean_msg(msg)


_STEP_LISTS = ("steps", "then", "else", "on_error")


def _clean_loc(loc: tuple[int | str, ...]) -> tuple[int | str, ...]:
    """Drop pydantic's union bookkeeping: branch labels and the step-tag segment."""
    parts = [p for p in loc if not (isinstance(p, str) and p.startswith(("literal[", "list[")))]
    out: list[int | str] = []
    for i, part in enumerate(parts):
        is_tag = (
            isinstance(part, str)
            and i >= 2
            and isinstance(parts[i - 1], int)
            and parts[i - 2] in _STEP_LISTS
        )
        # An `if` step's own key is not repeated in the loc: its tag stands for `if`.
        if is_tag and part == "if" and parts[i + 1 : i + 2] in (["then"], ["else"]):
            is_tag = False
        if not is_tag:
            out.append(part)
    return tuple(out)


def _in_list_branch(loc: tuple[int | str, ...], prefix: tuple[int | str, ...]) -> bool:
    return (
        loc[: len(prefix)] == prefix
        and len(loc) > len(prefix)
        and str(loc[len(prefix)]).startswith("list[")
    )


def _first_error(exc: ValidationError) -> str:
    """Format the first error; steps are tagged unions, so errors only name the chosen model."""
    errors = exc.errors()
    err = errors[0]
    last = err["loc"][-1:]
    if last and str(last[0]).startswith("literal[") and isinstance(err["input"], list):
        # `on_error` is "fail" | "continue" | a step list; a list was meant, so show its errors.
        prefix = err["loc"][:-1]
        err = next((e for e in errors if _in_list_branch(e["loc"], prefix)), err)
    where = _clean_loc(err["loc"])
    if err["type"] == "union_tag_not_found":
        value = err.get("input")
        found = [k for k in value if k not in _COMMON_FIELDS] if isinstance(value, dict) else []
        return _join(where, f"a step needs exactly one action key; got {found}")
    return _join(where, err["msg"])


def load_workflow(path: Path) -> Workflow:
    """Parse and validate a workflow file, raising WorkflowError on any problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise WorkflowError(path, f"cannot read file ({e.strerror or e})") from e
    except UnicodeDecodeError as e:
        raise WorkflowError(path, "file is not valid UTF-8 text") from e
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
        wf = Workflow.model_validate(data)
    except ValidationError as e:
        raise WorkflowError(path, _first_error(e)) from e
    problems = expression_errors(wf)
    if problems:
        raise WorkflowError(path, problems[0])
    return wf
