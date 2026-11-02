"""End-to-end: the bundled demo bot runs through the CLI against the local fixture site."""

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from rpawright.cli import app

EXAMPLE = Path("examples/bots/demo-login.yaml")


def run_example(tmp_path: Path, site_url: str, page_name: str) -> Any:
    src = EXAMPLE.read_text(encoding="utf-8")
    bot = tmp_path / "bot.yaml"
    bot.write_text(
        src.replace("http://127.0.0.1:8765", site_url).replace("login.html", page_name),
        encoding="utf-8",
    )
    return CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")])


def read_log(tmp_path: Path) -> list[dict[str, Any]]:
    logs = list((tmp_path / "runs").glob("*/*/log.jsonl"))
    assert len(logs) == 1
    return [json.loads(line) for line in logs[0].read_text(encoding="utf-8").splitlines()]


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
