"""Run artifacts: per-run directory, JSONL step log and failure screenshots."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page


def safe_name(s: str) -> str:
    """Make ``s`` safe as a path component."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-") or "bot"


class RunArtifacts:
    """Owns ``root/<bot>/<UTC timestamp>/`` for one run."""

    def __init__(self, root: Path, bot_name: str) -> None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        parent = root / safe_name(bot_name)
        parent.mkdir(parents=True, exist_ok=True)
        for n in range(1, 101):
            candidate = parent / (stamp if n == 1 else f"{stamp}-{n}")
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            self.dir = candidate
            return
        raise FileExistsError(f"could not create a unique run directory under {parent}")

    def log(self, record: dict[str, object]) -> None:
        with (self.dir / "log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def screenshot(self, page: Page, step_id: str) -> Path:
        path = self.dir / f"fail-{safe_name(step_id)}.png"
        page.screenshot(path=str(path))
        return path
