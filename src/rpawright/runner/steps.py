"""Step handlers: one function per action, keyed by YAML action name."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import FrameLocator, Page

from rpawright.runner.errors import AssertionFailed, LocatorNotFound, StepError
from rpawright.runner.locate import (
    Resolved,
    build_locator,
    describe,
    frame_scope,
    resolve_target,
)
from rpawright.workflow.models import (
    AssertStep,
    ClickStep,
    FillStep,
    GotoStep,
    PressBody,
    PressStep,
    Step,
    Target,
    WaitBody,
    WaitStep,
)


@dataclass
class StepContext:
    page: Page
    timeout_ms: int
    step_id: str
    locator_used: str | None = None


def _resolve(ctx: StepContext, targets: list[Target], frame: list[Target] | None) -> Resolved:
    resolved = resolve_target(
        ctx.page, targets, frame=frame, timeout_ms=ctx.timeout_ms, step_id=ctx.step_id
    )
    ctx.locator_used = describe(targets[resolved.index])
    return resolved


def _goto(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, GotoStep)
    try:
        ctx.page.goto(step.goto, timeout=ctx.timeout_ms)
    except PlaywrightError as e:
        raise StepError(ctx.step_id, f"goto {step.goto} failed: {e}") from e


def _click(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, ClickStep)
    _resolve(ctx, step.click.target, step.click.frame).locator.click(timeout=ctx.timeout_ms)


def _fill(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, FillStep)
    body = step.fill
    _resolve(ctx, body.target, body.frame).locator.fill(body.value, timeout=ctx.timeout_ms)


def _press(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, PressStep)
    body = step.press
    if isinstance(body, str):
        ctx.page.keyboard.press(body)
        return
    assert isinstance(body, PressBody)
    if body.target is None:
        ctx.page.keyboard.press(body.key)
        return
    loc = _resolve(ctx, body.target, body.frame).locator
    loc.focus(timeout=ctx.timeout_ms)
    ctx.page.keyboard.press(body.key)


def _any_visible(scope: Page | FrameLocator, targets: list[Target]) -> bool:
    """True if any match of any candidate is visible."""
    for t in targets:
        loc = build_locator(scope, t)
        if any(loc.nth(i).is_visible() for i in range(loc.count())):
            return True
    return False


def _wait_hidden(ctx: StepContext, targets: list[Target], frame: list[Target] | None) -> None:
    # Hidden means no match of any candidate is visible; a missing element or frame counts
    # as hidden.
    deadline = time.monotonic() + ctx.timeout_ms / 1000
    while True:
        try:
            scope: Page | FrameLocator = ctx.page
            if frame:
                # One pass, no waiting: a frame that is not there means nothing is visible.
                scope = frame_scope(
                    ctx.page,
                    frame,
                    deadline=time.monotonic() - 1,
                    poll_ms=0,
                    step_id=ctx.step_id,
                )
            visible = _any_visible(scope, targets)
        except LocatorNotFound:
            visible = False
        except PlaywrightError:
            visible = False  # a detached or invalid element counts as hidden
        if not visible:
            return
        if time.monotonic() >= deadline:
            raise StepError(
                ctx.step_id,
                f"still visible after {ctx.timeout_ms} ms: "
                + ", ".join(describe(t) for t in targets),
            )
        ctx.page.wait_for_timeout(250)


def _wait_url(ctx: StepContext, needle: str) -> str | None:
    """Poll until the page url contains ``needle``. Returns None on success, else the last url."""
    deadline = time.monotonic() + ctx.timeout_ms / 1000
    while needle not in ctx.page.url:
        if time.monotonic() >= deadline:
            return ctx.page.url
        ctx.page.wait_for_timeout(250)
    return None


def _wait(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, WaitStep)
    body = step.wait
    if isinstance(body, int):
        ctx.page.wait_for_timeout(body)
        return
    assert isinstance(body, WaitBody)
    if body.ms is not None:
        ctx.page.wait_for_timeout(body.ms)
    elif body.target is not None:
        if body.state == "visible":
            _resolve(ctx, body.target, body.frame)
        else:
            _wait_hidden(ctx, body.target, body.frame)
    else:
        assert body.url_contains is not None
        last_url = _wait_url(ctx, body.url_contains)
        if last_url is not None:
            raise StepError(
                ctx.step_id,
                f"url did not contain {body.url_contains!r} within {ctx.timeout_ms} ms; "
                f"actual url {last_url!r}",
            )


def _assert(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, AssertStep)
    body = step.assert_
    if body.url_contains is not None:
        last_url = _wait_url(ctx, body.url_contains)
        if last_url is not None:
            raise AssertionFailed(
                ctx.step_id,
                f"expected url containing {body.url_contains!r}, actual url {last_url!r}",
            )
    if body.target is None:
        return
    if body.visible is False:
        if body.text_contains is not None:
            raise StepError(ctx.step_id, "assert: text_contains requires a visible element")
        try:
            _wait_hidden(ctx, body.target, body.frame)
        except StepError as e:
            raise AssertionFailed(
                ctx.step_id,
                "expected hidden, actual visible: " + ", ".join(describe(t) for t in body.target),
            ) from e
        return
    resolved = _resolve(ctx, body.target, body.frame)
    loc = resolved.locator
    if body.text_contains is not None:
        deadline = time.monotonic() + ctx.timeout_ms / 1000
        while True:
            actual = loc.inner_text(timeout=ctx.timeout_ms)
            if body.text_contains in actual:
                break
            if time.monotonic() >= deadline:
                raise AssertionFailed(
                    ctx.step_id,
                    f"expected text containing {body.text_contains!r}, actual {actual!r}",
                )
            ctx.page.wait_for_timeout(250)
    if body.visible is not None:
        actual_visible = loc.is_visible()
        if actual_visible != body.visible:
            raise AssertionFailed(
                ctx.step_id, f"expected visible={body.visible}, actual visible={actual_visible}"
            )


HANDLERS: dict[str, Callable[[StepContext, Step], None]] = {
    "goto": _goto,
    "click": _click,
    "fill": _fill,
    "press": _press,
    "wait": _wait,
    "assert": _assert,
}
