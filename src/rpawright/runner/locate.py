"""Locator resolution: first candidate matching exactly one visible element wins."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import FrameLocator, Locator, Page

from rpawright.runner.errors import LocatorNotFound
from rpawright.workflow.models import Target


@dataclass
class Resolved:
    locator: Locator
    index: int


def describe(t: Target) -> str:
    """Render as ``<kind>=<value>``; role adds ``[name="..."]``; nth appends ``[nth=N]``."""
    kind = t.kind
    if kind == "role":
        text = f"role={t.role}"
        if t.name is not None:
            text += f'[name="{t.name}"]'
    else:
        text = f"{kind}={getattr(t, kind)}"
    if t.nth is not None:
        text += f"[nth={t.nth}]"
    return text


def build_locator(scope: Page | FrameLocator, t: Target) -> Locator:
    kind = t.kind
    if kind == "testid":
        assert t.testid is not None
        loc = scope.get_by_test_id(t.testid)
    elif kind == "role":
        assert t.role is not None
        # Playwright's `role` param is a Literal of ARIA roles; the YAML value is a free string.
        loc = scope.get_by_role(t.role, name=t.name, exact=t.exact)  # type: ignore[arg-type]
    elif kind == "label":
        assert t.label is not None
        loc = scope.get_by_label(t.label, exact=t.exact)
    elif kind == "text":
        assert t.text is not None
        loc = scope.get_by_text(t.text, exact=t.exact)
    elif kind == "css":
        assert t.css is not None
        loc = scope.locator(t.css)
    else:
        assert t.xpath is not None
        loc = scope.locator("xpath=" + t.xpath)
    if t.nth is not None:
        loc = loc.nth(t.nth)
    return loc


def poll_until[T](
    page: Page,
    check: Callable[[], T | None],
    *,
    timeout_ms: int,
    poll_ms: int = 250,
) -> T | None:
    """Call ``check`` until it returns non-None or ``timeout_ms`` passes (then None).

    ``check`` always runs at least once. Waits go through ``page.wait_for_timeout`` (never
    ``time.sleep``) so Playwright events such as downloads keep firing, and each wait is
    clamped to the time left so the deadline is not overshot.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        result = check()
        if result is not None:
            return result
        remaining_ms = (deadline - time.monotonic()) * 1000
        if remaining_ms <= 0:
            return None
        page.wait_for_timeout(min(poll_ms, remaining_ms))


def _poll(
    page: Page,
    scope: Page | FrameLocator,
    targets: list[Target],
    *,
    deadline: float,
    poll_ms: int,
    step_id: str,
    what: str,
) -> Resolved:
    tried: list[tuple[str, int]] = []

    def check() -> Resolved | None:
        tried.clear()
        for i, t in enumerate(targets):
            count = 0
            try:
                loc = build_locator(scope, t)
                count = loc.count()
                visible = count == 1 and loc.is_visible()
            except PlaywrightError:
                # Invalid selector, strict-mode race, closed target or navigation race:
                # treat as no match for this poll and keep polling.
                visible = False
            tried.append((describe(t), count))
            if visible:
                return Resolved(locator=loc, index=i)
        return None

    timeout_ms = max(0, math.ceil((deadline - time.monotonic()) * 1000))
    hit = poll_until(page, check, timeout_ms=timeout_ms, poll_ms=poll_ms)
    if hit is not None:
        return hit
    detail = ", ".join(f"{d} ({c} match{'' if c == 1 else 'es'})" for d, c in tried)
    raise LocatorNotFound(
        step_id, f"no {what} matched exactly one visible element: {detail}", tried
    )


def frame_scope(
    page: Page,
    frame: list[Target],
    *,
    deadline: float,
    poll_ms: int,
    step_id: str,
) -> FrameLocator:
    """Resolve the frame candidates to a FrameLocator; raises LocatorNotFound at the deadline."""
    hit = _poll(
        page,
        page,
        frame,
        deadline=deadline,
        poll_ms=poll_ms,
        step_id=step_id,
        what="frame candidate",
    )
    return hit.locator.frame_locator(":scope")


def resolve_target(
    page: Page,
    targets: list[Target],
    *,
    frame: list[Target] | None,
    timeout_ms: int,
    step_id: str,
    poll_ms: int = 250,
) -> Resolved:
    """Poll candidates in order until one matches exactly one visible element."""
    deadline = time.monotonic() + timeout_ms / 1000
    scope: Page | FrameLocator = page
    if frame:
        scope = frame_scope(page, frame, deadline=deadline, poll_ms=poll_ms, step_id=step_id)
    return _poll(
        page,
        scope,
        targets,
        deadline=deadline,
        poll_ms=poll_ms,
        step_id=step_id,
        what="target candidate",
    )
