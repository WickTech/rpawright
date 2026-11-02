from typing import Any

import pytest
from pydantic import ValidationError

from rpawright.workflow.models import Target, Workflow, action_name


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
