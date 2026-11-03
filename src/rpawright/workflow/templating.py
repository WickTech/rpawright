"""Walk workflow models for {{ }} strings: render them at run time, check them at load time."""

from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import BaseModel

from rpawright.workflow.expressions import ExpressionError, check_syntax, evaluate
from rpawright.workflow.models import StepCommon, Workflow, child_blocks

MAX_EXPRESSION_CHARS = 10_000
_MARKERS = ("{{", "{%", "{#")
_SKIPPED = frozenset({"id"})


def _yaml_name(model: BaseModel, field: str) -> str:
    return model.__class__.model_fields[field].alias or field


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def iter_strings(model: BaseModel, path: str) -> Iterator[tuple[str, str]]:
    """Yield (yaml path, text) for every string field, skipping ``id`` and lazy fields."""
    lazy: frozenset[str] = getattr(model, "LAZY_FIELDS", frozenset())
    for field in type(model).model_fields:
        if field in _SKIPPED or field in lazy:
            continue
        here = _join(path, _yaml_name(model, field))
        yield from _walk(getattr(model, field), here)


def _walk(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, BaseModel):
        yield from iter_strings(value, path)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk(item, f"{path}[{i}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, f"{path}.{key}")


def _render(value: Any, ns: Mapping[str, object], path: str, native: bool) -> Any:
    if isinstance(value, str):
        try:
            return evaluate(value, ns, native=native)
        except ExpressionError as e:
            e.where = path
            raise
    if isinstance(value, BaseModel):
        return _render_model(value, ns, path, native)
    if isinstance(value, list):
        return [_render(v, ns, f"{path}[{i}]", native) for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: _render(v, ns, f"{path}.{k}", native) for k, v in value.items()}
    return value


def _render_model(model: BaseModel, ns: Mapping[str, object], path: str, inherited: bool) -> Any:
    native_fields: frozenset[str] = getattr(model, "NATIVE_FIELDS", frozenset())
    lazy: frozenset[str] = getattr(model, "LAZY_FIELDS", frozenset())
    update: dict[str, Any] = {}
    for field in type(model).model_fields:
        if field in _SKIPPED or field in lazy:
            continue
        here = _join(path, _yaml_name(model, field))
        update[field] = _render(
            getattr(model, field), ns, here, inherited or field in native_fields
        )
    return model.model_copy(update=update)


def render_step[S: StepCommon](step: S, namespace: Mapping[str, object]) -> S:
    """Return a copy of ``step`` with every string field rendered (lazy fields untouched)."""
    return _render_model(step, namespace, "", False)  # type: ignore[no-any-return]


def _check(path: str, text: str, problems: list[str], prefix: str) -> None:
    if not any(marker in text for marker in _MARKERS):
        return
    if len(text) > MAX_EXPRESSION_CHARS:
        problems.append(
            f"{prefix}{path}: expression too long (max {MAX_EXPRESSION_CHARS} characters)"
        )
        return
    message = check_syntax(text)
    if message is not None:
        problems.append(f"{prefix}{path}: bad expression: {message}")


def _check_steps(steps: list[Any], prefix: str, problems: list[str]) -> None:
    for i, step in enumerate(steps):
        here = f"{prefix}[{i}]"
        for path, text in iter_strings(step, ""):
            _check(path, text, problems, f"{here}.")
        for label, block in child_blocks(step):
            # YAML path: if.then, if.else, for_each.steps, on_error
            owner = {"then": "if", "else": "if", "steps": "for_each"}.get(label)
            sub = f"{here}.{owner}.{label}" if owner else f"{here}.{label}"
            _check_steps(block, sub, problems)


def expression_errors(wf: Workflow) -> list[str]:
    """Syntax problems in every {{ }} string, as ``<yaml path>: bad expression: <msg>``."""
    problems: list[str] = []
    for key, value in wf.vars.items():
        for path, text in _walk(value, f"vars.{key}"):
            _check(path, text, problems, "")
    for key, spec in wf.inputs.items():
        if isinstance(spec.default, str):
            _check(f"inputs.{key}.default", spec.default, problems, "")
    _check_steps(list(wf.steps), "steps", problems)
    return problems
