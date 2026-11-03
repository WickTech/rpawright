"""Inputs, vars and the expression namespace."""

from datetime import date
from typing import Any

import pytest

from rpawright.runner.context import Scope
from rpawright.runner.inputs import (
    InputError,
    build_namespace,
    init_vars,
    parse_input_pairs,
    resolve_inputs,
)
from rpawright.workflow.models import Workflow

TODAY = date(2026, 11, 2)


def _wf(**extra: Any) -> Workflow:
    return Workflow.model_validate(
        {"version": 1, "name": "t", "steps": [{"log": {"message": "x"}}], **extra}
    )


def test_env_namespace_only_prefixed() -> None:
    env = {"RPAWRIGHT_ENV_REGION": "eu", "RPAWRIGHT_VAULT_KEY": "k", "HOME": "/h"}
    ns = build_namespace(Scope(), env=env, today=TODAY)
    assert ns["env"] == {"REGION": "eu"}
    assert "RPAWRIGHT_VAULT_KEY" not in ns["env"]  # type: ignore[operator]
    assert "k" not in ns["env"].values()  # type: ignore[attr-defined]


def test_namespace_precedence() -> None:
    scope = Scope(vars={"x": 1, "y": 2}, loop={"x": 99})
    ns = build_namespace(scope, env={}, today=TODAY)
    assert ns["x"] == 99
    assert ns["y"] == 2
    assert ns["vars"] == {"x": 1, "y": 2}  # type: ignore[comparison-overlap]
    assert ns["today"] == TODAY


def test_namespace_converts_non_plain_data() -> None:
    from decimal import Decimal
    from pathlib import Path

    scope = Scope(vars={"d": Decimal("1.5"), "p": Path("a/b"), "s": {1}, "rows": [{"c": b"hi"}]})
    ns = build_namespace(scope, env={}, today=TODAY)
    assert ns["d"] == 1.5
    assert ns["p"] == str(Path("a/b"))
    assert ns["s"] == [1]
    assert ns["rows"] == [{"c": "hi"}]


def test_resolve_inputs_coercion() -> None:
    wf = _wf(
        inputs={
            "n": {"type": "int"},
            "f": {"type": "float"},
            "b": {"type": "bool"},
        }
    )
    got = resolve_inputs(wf, {"n": "7", "f": "1.5", "b": "Yes"}, env={}, today=TODAY)
    assert got == {"n": 7, "f": 1.5, "b": True}
    with pytest.raises(InputError, match="b"):
        resolve_inputs(wf, {"n": "1", "f": "1", "b": "maybe"}, env={}, today=TODAY)


def test_missing_required_input() -> None:
    wf = _wf(inputs={"month": {"type": "string"}})
    with pytest.raises(InputError, match="missing required input 'month'"):
        resolve_inputs(wf, {}, env={}, today=TODAY)


def test_unknown_input() -> None:
    wf = _wf(inputs={"month": {"type": "string"}})
    with pytest.raises(InputError, match=r"unknown input 'bogus' \(declared: month\)"):
        resolve_inputs(wf, {"month": "a", "bogus": "1"}, env={}, today=TODAY)


def test_default_template_rendered() -> None:
    wf = _wf(
        inputs={"month": {"type": "string", "default": "{{ today | prev_month | fmt('%Y-%m') }}"}}
    )
    assert resolve_inputs(wf, {}, env={}, today=TODAY) == {"month": "2026-10"}


def test_call_style_native_values() -> None:
    wf = _wf(inputs={"s": {"type": "string"}, "n": {"type": "int"}})
    got = resolve_inputs(wf, {"s": 5, "n": "7"}, env={}, today=TODAY)
    assert got == {"s": "5", "n": 7}


def test_default_expression_error_is_input_error() -> None:
    wf = _wf(inputs={"month": {"type": "string", "default": "{{ nope }}"}})
    with pytest.raises(InputError, match="inputs.month: 'nope' is undefined"):
        resolve_inputs(wf, {}, env={}, today=TODAY)


def test_vars_expression_error_is_input_error() -> None:
    wf = _wf(vars={"x": "{{ nope }}"})
    scope = Scope()
    with pytest.raises(InputError, match="vars.x: 'nope' is undefined"):
        init_vars(wf, lambda: build_namespace(scope, env={}, today=TODAY), scope)


def test_vars_render_in_order_and_native() -> None:
    wf = _wf(
        inputs={"n": {"type": "int", "default": 3}},
        vars={"a": "{{ inputs.n }}", "b": "{{ a + 1 }}", "c": {"k": ["{{ b }}"]}},
    )
    scope = Scope(inputs=resolve_inputs(wf, {}, env={}, today=TODAY))
    init_vars(wf, lambda: build_namespace(scope, env={}, today=TODAY), scope)
    assert scope.vars == {"a": 3, "b": 4, "c": {"k": [4]}}


def test_provided_values_never_rendered() -> None:
    wf = _wf(inputs={"s": {"type": "string"}})
    assert resolve_inputs(wf, {"s": "{{ 7*7 }}"}, env={}, today=TODAY) == {"s": "{{ 7*7 }}"}


def test_parse_input_pairs() -> None:
    assert parse_input_pairs(["a=b=c", "x=1"]) == {"a": "b=c", "x": "1"}
    with pytest.raises(InputError, match="novalue"):
        parse_input_pairs(["novalue"])


def test_namespace_converts_vars_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from rpawright.runner import inputs as mod

    rows = [{"a": i, "b": i, "c": i} for i in range(1000)]
    scope = Scope(vars={"rows": rows})
    seen: list[object] = []
    real = mod.to_plain

    def counting(value: object, depth: int = 0) -> object:
        if value is scope.vars:
            seen.append(value)
        return real(value, depth)

    monkeypatch.setattr(mod, "to_plain", counting)
    build_namespace(scope, env={}, today=TODAY)
    assert len(seen) == 1
