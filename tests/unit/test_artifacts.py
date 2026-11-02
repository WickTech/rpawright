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
