from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

# Ensure src/ is on sys.path for imports
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_PATH))


@pytest.fixture(autouse=True)
def _mock_container_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: "/usr/bin/container" if cmd == "container" else None,
    )
