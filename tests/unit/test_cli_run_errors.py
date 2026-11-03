"""CLI failure handling that must not need a real browser (no browser fixtures: no nesting)."""

from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError
from typer.testing import CliRunner

from rpawright.cli import app
from rpawright.runner import engine

BOT = 'version: 1\nname: t\nsteps:\n  - log: {message: "x"}\n'


def test_missing_chromium_is_one_clear_line_and_leaves_no_run_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeChromium:
        def launch(self, **kwargs: object) -> None:
            raise PlaywrightError(
                "BrowserType.launch: Executable doesn't exist at /x/chrome\n"
                "Looks like Playwright was just installed. Please run: playwright install"
            )

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self) -> "FakePlaywright":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(engine, "sync_playwright", lambda: FakePlaywright())
    bot = tmp_path / "bot.yaml"
    bot.write_text(BOT, encoding="utf-8")
    runs = tmp_path / "runs"
    result = CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(runs)])
    assert result.exit_code == 1
    assert result.stderr.strip() == (
        "error  Chromium is not installed. Run: uv run playwright install chromium"
    )
    assert "Traceback" not in result.output
    assert not runs.exists()


def test_other_launch_errors_are_not_masked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeChromium:
        def launch(self, **kwargs: object) -> None:
            raise PlaywrightError("some other launch failure")

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self) -> "FakePlaywright":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(engine, "sync_playwright", lambda: FakePlaywright())
    bot = tmp_path / "bot.yaml"
    bot.write_text(BOT, encoding="utf-8")
    result = CliRunner().invoke(app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code != 0
    assert isinstance(result.exception, PlaywrightError)
