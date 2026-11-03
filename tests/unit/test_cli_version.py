import subprocess
import sys

from typer.testing import CliRunner

from rpawright import __version__
from rpawright.cli import app


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_light_commands_do_not_import_playwright() -> None:
    code = "import sys; import rpawright.cli; assert 'playwright' not in sys.modules"
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
