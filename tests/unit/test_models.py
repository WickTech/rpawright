from typing import Any

import pytest
from pydantic import ValidationError

from rpawright.workflow.models import (
    ForEachStep,
    IfStep,
    PauseStep,
    Target,
    Workflow,
    action_name,
    child_blocks,
    iter_steps,
)


def wf(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {"version": 1, "name": "t", "steps": steps}


def test_target_requires_exactly_one_kind() -> None:
    with pytest.raises(ValidationError):
        Target.model_validate({"css": "a", "text": "b"})
    with pytest.raises(ValidationError):
        Target.model_validate({"nth": 1})
    assert Target.model_validate({"role": "button", "name": "Go"}).kind == "role"


def test_name_only_with_role() -> None:
    with pytest.raises(ValidationError):
        Target.model_validate({"css": "a", "name": "x"})


def test_step_with_two_actions_rejected() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"goto": "http://x", "click": {"target": [{"css": "a"}]}}]))


def test_step_with_no_action_rejected() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"id": "lonely"}]))


def test_ids_autofilled_and_unique() -> None:
    w = Workflow.model_validate(wf([{"goto": "http://x"}, {"press": "Enter"}]))
    assert [s.id for s in w.steps] == ["goto-1", "press-2"]
    with pytest.raises(ValidationError):
        Workflow.model_validate(
            wf([{"id": "a", "goto": "http://x"}, {"id": "a", "press": "Enter"}])
        )


def test_assert_alias_and_action_name() -> None:
    w = Workflow.model_validate(wf([{"assert": {"url_contains": "/dash"}}]))
    assert action_name(w.steps[0]) == "assert"


def test_version_must_be_1_and_defaults() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate({"version": 2, "name": "t", "steps": [{"goto": "http://x"}]})
    w = Workflow.model_validate(wf([{"goto": "http://x"}]))
    assert (w.policy.timeout_ms, w.policy.headless, w.policy.heal) == (15000, True, "propose")
    assert w.steps[0].on_error == "fail"


def test_wait_body_needs_exactly_one_mode() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"wait": {"ms": 5, "url_contains": "x"}}]))


@pytest.mark.parametrize("bad", [0, -1])
def test_timeouts_must_be_positive(bad: int) -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate({**wf([{"goto": "http://x"}]), "policy": {"timeout_ms": bad}})
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"goto": "http://x", "timeout_ms": bad}]))


def test_negative_waits_rejected() -> None:
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"wait": -1}]))
    with pytest.raises(ValidationError):
        Workflow.model_validate(wf([{"wait": {"ms": -1}}]))
    Workflow.model_validate(wf([{"wait": 0}, {"wait": {"ms": 0}}]))


def _ok(steps: list[dict[str, Any]], **extra: Any) -> Workflow:
    return Workflow.model_validate({**wf(steps), **extra})


def _bad(steps: list[dict[str, Any]], **extra: Any) -> str:
    with pytest.raises(ValidationError) as e:
        _ok(steps, **extra)
    return str(e.value)


def test_ids_unique_across_nested_blocks() -> None:
    msg = _bad(
        [
            {"for_each": {"in": [1], "as": "x", "steps": [{"id": "a", "goto": "http://x"}]}},
            {"id": "a", "goto": "http://y"},
        ]
    )
    assert "duplicate step id 'a'" in msg


def test_auto_ids_use_preorder_counter() -> None:
    w = _ok(
        [
            {"goto": "http://x"},
            {"for_each": {"in": [1], "as": "x", "steps": [{"click": {"target": [{"css": "a"}]}}]}},
            {"press": "Enter"},
        ]
    )
    assert [s.id for s in iter_steps(w.steps)] == ["goto-1", "for_each-2", "click-3", "press-4"]


def test_if_for_each_call_aliases() -> None:
    w = _ok(
        [
            {"if": "{{ a }}", "then": [{"goto": "http://x"}], "else": [{"goto": "http://y"}]},
            {"for_each": {"in": "{{ rows }}", "as": "r", "steps": [{"goto": "http://x"}]}},
        ]
    )
    assert isinstance(w.steps[0], IfStep) and len(w.steps[0].else_) == 1
    assert isinstance(w.steps[1], ForEachStep) and w.steps[1].for_each.as_ == "r"
    _bad([{"if_": True, "then": [{"goto": "http://x"}]}])
    with pytest.raises(ValidationError):
        _ok([{"if": True, "then": [{"goto": "http://x"}], "else_": []}])
    with pytest.raises(ValidationError):
        _ok([{"for_each": {"in_": [1], "as": "x", "steps": [{"goto": "http://x"}]}}])
    with pytest.raises(ValidationError):
        _ok([{"for_each": {"in": [1], "as_": "x", "steps": [{"goto": "http://x"}]}}])


def test_if_requires_whole_expression_or_bool() -> None:
    then = [{"goto": "http://x"}]
    for bad in ("true", "{{ a }} x"):
        assert "if" in _bad([{"if": bad, "then": then}])
    _ok([{"if": True, "then": then}])
    _ok([{"if": "{{ a > 1 }}", "then": then}])


def test_var_names_reject_jinja_keywords() -> None:
    target = {"target": [{"css": "a"}]}
    _bad([{"extract_text": {**target, "into": "true"}}])
    _bad([{"for_each": {"in": [1], "as": "and", "steps": [{"goto": "http://x"}]}}])
    _bad([{"set": {"none": 1}}])
    _bad([{"extract_text": {**target, "into": "not an identifier"}}])
    _ok([{"extract_text": {**target, "into": "total_1"}}])


def test_pause_requires_key() -> None:
    with pytest.raises(ValidationError):
        _ok([{"id": "x"}])
    w = _ok([{"pause": None}])
    assert isinstance(w.steps[0], PauseStep) and w.steps[0].pause is None


def test_on_error_accepts_step_list() -> None:
    w = _ok([{"goto": "http://x", "on_error": [{"log": {"message": "m"}}]}])
    assert w.steps[0].on_error != "fail"
    assert [s.id for s in iter_steps(w.steps)] == ["goto-1", "log-2"]
    assert child_blocks(w.steps[0])[0][0] == "on_error"
    _ok([{"goto": "http://x", "on_error": "continue"}])
    _bad([{"goto": "http://x", "on_error": "explode"}])


def test_child_blocks_order() -> None:
    w = _ok(
        [
            {
                "if": True,
                "then": [{"goto": "http://x"}],
                "else": [{"goto": "http://y"}],
                "on_error": [{"goto": "http://z"}],
            }
        ]
    )
    assert [label for label, _ in child_blocks(w.steps[0])] == ["then", "else", "on_error"]


def test_select_needs_exactly_one_of_value_label() -> None:
    t = [{"css": "s"}]
    _ok([{"select": {"target": t, "value": "a"}}])
    _ok([{"select": {"target": t, "label": "A"}}])
    _bad([{"select": {"target": t}}])
    _bad([{"select": {"target": t, "value": "a", "label": "A"}}])


def test_http_json_and_body_exclusive() -> None:
    _ok([{"http": {"url": "http://x", "json": {"a": 1}}}])
    _ok([{"http": {"url": "http://x", "body": "raw", "expect_status": [200, 201]}}])
    _bad([{"http": {"url": "http://x", "json": {"a": 1}, "body": "raw"}}])
    _bad([{"http": {"url": "http://x", "method": "TRACE"}}])
    _bad([{"http": {"url": "http://x", "json_": {"a": 1}}}])


def test_input_default_must_match_type() -> None:
    step = [{"goto": "http://x"}]
    _ok(step, inputs={"n": {"type": "int", "default": 3}})
    _ok(step, inputs={"n": {"type": "int", "default": "{{ 1 + 2 }}"}})
    _ok(step, inputs={"s": {}})
    _bad(step, inputs={"n": {"type": "int", "default": "abc"}})
    _bad(step, inputs={"b": {"type": "bool", "default": 1}})
    _bad(step, inputs={"s": {"type": "string", "default": 5}})
    _bad(step, inputs={"f": {"type": "float", "default": True}})


def test_reserved_names_rejected() -> None:
    target = {"target": [{"css": "a"}]}
    _bad([{"extract_text": {**target, "into": "inputs"}}])
    _bad([{"for_each": {"in": [1], "as": "today", "steps": [{"goto": "http://x"}]}}])
    _bad([{"goto": "http://x"}], vars={"secret": 1})
    _bad([{"goto": "http://x"}], inputs={"env": {}})
    w = _ok([{"goto": "http://x"}], vars={"total": 1}, inputs={"who": {}})
    assert w.vars == {"total": 1}
