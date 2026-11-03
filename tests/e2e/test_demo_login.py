"""End-to-end: the bundled demo bot runs through the CLI against the local fixture site."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from rpawright.cli import app

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "bots" / "demo-login.yaml"


def run_example(tmp_path: Path, site_url: str, page_name: str) -> Any:
    src = EXAMPLE.read_text(encoding="utf-8")
    base = "http://127.0.0.1:8765"
    old_url = f"{base}/login.html"
    assert old_url in src
    bot = tmp_path / "bot.yaml"
    bot.write_text(src.replace(old_url, f"{site_url}/{page_name}"), encoding="utf-8")
    assert f"{site_url}/{page_name}" in bot.read_text(encoding="utf-8")
    return CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")])


def read_log(tmp_path: Path) -> list[dict[str, Any]]:
    logs = list((tmp_path / "runs").glob("*/*/log.jsonl"))
    assert len(logs) == 1
    return [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]


def test_log_records_have_step_event(tmp_path: Path, site_url: str) -> None:
    result = run_example(tmp_path, site_url, "login.html")
    assert result.exit_code == 0, result.output
    assert all(r["event"] == "step" for r in read_log(tmp_path))


def test_example_validates() -> None:
    assert CliRunner().invoke(app, ["validate", str(EXAMPLE)]).exit_code == 0


def test_demo_login_original_site(tmp_path: Path, site_url: str) -> None:
    result = run_example(tmp_path, site_url, "login.html")
    assert result.exit_code == 0, result.output
    fill = next(r for r in read_log(tmp_path) if r.get("step_id") == "fill-2")
    assert fill["locator_used"] == "css=#email"


def test_demo_login_survives_changed_id(tmp_path: Path, site_url: str) -> None:
    result = run_example(tmp_path, site_url, "login_v2.html")
    assert result.exit_code == 0, result.output
    fill = next(r for r in read_log(tmp_path) if r.get("step_id") == "fill-2")
    assert fill["locator_used"].startswith("role=textbox")


def _bot(tmp_path: Path, text: str) -> Path:
    bot = tmp_path / "bot.yaml"
    bot.write_text(text, encoding="utf-8")
    return bot


_LOG_BOT = """version: 1
name: t
inputs:
  n: {type: int, default: 1}
  s: {type: string, default: z}
steps:
  - log: {message: "n={{ inputs.n }} s={{ inputs.s }}"}
"""


def test_run_missing_input_exits_2_without_traceback(tmp_path: Path) -> None:
    bot = _bot(
        tmp_path,
        'version: 1\nname: t\ninputs:\n  month: {type: string}\nsteps:\n  - log: {message: "x"}\n',
    )
    result = CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 2
    assert "missing required input 'month'" in result.stderr
    assert result.stdout == ""
    assert "Traceback" not in result.output
    assert not (tmp_path / "runs").exists()


def test_run_input_flag_is_repeatable_and_typed(tmp_path: Path) -> None:
    bot = _bot(tmp_path, _LOG_BOT)
    result = CliRunner().invoke(
        app,
        ["run", str(bot), "--runs-dir", str(tmp_path / "runs"), "--input", "n=7", "-i", "s=x"],
    )
    assert result.exit_code == 0, result.output
    assert "log  n=7 s=x" in result.output


def test_run_bad_int_input_exits_2(tmp_path: Path) -> None:
    bot = _bot(tmp_path, _LOG_BOT)
    result = CliRunner().invoke(
        app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs"), "--input", "n=seven"]
    )
    assert result.exit_code == 2
    assert "error  " in result.stderr
    assert "error  " not in result.stdout
    assert "Traceback" not in result.output


def test_run_vars_expression_error_exits_2(tmp_path: Path) -> None:
    bot = _bot(
        tmp_path,
        'version: 1\nname: t\nvars:\n  x: "{{ nope }}"\nsteps:\n  - log: {message: "x"}\n',
    )
    result = CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 2
    assert "vars.x: 'nope' is undefined" in result.output
    assert not (tmp_path / "runs").exists()


def test_step_mode_eof_aborts_cleanly(tmp_path: Path) -> None:
    bot = _bot(tmp_path, _LOG_BOT)
    result = CliRunner().invoke(
        app, ["run", str(bot), "--step", "--runs-dir", str(tmp_path / "runs")], input=""
    )
    assert result.exit_code == 1
    assert result.stderr.strip().endswith("aborted")
    assert "press Enter to run" in result.stdout
    assert "Traceback" not in result.output
