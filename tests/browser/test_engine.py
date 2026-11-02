import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rpawright.cli import app
from rpawright.runner.artifacts import safe_name
from rpawright.runner.engine import run_workflow
from rpawright.workflow.models import Workflow


def login_steps(base: str, email_target: list[dict]) -> list[dict]:
    return [
        {"goto": f"{base}/login.html"},
        {"fill": {"target": email_target, "value": "me@x.dev"}},
        {"fill": {"target": [{"label": "Password"}], "value": "pw"}},
        {"click": {"target": [{"role": "button", "name": "Sign in"}]}},
        {"assert": {"target": [{"role": "heading", "name": "Welcome"}], "visible": True}},
    ]


def test_login_ok_writes_log(tmp_path: Path, site_url: str) -> None:
    wf = Workflow.model_validate(
        {"version": 1, "name": "demo", "steps": login_steps(site_url, [{"css": "#email"}])}
    )
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 0 and res.status == "ok"
    lines = (res.run_dir / "log.jsonl").read_text().splitlines()
    assert len(lines) == 5 and json.loads(lines[1])["locator_used"] == "css=#email"


def test_failure_stops_screenshots_exit1(tmp_path: Path, site_url: str) -> None:
    steps = login_steps(site_url, [{"css": "#missing"}])
    wf = Workflow.model_validate(
        {"version": 1, "name": "demo", "policy": {"timeout_ms": 500}, "steps": steps}
    )
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 1 and res.failed_step == "fill-2"
    assert (res.run_dir / "fail-fill-2.png").exists() and len(res.steps) == 2


def test_retry_counts_attempts(tmp_path: Path, site_url: str) -> None:
    wf = Workflow.model_validate(
        {
            "version": 1,
            "name": "r",
            "policy": {"timeout_ms": 300},
            "steps": [
                {"goto": f"{site_url}/login.html"},
                {"click": {"target": [{"css": "#nope"}]}, "retry": {"times": 2, "delay_ms": 10}},
            ],
        }
    )
    assert run_workflow(wf, runs_root=tmp_path).steps[1].attempts == 3


def test_on_error_continue(tmp_path: Path, site_url: str) -> None:
    wf = Workflow.model_validate(
        {
            "version": 1,
            "name": "c",
            "policy": {"timeout_ms": 300},
            "steps": [
                {"goto": f"{site_url}/login.html"},
                {"click": {"target": [{"css": "#nope"}]}, "on_error": "continue"},
                {"assert": {"url_contains": "login"}},
            ],
        }
    )
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 0 and [s.status for s in res.steps] == ["ok", "continued", "ok"]


def test_unreachable_goto_is_step_error(tmp_path: Path) -> None:
    wf = Workflow.model_validate(
        {
            "version": 1,
            "name": "u",
            "policy": {"timeout_ms": 2000},
            "steps": [{"goto": "http://127.0.0.1:9/"}],
        }
    )
    res = run_workflow(wf, runs_root=tmp_path)
    assert res.exit_code == 1 and (res.run_dir / "log.jsonl").exists()


def test_safe_name_and_step_mode(tmp_path: Path, site_url: str) -> None:
    assert safe_name("my bot/ünï") == "my-bot-n"
    assert safe_name("///") == "bot"
    seen: list[str] = []
    wf = Workflow.model_validate(
        {"version": 1, "name": "a b", "steps": [{"goto": f"{site_url}/login.html"}]}
    )
    res = run_workflow(wf, runs_root=tmp_path, step_mode=True, confirm=seen.append)
    assert seen == ["goto-1"] and res.run_dir.parent.name == "a-b"


def _write_bot(tmp_path: Path, site_url: str) -> Path:
    bot = tmp_path / "bot.yaml"
    bot.write_text(
        "version: 1\nname: cli-demo\nsteps:\n"
        f"  - goto: {site_url}/login.html\n"
        "  - fill:\n      target: [{css: '#email'}]\n      value: me@x.dev\n"
        "  - fill:\n      target: [{label: Password}]\n      value: pw\n"
        "  - click:\n      target: [{role: button, name: Sign in}]\n"
        "  - assert:\n      url_contains: dashboard\n",
        encoding="utf-8",
    )
    return bot


def test_cli_run_invalid_bot_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nname: x\nsteps: []\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["run", str(bad), "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 2
    assert "bad.yaml" in result.output


def test_cli_run_good_bot_exits_0(tmp_path: Path, site_url: str) -> None:
    bot = _write_bot(tmp_path, site_url)
    result = CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 0, result.output
    assert "run ok" in result.output
    assert "click-4" in result.output


def _ok_wf(site_url: str) -> Workflow:
    return Workflow.model_validate(
        {"version": 1, "name": "t", "steps": [{"goto": f"{site_url}/login.html"}]}
    )


def test_trace_writes_zip(tmp_path: Path, site_url: str) -> None:
    res = run_workflow(_ok_wf(site_url), runs_root=tmp_path, trace=True)
    assert res.exit_code == 0
    assert (res.run_dir / "trace.zip").exists()


def test_trace_stop_failure_is_logged(
    tmp_path: Path, site_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api._generated import Tracing

    def boom(self: object, **kwargs: object) -> None:
        raise PlaywrightError("trace boom\nsecond line")

    monkeypatch.setattr(Tracing, "stop", boom)
    res = run_workflow(_ok_wf(site_url), runs_root=tmp_path, trace=True)
    assert res.exit_code == 0 and res.status == "ok"
    records = [json.loads(x) for x in (res.run_dir / "log.jsonl").read_text().splitlines()]
    assert {"event": "trace_failed", "error": "trace boom"} in records
