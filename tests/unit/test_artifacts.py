from datetime import datetime
from pathlib import Path

import pytest

from rpawright.runner import artifacts
from rpawright.runner.artifacts import RunArtifacts


def test_same_second_runs_get_distinct_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return datetime(2026, 11, 2, 12, 0, 0, tzinfo=tz)

    monkeypatch.setattr(artifacts, "datetime", _Frozen)
    a = RunArtifacts(tmp_path, "bot")
    b = RunArtifacts(tmp_path, "bot")
    c = RunArtifacts(tmp_path, "bot")
    assert [a.dir.name, b.dir.name, c.dir.name] == [
        "20261102T120000Z",
        "20261102T120000Z-2",
        "20261102T120000Z-3",
    ]


@pytest.mark.parametrize("name", ["..", ".", "...", ".hidden", "x" * 300])
def test_safe_name_is_a_single_safe_component(name: str) -> None:
    s = artifacts.safe_name(name)
    assert s not in ("", ".", "..")
    assert not s.startswith(".")
    assert len(s) <= 100
    assert "/" not in s and "\\" not in s


def test_safe_name_values() -> None:
    assert artifacts.safe_name("..") == "bot"
    assert artifacts.safe_name(".") == "bot"
    assert artifacts.safe_name("...") == "bot"
    assert artifacts.safe_name(".hidden") == "hidden"
    assert len(artifacts.safe_name("x" * 300)) == 100


@pytest.mark.parametrize("name", ["..", ".", "...", ".hidden", "x" * 300])
def test_run_dir_stays_under_root_bot_dir(tmp_path: Path, name: str) -> None:
    root = tmp_path / "runs"
    run = RunArtifacts(root, name)
    assert run.dir.parent == root / artifacts.safe_name(name)
    assert run.dir.parent.parent == root
    assert run.dir.resolve().is_relative_to(root.resolve())
