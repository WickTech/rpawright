"""End-to-end: the demo-inputs bot runs through the CLI against the local fixture site."""

from pathlib import Path

from typer.testing import CliRunner

from rpawright.cli import app

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "bots" / "demo-inputs.yaml"


def _run(tmp_path: Path, site_url: str, *extra: str) -> str:
    src = EXAMPLE.read_text(encoding="utf-8")
    old_url = "http://127.0.0.1:8765/login.html"
    assert old_url in src
    bot = tmp_path / "bot.yaml"
    bot.write_text(src.replace(old_url, f"{site_url}/login.html"), encoding="utf-8")
    result = CliRunner().invoke(
        app, ["run", str(bot), "--runs-dir", str(tmp_path / "runs"), *extra]
    )
    assert result.exit_code == 0, result.output
    return result.output


def test_demo_inputs_uses_default(tmp_path: Path, site_url: str) -> None:
    out = _run(tmp_path, site_url)
    assert "Login finished for me@example.com (done=yes)" in out


def test_demo_inputs_input_flag_overrides_default(tmp_path: Path, site_url: str) -> None:
    out = _run(tmp_path, site_url, "--input", "email=you@example.com")
    assert "Login finished for you@example.com (done=yes)" in out
    assert "me@example.com" not in out
