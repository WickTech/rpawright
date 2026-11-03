"""Shared fixtures: a local fixture-site server and a headless Chromium page."""

import functools
import threading
from collections.abc import Callable, Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

from rpawright.runner.engine import RunResult, run_workflow
from rpawright.workflow.models import Workflow

SITE_DIR = Path(__file__).parent / "fixtures" / "site"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture(scope="session")
def site_url() -> Iterator[str]:
    handler = functools.partial(_QuietHandler, directory=str(SITE_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


# Module scope: sync_playwright() cannot nest, so run_workflow tests (which start their own)
# must not run while a session-wide Playwright is still open.
@pytest.fixture(scope="module")
def _browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(_browser: Browser) -> Iterator[Page]:
    context = _browser.new_context()
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


@pytest.fixture
def run_bot(_browser: Browser, tmp_path: Path) -> Callable[..., RunResult]:
    """Run a bot given as a dict on the shared browser; extra kwargs go to run_workflow."""

    def _run(bot: dict[str, Any], **kwargs: Any) -> RunResult:
        wf = Workflow.model_validate({"version": 1, "name": "t", **bot})
        return run_workflow(
            wf, runs_root=tmp_path / "runs", browser=_browser, workspace=tmp_path, **kwargs
        )

    return _run
