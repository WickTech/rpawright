import pytest
from playwright.sync_api import Page

from rpawright.runner.errors import AssertionFailed, LocatorNotFound, StepError
from rpawright.runner.steps import HANDLERS, StepContext
from rpawright.workflow.models import Workflow


def run_step(page: Page, step: dict[str, object], timeout_ms: int = 500) -> StepContext:
    wf = Workflow.model_validate({"version": 1, "name": "t", "steps": [step]})
    s = wf.steps[0]
    assert s.id is not None
    ctx = StepContext(page=page, timeout_ms=timeout_ms, step_id=s.id)
    action = s.id.split("-")[0]
    HANDLERS[action](ctx, s)
    return ctx


def test_wait_ms_and_url(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/login.html")
    run_step(page, {"wait": 10})
    run_step(page, {"wait": {"ms": 10}})
    run_step(page, {"wait": {"url_contains": "login"}})
    with pytest.raises(StepError, match="url did not contain"):
        run_step(page, {"wait": {"url_contains": "nope"}}, timeout_ms=200)


def test_wait_target_visible_and_hidden(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/hidden.html")
    ctx = run_step(page, {"wait": {"target": [{"testid": "shown"}]}})
    assert ctx.locator_used == "testid=shown"
    run_step(page, {"wait": {"target": [{"css": "#hidden"}], "state": "hidden"}})
    run_step(page, {"wait": {"target": [{"css": "#absent"}], "state": "hidden"}})
    with pytest.raises(StepError, match="still visible"):
        run_step(
            page, {"wait": {"target": [{"testid": "shown"}], "state": "hidden"}}, timeout_ms=300
        )
    with pytest.raises(LocatorNotFound):
        run_step(page, {"wait": {"target": [{"css": "#hidden"}]}}, timeout_ms=300)


def test_press_with_and_without_target(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/login.html")
    ctx = run_step(page, {"press": "Tab"})
    assert ctx.locator_used is None
    ctx = run_step(page, {"press": {"key": "a", "target": [{"css": "#email"}]}})
    assert ctx.locator_used == "css=#email"
    assert page.input_value("#email") == "a"
    run_step(page, {"press": {"key": "b"}})


def test_assert_failures(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/login.html")
    with pytest.raises(AssertionFailed, match="actual url"):
        run_step(page, {"assert": {"url_contains": "dashboard"}})
    with pytest.raises(AssertionFailed, match="actual"):
        run_step(
            page,
            {"assert": {"target": [{"css": "#email"}], "text_contains": "zzz"}},
        )
    with pytest.raises(AssertionFailed, match="visible"):
        run_step(page, {"assert": {"target": [{"css": "#email"}], "visible": False}})
    run_step(page, {"assert": {"target": [{"css": "#email"}], "visible": True}})


def test_goto_failure_is_step_error(page: Page) -> None:
    with pytest.raises(StepError, match="goto"):
        run_step(page, {"goto": "http://127.0.0.1:9/"}, timeout_ms=1000)
