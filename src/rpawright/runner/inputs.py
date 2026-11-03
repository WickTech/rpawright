"""Workflow inputs, ``vars:`` and the expression namespace.

Only YAML-authored strings are ever rendered (R25): defaults and ``vars:`` values once, step
fields per execution.  Provided input values and everything stored in vars are plain data and are
never rendered again.
"""

from collections.abc import Callable, Mapping
from datetime import date
from decimal import Decimal
from pathlib import PurePath
from typing import Any

from rpawright.runner.context import Scope
from rpawright.workflow.expressions import ASSET, SECRET, ExpressionError, env_namespace
from rpawright.workflow.models import InputSpec, Workflow
from rpawright.workflow.templating import render_value

__all__ = [
    "InputError",
    "build_namespace",
    "init_vars",
    "parse_input_pairs",
    "resolve_inputs",
    "to_plain",
]

_TRUE = frozenset({"true", "yes", "1"})
_FALSE = frozenset({"false", "no", "0"})
_MAX_PLAIN_DEPTH = 50


class InputError(Exception):
    """Bad, missing or unknown inputs, or a failing default / ``vars:`` entry (CLI exit 2)."""


def to_plain(value: object, depth: int = 0) -> Any:
    """Convert anything that is not plain data (C12) into plain data."""
    if depth > _MAX_PLAIN_DEPTH:
        return str(value)
    if value is None or isinstance(value, bool | int | float | str | date):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes | bytearray):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, PurePath):
        return str(value)
    if isinstance(value, dict):
        return {
            (k if isinstance(k, str | int) else str(k)): to_plain(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [to_plain(v, depth + 1) for v in value]
    if isinstance(value, set | frozenset):
        items = [to_plain(v, depth + 1) for v in value]
        try:
            return sorted(items)
        except TypeError:
            return items
    return str(value)


def build_namespace(scope: Scope, *, env: Mapping[str, str], today: date) -> dict[str, object]:
    """Names visible to expressions; later entries win (R2): vars, loop, then reserved names."""
    ns: dict[str, object] = {}
    ns.update(to_plain(scope.vars))
    ns.update(to_plain(scope.loop))
    ns["inputs"] = to_plain(scope.inputs)
    ns["vars"] = to_plain(scope.vars)
    ns["secret"] = SECRET
    ns["asset"] = ASSET
    ns["env"] = env_namespace(env)
    ns["today"] = today
    return ns


def _coerce(name: str, spec: InputSpec, value: object) -> object:
    kind = spec.type
    bad = InputError(f"input '{name}' must be {kind}, got {value!r}")
    if kind == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, bool | int | float):
            return str(value)
        raise bad
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in _TRUE | _FALSE:
            return value.strip().lower() in _TRUE
        raise bad
    if isinstance(value, bool):
        raise bad
    if kind == "int":
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                raise bad from None
        raise bad
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            raise bad from None
    raise bad


def resolve_inputs(
    wf: Workflow, provided: Mapping[str, object], *, env: Mapping[str, str], today: date
) -> dict[str, object]:
    """Merge provided values with defaults and coerce to the declared types (R20)."""
    declared = ", ".join(wf.inputs) or "none"
    for key in provided:
        if key not in wf.inputs:
            raise InputError(f"unknown input '{key}' (declared: {declared})")
    namespace = build_namespace(Scope(), env=env, today=today)
    resolved: dict[str, object] = {}
    for key, spec in wf.inputs.items():
        if key in provided:
            resolved[key] = _coerce(key, spec, provided[key])
        elif spec.default is None:
            raise InputError(f"missing required input '{key}'")
        else:
            try:
                default = render_value(spec.default, namespace, f"inputs.{key}")
            except ExpressionError as e:
                raise InputError(f"inputs.{key}: {e}") from e
            resolved[key] = _coerce(key, spec, default)
    return resolved


def init_vars(
    wf: Workflow, namespace_factory: Callable[[], dict[str, object]], scope: Scope
) -> None:
    """Render ``vars:`` in order; each entry sees the earlier ones."""
    for key, value in wf.vars.items():
        try:
            rendered = render_value(value, namespace_factory(), f"vars.{key}")
        except ExpressionError as e:
            where = e.where or f"vars.{key}"
            raise InputError(f"{where}: {e}") from e
        scope.vars[key] = rendered


def parse_input_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse repeated ``k=v`` options; the last value for a key wins."""
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise InputError(f"bad --input '{pair}': expected name=value")
        out[key] = value
    return out
