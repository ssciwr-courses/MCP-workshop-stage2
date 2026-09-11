"""Import shim for scripts/process_climate.py.

scripts/ is a standalone script directory, not an installable package, so it
is imported the same way tests/conftest.py already does: by adding it to
sys.path. Kept in one place so every server module imports the pipeline the
same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import process_climate as pc  # noqa: E402  (path must be set up first)

__all__ = ["pc"]
