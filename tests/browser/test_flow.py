"""Executor and flow tests. Uses ``run_bot`` (shared browser) only: never call run_workflow
without ``browser=`` or invoke the CLI ``run`` here, since sync Playwright cannot nest."""

import json
from collections.abc import Callable

import pytest

from rpawright.runner.context import StepContext
from rpawright.runner.engine import RunResult
from rpawright.runner.errors import NestedFailure, PolicyViolation
from rpawright.runner.handlers import HANDLERS
from rpawright.workflow.models import Step, Workflow

RunBot = Callable[..., RunResult]


def _log(result: RunResult) -> list[dict[str, object]]:
    text = (result.run_dir / "log.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def _login(site_url: str) -> dict[str, object]:
    return {"goto": f"{site_url}/login.html"}


def test_on_error_step_list_runs_handler_and_continues(run_bot: RunBot, site_url: str) -> None:
    res = run_bot(
        {
            "steps": [
                _login(site_url),
                {
                    "click": {"target": [{"css": "#missing"}]},
                    "timeout_ms": 300,
                    "on_error": [{"fill": {"target": [{"css": "#email"}], "value": "fb@x.dev"}}],
                },
                {"assert": {"target": [{"css": "#email"}], "visible": True}},
            ]
        }
    )
    assert res.status == "ok" and res.exit_code == 0
    assert [r.status for r in res.steps] == ["ok", "ok", "handled", "ok"]
    assert res.failed_step is None and res.failed_path is None
    assert list(res.run_dir.glob("fail-*.png"))


def test_on_error_handler_failure_fails_step(run_bot: RunBot, site_url: str) -> None:
    res = run_bot(
        {
            "steps": [
                _login(site_url),
                {
                    "click": {"target": [{"css": "#missing"}]},
                    "timeout_ms": 200,
                    "on_error": [{"click": {"target": [{"css": "#also-missing"}]}}],
                },
            ]
        }
    )
    assert res.exit_code == 1
    last = res.steps[-1]
    assert last.status == "failed" and last.error is not None
    assert "on_error handler failed" in last.error
    inner = res.steps[-2]
    assert inner.status == "failed" and inner.path == f"{last.path}.on_error/{inner.step_id}"
    assert res.failed_step == inner.step_id and res.failed_path == inner.path


def test_unexpected_exception_is_logged_not_traceback(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(ctx: StepContext, step: Step) -> None:
        raise RuntimeError("boom")

    monkeypatch.setitem(HANDLERS, "wait", boom)
    res = run_bot({"steps": [{"wait": 1}]})
    assert res.exit_code == 1
    errors = [str(rec["error"]) for rec in _log(res)]
    assert any("RuntimeError: boom" in e for e in errors)


def _violation(calls: list[str]) -> Callable[[StepContext, Step], None]:
    def handler(ctx: StepContext, step: Step) -> None:
        calls.append(ctx.step_id)
        raise PolicyViolation(ctx.step_id, "not allowed")

    return handler


def test_policy_violation_never_retried_or_continued(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setitem(HANDLERS, "wait", _violation(calls))
    res = run_bot(
        {
            "steps": [
                {"wait": 1, "retry": {"times": 2, "delay_ms": 0}, "on_error": "continue"},
            ]
        }
    )
    assert res.status == "failed" and res.exit_code == 1
    assert res.steps[0].status == "failed" and res.steps[0].attempts == 1
    assert res.steps[0].policy is True
    assert res.steps[0].error == "not allowed"
    assert len(calls) == 1


def test_policy_violation_never_handled_by_on_error_list(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setitem(HANDLERS, "wait", _violation(calls))
    res = run_bot(
        {
            "steps": [
                {
                    "wait": 1,
                    "retry": {"times": 2, "delay_ms": 0},
                    "on_error": [{"log": {"message": "handled"}}],
                },
            ]
        }
    )
    assert res.status == "failed"
    assert [r.status for r in res.steps] == ["failed"]
    assert res.steps[0].attempts == 1 and len(calls) == 1


def test_policy_violation_inside_on_error_list_propagates(
    run_bot: RunBot, site_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setitem(HANDLERS, "wait", _violation(calls))
    res = run_bot(
        {
            "steps": [
                _login(site_url),
                {
                    "click": {"target": [{"css": "#missing"}]},
                    "timeout_ms": 200,
                    "on_error": [
                        {"wait": 1, "retry": {"times": 2, "delay_ms": 0}, "on_error": "continue"}
                    ],
                },
            ]
        }
    )
    assert res.status == "failed" and res.exit_code == 1
    by_path = {r.path: r for r in res.steps}
    inner = next(r for p, r in by_path.items() if "on_error/" in p)
    outer = res.steps[-1]
    assert inner.status == "failed" and inner.attempts == 1 and inner.policy
    assert outer.status == "failed" and outer.policy
    assert len(calls) == 1
    assert res.failed_path == inner.path


def test_run_attempts_applies_on_error_to_a_block(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    failing = Workflow.model_validate(
        {"version": 1, "name": "x", "steps": [{"click": {"target": [{"css": "#nope"}]}}]}
    ).steps

    def runner(ctx: StepContext, step: Step) -> None:
        ctx.per_iteration = True
        seen.append(ctx.require_run().run_attempts(failing, ctx.path + "[0]", step))

    monkeypatch.setitem(HANDLERS, "wait", runner)
    res = run_bot({"steps": [{"wait": 1, "on_error": "continue", "timeout_ms": 200}]})
    assert seen == ["continued"]
    assert res.status == "ok"


def test_run_workflow_uses_injected_browser(run_bot: RunBot, _browser) -> None:  # type: ignore[no-untyped-def]
    res = run_bot({"steps": [{"wait": 1}]})
    assert res.status == "ok"
    assert _browser.is_connected()
    assert _browser.contexts == []


def test_log_records_have_path_equal_to_id_for_top_level_steps(
    run_bot: RunBot, site_url: str
) -> None:
    res = run_bot({"steps": [_login(site_url), {"wait": 1}]})
    records = _log(res)
    assert [r["path"] for r in records] == [r["step_id"] for r in records]
    assert all(r["event"] == "step" for r in records)
    assert "policy" not in records[0]


def test_failed_step_and_failed_path_set_only_on_failure(run_bot: RunBot, site_url: str) -> None:
    ok = run_bot({"steps": [_login(site_url)]})
    assert ok.failed_step is None and ok.failed_path is None
    bad = run_bot(
        {
            "steps": [
                _login(site_url),
                {"click": {"target": [{"css": "#missing"}]}, "timeout_ms": 200},
            ]
        }
    )
    assert bad.failed_step == bad.steps[-1].step_id
    assert bad.failed_path == bad.steps[-1].path == bad.failed_step


def _recovering_handler(ctx: StepContext, step: Step) -> None:
    """Test-only: a nested failure that the handler swallows, leaving a failed record."""
    nested = Workflow.model_validate(
        {
            "version": 1,
            "name": "x",
            "steps": [{"id": "inner", "click": {"target": [{"css": "#nope"}]}, "timeout_ms": 200}],
        }
    ).steps
    try:
        ctx.require_run().run_block(nested, ctx.path)
    except NestedFailure:
        pass


def test_failed_step_ignores_recovered_nested_failures(
    run_bot: RunBot, site_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(HANDLERS, "wait", _recovering_handler)
    res = run_bot(
        {
            "steps": [
                _login(site_url),
                {"id": "early", "wait": 1},
                {"id": "late", "click": {"target": [{"css": "#missing"}]}, "timeout_ms": 300},
            ]
        }
    )
    assert any(r.path == "early/inner" and r.status == "failed" for r in res.steps)
    assert res.exit_code == 1
    assert res.failed_step == "late" and res.failed_path == "late"


def test_recovered_nested_failure_leaves_run_ok(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(HANDLERS, "wait", _recovering_handler)
    res = run_bot({"steps": [{"id": "early", "wait": 1}]})
    assert any(r.status == "failed" for r in res.steps)
    assert res.exit_code == 0 and res.status == "ok"
    assert res.failed_step is None and res.failed_path is None
