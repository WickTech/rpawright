import json
from pathlib import Path

from typer.testing import CliRunner

from rpawright.cli import app
from rpawright.workflow.schema import workflow_json_schema


def test_schema_uses_yaml_surface_names() -> None:
    text = json.dumps(workflow_json_schema())
    for key in ('"goto"', '"click"', '"fill"', '"assert"', '"testid"'):
        assert key in text
    assert '"assert_"' not in text


def test_committed_schema_is_current() -> None:
    committed = json.loads(Path("schema/workflow.schema.json").read_text())
    assert committed == workflow_json_schema()


def test_schema_command_prints_schema_to_stdout() -> None:
    result = CliRunner().invoke(app, ["schema"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == workflow_json_schema()


def test_schema_command_writes_file_with_out_option(tmp_path: Path) -> None:
    out = tmp_path / "workflow.schema.json"
    result = CliRunner().invoke(app, ["schema", "--out", str(out)])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert out.read_text() == json.dumps(workflow_json_schema(), indent=2, sort_keys=True) + "\n"
