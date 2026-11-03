from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from rpawright.cli import app
from rpawright.workflow.loader import WorkflowError, load_workflow
from rpawright.workflow.models import Workflow


def test_yaml_syntax_error_reports_line(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("version: 1\nname: x\nsteps: [\n")
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert "line" in str(e.value) and str(p) in str(e.value)


def test_schema_error_reports_step_index(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("version: 1\nname: x\nsteps:\n  - goto: http://x\n  - click: {}\n")
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert "steps[1].click.target" in str(e.value)
    assert "GotoStep" not in str(e.value)


def test_validate_cli_exit_codes(tmp_path: Path) -> None:
    good = tmp_path / "g.yaml"
    good.write_text("version: 1\nname: g\nsteps:\n  - goto: http://x\n")
    bad = tmp_path / "b.yaml"
    bad.write_text("version: 1\nname: b\nsteps: []\n")
    r = CliRunner().invoke(app, ["validate", str(good)])
    assert r.exit_code == 0 and "ok" in r.stdout
    r = CliRunner().invoke(app, ["validate", str(good), str(bad)])
    assert r.exit_code == 2 and "Traceback" not in r.output
    assert "error  " in r.stderr and "error  " not in r.stdout
    assert "ok  " in r.stdout


def test_missing_and_non_mapping_files(tmp_path: Path) -> None:
    with pytest.raises(WorkflowError):
        load_workflow(tmp_path / "nope.yaml")
    p = tmp_path / "list.yaml"
    p.write_text("- 1\n")
    with pytest.raises(WorkflowError):
        load_workflow(p)


def test_non_utf8_file_is_clean_error(tmp_path: Path) -> None:
    p = tmp_path / "bin.yaml"
    p.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(WorkflowError):
        load_workflow(p)
    r = CliRunner().invoke(app, ["validate", str(p)])
    assert r.exit_code == 2 and "Traceback" not in r.output
    assert "error  " in r.stderr and "error  " not in r.stdout


def _msg(tmp_path: Path, steps: str) -> str:
    p = tmp_path / "b.yaml"
    p.write_text(f"version: 1\nname: x\nsteps:\n{steps}")
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert "GotoStep" not in e.value.message
    return e.value.message


def test_zero_action_keys_message(tmp_path: Path) -> None:
    assert _msg(tmp_path, "  - id: a\n") == (
        "steps[0]: a step needs exactly one action key; got []"
    )


def test_two_action_keys_message(tmp_path: Path) -> None:
    msg = _msg(tmp_path, "  - goto: http://x\n    click: {target: [{css: a}]}\n    id: a\n")
    assert msg == "steps[0]: a step needs exactly one action key; got ['goto', 'click']"


def test_duplicate_id_message(tmp_path: Path) -> None:
    msg = _msg(tmp_path, "  - {id: q, goto: http://x}\n  - {id: q, goto: http://y}\n")
    assert msg == "duplicate step id 'q'"
    p = tmp_path / "b.yaml"
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert str(e.value) == f"{p}: duplicate step id 'q'"


def test_nested_error_names_full_path(tmp_path: Path) -> None:
    msg = _msg(
        tmp_path,
        "  - goto: http://x\n  - for_each: {in: [1], as: x, steps: [{click: {}}]}\n",
    )
    assert msg.startswith("steps[1].for_each.steps[0].click.target: ")
    assert "Field required" in msg


def test_on_error_list_error_path(tmp_path: Path) -> None:
    msg = _msg(tmp_path, "  - goto: http://x\n    on_error: [{click: {}}]\n")
    assert msg.startswith("steps[0].on_error[0].click.target: ")


def test_deep_nesting_error_path(tmp_path: Path) -> None:
    msg = _msg(
        tmp_path,
        "  - if: '{{ true }}'\n"
        "    then:\n"
        "      - for_each:\n"
        "          in: [1]\n"
        "          as: x\n"
        "          steps:\n"
        "            - goto: http://x\n"
        "              on_error: [{click: {}}]\n",
    )
    assert msg.startswith("steps[0].if.then[0].for_each.steps[0].on_error[0].click.target: ")


def test_nested_zero_action_keys_message(tmp_path: Path) -> None:
    msg = _msg(tmp_path, "  - if: '{{ true }}'\n    then: [{id: a}]\n")
    assert msg == "steps[0].if.then[0]: a step needs exactly one action key; got []"


def test_bad_expression_reported_with_path(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text(
        "version: 1\nname: x\nsteps:\n  - goto: http://x\n"
        "  - fill: {target: [{css: a}], value: '{{ 1 + }}'}\n"
    )
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert "steps[1].fill.value: bad expression:" in e.value.message
    r = CliRunner().invoke(app, ["validate", str(p)])
    assert r.exit_code == 2


def test_nested_bad_expression_path(tmp_path: Path) -> None:
    msg = _msg(
        tmp_path,
        "  - goto: http://x\n  - goto: http://y\n"
        "  - for_each:\n      in: [1]\n      as: x\n      steps:\n"
        "        - click: {target: [{role: link, name: '{{ 1 + }}'}]}\n",
    )
    assert msg.startswith("steps[2].for_each.steps[0].click.target[0].name: bad expression:")


def test_vars_and_input_default_expression_checked(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("version: 1\nname: x\nvars: {a: '{{ 1 + }}'}\nsteps:\n  - goto: http://x\n")
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert e.value.message.startswith("vars.a: bad expression:")
    p.write_text(
        "version: 1\nname: x\ninputs: {n: {default: '{{ 1 + }}'}}\nsteps:\n  - goto: http://x\n"
    )
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert e.value.message.startswith("inputs.n.default: bad expression:")


def test_overlong_expression_rejected(tmp_path: Path) -> None:
    long = "{{ " + "1 + " * 3000 + "1 }}"
    assert len(long) > 10_000
    msg = _msg(tmp_path, f"  - goto: http://x\n  - goto: '{long}'\n")
    assert msg == "steps[1].goto: expression too long (max 10000 characters)"


@pytest.mark.parametrize("text", ["{% if x %}a{% endif %}", "{# c #}"])
def test_statement_and_comment_blocks_rejected(tmp_path: Path, text: str) -> None:
    msg = _msg(tmp_path, f"  - goto: '{text}'\n")
    assert msg.startswith("steps[0].goto: bad expression: only {{ }} expressions are allowed")
    msg = _msg(
        tmp_path,
        f"  - goto: http://x\n  - if: true\n    then:\n      - goto: '{text}'\n",
    )
    assert msg.startswith("steps[1].if.then[0].goto: bad expression: only {{ }}")


def test_long_statement_string_hits_length_cap_but_plain_long_is_fine(tmp_path: Path) -> None:
    msg = _msg(tmp_path, f"  - goto: '{{% if x %}}{'a' * 10_000}'\n")
    assert msg == "steps[0].goto: expression too long (max 10000 characters)"
    p = tmp_path / "ok.yaml"
    p.write_text(f"version: 1\nname: x\nsteps:\n  - goto: '{'a' * 20_000}'\n")
    load_workflow(p)


def _nested_if(depth: int) -> str:
    lines = ["version: 1", "name: x", "steps:"]
    for i in range(depth):
        pad = "  " * (2 * i + 1)
        lines += [f"{pad}- if: true", f"{pad}  then:"]
    lines.append("  " * (2 * depth + 1) + "- goto: http://x")
    return "\n".join(lines) + "\n"


def test_deep_nesting_is_clean_error(tmp_path: Path) -> None:
    flow = tmp_path / "flow.yaml"
    flow.write_text("version: 1\nname: x\nsteps: " + "[" * 3000 + "]" * 3000 + "\n")
    deep = tmp_path / "deep.yaml"
    deep.write_text(_nested_if(400))
    for p in (flow, deep):
        with pytest.raises(WorkflowError) as e:
            load_workflow(p)
        assert e.value.message == "nesting too deep"
    r = CliRunner().invoke(app, ["validate", str(flow), str(deep)])
    assert r.exit_code == 2 and "Traceback" not in r.output
    assert "error  " in r.stderr and "error  " not in r.stdout
    assert "nesting too deep" in r.stderr


def test_moderate_nesting_still_loads(tmp_path: Path) -> None:
    p = tmp_path / "ok.yaml"
    p.write_text(_nested_if(40))
    load_workflow(p)


def test_pydantic_recursion_guard_reports_nesting_too_deep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise ValidationError.from_exception_data(
            "Workflow",
            [{"type": "recursion_loop", "loc": ("steps", 0, "if", "then", 0), "input": None}],
        )

    monkeypatch.setattr(Workflow, "model_validate", boom)
    p = tmp_path / "d.yaml"
    p.write_text(_nested_if(2))
    with pytest.raises(WorkflowError) as e:
        load_workflow(p)
    assert e.value.message == "nesting too deep"
    assert str(e.value).endswith("nesting too deep") and "if.then" not in str(e.value)
