"""Step handlers: one function per action, keyed by YAML action name."""

import time
from collections.abc import Callable
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import FrameLocator, Page

from rpawright.runner.context import StepContext
from rpawright.runner.errors import AssertionFailed, LocatorNotFound, StepError
from rpawright.runner.locate import build_locator, describe, frame_scope, poll_until
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


def _goto(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, GotoStep)
    try:
        ctx.page.goto(step.goto, timeout=ctx.timeout_ms)
    except PlaywrightError as e:
        raise StepError(ctx.step_id, f"goto {step.goto} failed: {e}") from e


def _click(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, ClickStep)
    ctx.resolve(step.click.target, step.click.frame).locator.click(timeout=ctx.timeout_ms)


def _fill(ctx: StepContext, step: Step) -> None:
    assert isinstance(step, FillStep)
    body = step.fill
    ctx.resolve(body.target, body.frame).locator.fill(body.value, timeout=ctx.timeout_ms)


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
    loc = ctx.resolve(body.target, body.frame).locator
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
    def check() -> bool | None:
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
        return None if visible else True

    if poll_until(ctx.page, check, timeout_ms=ctx.timeout_ms) is None:
        raise StepError(
            ctx.step_id,
            f"still visible after {ctx.timeout_ms} ms: " + ", ".join(describe(t) for t in targets),
        )


def _wait_url(ctx: StepContext, needle: str) -> str | None:
    """Poll until the page url contains ``needle``. Returns None on success, else the last url."""
    hit = poll_until(
        ctx.page, lambda: True if needle in ctx.page.url else None, timeout_ms=ctx.timeout_ms
    )
    return None if hit else ctx.page.url


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
            ctx.resolve(body.target, body.frame)
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
    resolved = ctx.resolve(body.target, body.frame)
    loc = resolved.locator
    if body.text_contains is not None:
        needle = body.text_contains
        last = {"actual": ""}

        def text_matches() -> bool | None:
            last["actual"] = loc.inner_text(timeout=ctx.timeout_ms)
            return True if needle in last["actual"] else None

        if poll_until(ctx.page, text_matches, timeout_ms=ctx.timeout_ms) is None:
            raise AssertionFailed(
                ctx.step_id, f"expected text containing {needle!r}, actual {last['actual']!r}"
            )
    if body.visible is not None:
        actual_visible = loc.is_visible()
        if actual_visible != body.visible:
            raise AssertionFailed(
                ctx.step_id, f"expected visible={body.visible}, actual visible={actual_visible}"
            )


M1_HANDLERS: dict[str, Callable[[StepContext, Step], None]] = {
    "goto": _goto,
    "click": _click,
    "fill": _fill,
    "press": _press,
    "wait": _wait,
    "assert": _assert,
}

__all__ = ["M1_HANDLERS", "StepContext"]


def __getattr__(name: str) -> Any:
    # Lazy so handlers.py (which imports M1_HANDLERS from here) causes no import cycle.
    if name == "HANDLERS":
        from rpawright.runner.handlers import HANDLERS

        return HANDLERS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
