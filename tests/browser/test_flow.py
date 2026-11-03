"""Executor and flow tests. Uses ``run_bot`` (shared browser) only: never call run_workflow
without ``browser=`` or invoke the CLI ``run`` here, since sync Playwright cannot nest."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from rpawright.runner.context import StepContext
from rpawright.runner.engine import RunResult
from rpawright.runner.errors import NestedFailure, PolicyViolation, StepError
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


def _steps(*steps: dict[str, object]) -> list[Step]:
    return Workflow.model_validate({"version": 1, "name": "x", "steps": list(steps)}).steps


_MISSING = {"click": {"target": [{"css": "#nope"}]}, "timeout_ms": 200}


def test_failed_step_with_dotted_and_slashed_ids(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def recover(ctx: StepContext, step: Step) -> None:
        try:
            ctx.require_run().run_block(_steps({"id": "field", **_MISSING}), ctx.path)
        except NestedFailure:
            pass

    monkeypatch.setitem(HANDLERS, "wait", recover)
    res = run_bot(
        {
            "steps": [
                {"id": "login.submit", "wait": 1},
                {"id": "login", "click": {"target": [{"css": "#missing"}]}, "timeout_ms": 200},
            ]
        }
    )
    assert any(r.path == "login.submit/field" and r.status == "failed" for r in res.steps)
    assert res.failed_step == "login" and res.failed_path == "login"


def test_retried_block_failing_on_its_own_is_the_failed_step(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = {"n": 0}

    def block(ctx: StepContext, step: Step) -> None:
        attempt["n"] += 1
        child = _MISSING if attempt["n"] == 1 else {"wait": 1}
        ctx.require_run().run_block(_steps({"id": "c", **child}), ctx.path)
        if attempt["n"] == 2:
            raise StepError(ctx.step_id, "own failure")

    monkeypatch.setitem(HANDLERS, "press", block)
    res = run_bot({"steps": [{"id": "X", "press": "Enter", "retry": {"times": 1, "delay_ms": 10}}]})
    assert attempt["n"] == 2
    assert any(r.path == "X/c" and r.status == "failed" for r in res.steps)
    assert res.failed_step == "X" and res.failed_path == "X"
    assert res.steps[-1].error == "own failure"


def test_cause_path_survives_two_nesting_levels(
    run_bot: RunBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    def outer(ctx: StepContext, step: Step) -> None:
        ctx.require_run().run_block(_steps({"id": "mid", "press": "Enter"}), ctx.path)

    def mid(ctx: StepContext, step: Step) -> None:
        ctx.require_run().run_block(_steps({"id": "leaf", **_MISSING}), ctx.path)

    monkeypatch.setitem(HANDLERS, "wait", outer)
    monkeypatch.setitem(HANDLERS, "press", mid)
    res = run_bot({"steps": [{"id": "outer", "wait": 1}]})
    assert res.exit_code == 1
    assert res.failed_step == "leaf" and res.failed_path == "outer/mid/leaf"
    log = _log(res)
    assert all("cause_path" not in rec for rec in log)


def _messages(result: RunResult) -> list[object]:
    return [e["message"] for e in _log(result) if e.get("event") == "log"]


def test_set_keeps_native_and_text(run_bot: RunBot) -> None:
    echoed: list[str] = []
    res = run_bot(
        {
            "inputs": {"k": {"type": "int", "default": 5}},
            "steps": [
                {"set": {"n": "{{ inputs.k }}", "rows": [{"a": 1}]}},
                {"log": {"message": "n={{ n }} a={{ rows[0].a }}"}},
            ],
        },
        echo=echoed.append,
    )
    assert res.exit_code == 0
    assert _messages(res) == ["n=5 a=1"]
    assert echoed == ["n=5 a=1"]


def test_expression_error_names_step_expression_and_field(run_bot: RunBot) -> None:
    res = run_bot(
        {
            "steps": [
                {"id": "f1", "retry": {"times": 3, "delay_ms": 0}, "log": {"message": "{{ nope }}"}}
            ]
        }
    )
    assert res.exit_code == 1
    rec = res.steps[0]
    assert rec.error == "log.message: 'nope' is undefined in {{ nope }}"
    assert rec.attempts == 1


def test_secret_expression_fails_step_with_m3_message(run_bot: RunBot) -> None:
    res = run_bot({"steps": [{"log": {"message": "{{ secret.pw }}"}}]})
    assert res.exit_code == 1
    assert "secrets arrive with the vault in M3" in (res.steps[0].error or "")


def test_rendered_values_are_not_rerendered(run_bot: RunBot) -> None:
    res = run_bot(
        {
            "steps": [
                {"set": {"v": "{{ '{{ 7*7 }}' }}"}},
                {"log": {"message": "{{ v }}"}},
            ]
        }
    )
    assert res.exit_code == 0
    assert _messages(res) == ["{{ 7*7 }}"]


def test_provided_input_is_not_rendered(run_bot: RunBot) -> None:
    res = run_bot(
        {
            "inputs": {"s": {"type": "string"}},
            "steps": [{"log": {"message": "{{ inputs.s }}"}}],
        },
        inputs={"s": "{{ 7*7 }}"},
    )
    assert _messages(res) == ["{{ 7*7 }}"]


def test_log_step_writes_event_and_echoes(run_bot: RunBot) -> None:
    echoed: list[str] = []
    res = run_bot(
        {
            "inputs": {"k": {"type": "int", "default": 5}},
            "steps": [{"id": "l1", "log": {"message": "hello {{ inputs.k }}"}}],
        },
        echo=echoed.append,
    )
    assert echoed == ["hello 5"]
    entry = next(e for e in _log(res) if e.get("event") == "log")
    assert entry == {"event": "log", "step_id": "l1", "path": "l1", "message": "hello 5"}


def test_pause_headless_skipped(run_bot: RunBot) -> None:
    res = run_bot({"steps": [{"pause": "look"}]})
    assert res.steps[0].status == "ok"
    assert _messages(res) == ["pause skipped (headless)"]


def test_vars_section_and_inputs_in_templates(run_bot: RunBot) -> None:
    res = run_bot(
        {
            "inputs": {"who": {"type": "string"}},
            "vars": {"greeting": "hi {{ inputs.who }}", "n": 2},
            "steps": [{"log": {"message": "{{ greeting }}/{{ vars.n * 3 }}"}}],
        },
        inputs={"who": "bob"},
    )
    assert _messages(res) == ["hi bob/6"]


def test_input_error_raised_before_run_dir(run_bot: RunBot, tmp_path: Path) -> None:
    from rpawright.runner.inputs import InputError

    with pytest.raises(InputError, match="missing required input 'm'"):
        run_bot({"inputs": {"m": {"type": "string"}}, "steps": [{"log": {"message": "x"}}]})
    assert not (tmp_path / "runs").exists()
