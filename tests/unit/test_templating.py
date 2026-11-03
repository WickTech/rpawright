from typing import Any

import pytest

from rpawright.workflow.expressions import ExpressionError
from rpawright.workflow.models import (
    ClickStep,
    FillStep,
    ForEachStep,
    SetStep,
    Workflow,
    WriteCsvStep,
)
from rpawright.workflow.templating import expression_errors, iter_strings, render_step


def _step(raw: dict[str, Any]) -> Any:
    return Workflow.model_validate({"version": 1, "name": "t", "steps": [raw]}).steps[0]


def test_render_step_renders_target_values() -> None:
    step = _step({"click": {"target": [{"role": "link", "name": "{{ inv.Number }}"}]}})
    out = render_step(step, {"inv": {"Number": "INV-1"}})
    assert isinstance(out, ClickStep)
    assert out.click.target[0].name == "INV-1"
    assert out.click.target[0].exact is False
    assert step.click.target[0].name == "{{ inv.Number }}"


def test_native_field_keeps_list() -> None:
    rows = [{"a": 1}]
    out = render_step(_step({"write_csv": {"path": "o.csv", "rows": "{{ rows }}"}}), {"rows": rows})
    assert isinstance(out, WriteCsvStep) and out.write_csv.rows == rows
    out2 = render_step(_step({"set": {"a": "{{ n }}"}}), {"n": 5})
    assert isinstance(out2, SetStep) and out2.set == {"a": 5}


def test_text_field_never_native() -> None:
    out = render_step(_step({"fill": {"target": [{"css": "a"}], "value": "{{ n }}"}}), {"n": 5})
    assert isinstance(out, FillStep) and out.fill.value == "5"


def test_lazy_fields_not_rendered() -> None:
    step = _step(
        {
            "for_each": {
                "in": "{{ items }}",
                "as": "inv",
                "steps": [{"goto": "{{ inv }}"}],
            }
        }
    )
    out = render_step(step, {"items": [1, 2]})
    assert isinstance(out, ForEachStep)
    assert out.for_each.in_ == [1, 2]
    assert out.for_each.steps[0].goto == "{{ inv }}"  # type: ignore[union-attr]


def test_id_not_rendered() -> None:
    out = render_step(_step({"id": "{{ x }}", "goto": "http://{{ x }}"}), {"x": "a"})
    assert out.id == "{{ x }}"
    assert out.goto == "http://a"  # type: ignore[union-attr]


def test_expression_error_sets_where() -> None:
    step = _step({"fill": {"target": [{"css": "a"}], "value": "{{ nope }}"}})
    with pytest.raises(ExpressionError) as e:
        render_step(step, {})
    assert e.value.where == "fill.value"


def test_iter_strings_uses_yaml_names() -> None:
    step = _step({"fill": {"target": [{"role": "r", "name": "N"}], "value": "v", "frame": None}})
    paths = dict(iter_strings(step, ""))
    assert paths["fill.target[0].name"] == "N"
    assert paths["fill.value"] == "v"


def test_expression_errors_lists_paths() -> None:
    wf = Workflow.model_validate(
        {
            "version": 1,
            "name": "t",
            "vars": {"v": "{{ 1 + }}"},
            "steps": [
                {"goto": "http://x"},
                {"for_each": {"in": [1], "as": "x", "steps": [{"goto": "{{ 1 + }}"}]}},
            ],
        }
    )
    errs = expression_errors(wf)
    assert errs[0].startswith("vars.v: bad expression:")
    assert any(e.startswith("steps[1].for_each.steps[0].goto: bad expression:") for e in errs)
