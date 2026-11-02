import time

import pytest

from rpawright.runner.errors import LocatorNotFound
from rpawright.runner.locate import resolve_target
from rpawright.workflow.models import Target

T = Target.model_validate


def test_first_unique_candidate_wins(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/login.html")
    r = resolve_target(
        page,
        [T({"css": "#email"}), T({"label": "Email"})],
        frame=None,
        timeout_ms=2000,
        step_id="s",
    )
    assert r.index == 0


def test_falls_back_when_first_breaks(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/login_v2.html")
    r = resolve_target(
        page,
        [T({"css": "#email"}), T({"role": "textbox", "name": "Email"})],
        frame=None,
        timeout_ms=2000,
        step_id="s",
    )
    assert r.index == 1


def test_ambiguous_candidate_never_chosen(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/ambiguous.html")
    r = resolve_target(
        page,
        [T({"text": "Save"}), T({"testid": "save-main"})],
        frame=None,
        timeout_ms=2000,
        step_id="s",
    )
    assert r.index == 1


def test_all_fail_lists_counts(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/ambiguous.html")
    with pytest.raises(LocatorNotFound) as e:
        resolve_target(
            page,
            [T({"text": "Save"}), T({"css": "#nope"})],
            frame=None,
            timeout_ms=600,
            step_id="s",
        )
    assert [c for _, c in e.value.tried] == [3, 0]
    assert [d for d, _ in e.value.tried] == ["text=Save", "css=#nope"]
    assert e.value.step_id == "s"


def test_late_element_found_and_missing_first_does_not_block(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/late.html")
    start = time.monotonic()
    r = resolve_target(
        page,
        [T({"css": "#never"}), T({"role": "button", "name": "Ready"})],
        frame=None,
        timeout_ms=5000,
        step_id="s",
    )
    assert r.index == 1 and time.monotonic() - start < 3.0


def test_frame_scope(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/frame.html")
    r = resolve_target(
        page,
        [T({"label": "Password"})],
        frame=[T({"css": "iframe[title=Login]"})],
        timeout_ms=3000,
        step_id="s",
    )
    assert r.locator.count() == 1


def test_frame_not_found_raises(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/frame.html")
    with pytest.raises(LocatorNotFound):
        resolve_target(
            page,
            [T({"label": "Password"})],
            frame=[T({"css": "iframe#nope"})],
            timeout_ms=400,
            step_id="s",
        )


def test_erroring_candidate_falls_through(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/login.html")
    r = resolve_target(
        page,
        [T({"css": "::::"}), T({"xpath": "//*["}), T({"css": "#email"})],
        frame=None,
        timeout_ms=2000,
        step_id="s",
    )
    assert r.index == 2


def test_only_erroring_candidate_raises_locator_not_found(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/login.html")
    with pytest.raises(LocatorNotFound) as e:
        resolve_target(page, [T({"css": "::::"})], frame=None, timeout_ms=400, step_id="s")
    assert [c for _, c in e.value.tried] == [0]


def test_hidden_element_skipped(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/hidden.html")
    r = resolve_target(
        page,
        [T({"css": "#hidden"}), T({"role": "button", "name": "Hidden"}), T({"testid": "shown"})],
        frame=None,
        timeout_ms=2000,
        step_id="s",
    )
    assert r.index == 2


def test_only_hidden_element_raises(page, site_url) -> None:  # type: ignore[no-untyped-def]
    page.goto(f"{site_url}/hidden.html")
    with pytest.raises(LocatorNotFound) as e:
        resolve_target(page, [T({"css": "#hidden"})], frame=None, timeout_ms=400, step_id="s")
    assert e.value.tried == [("css=#hidden", 1)]
