from pathlib import Path

import pytest
from typer.testing import CliRunner

from rpawright.cli import app
from rpawright.workflow.loader import WorkflowError, load_workflow


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
    assert r.exit_code == 2 and "Traceback" not in r.stdout


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
    assert r.exit_code == 2 and "Traceback" not in r.stdout
