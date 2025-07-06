from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on sys.path for imports
SRC_PATH = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_PATH))
