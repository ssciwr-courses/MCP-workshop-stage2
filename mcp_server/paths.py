"""Filesystem sandboxing for the climate MCP server.

The processing pipeline (scripts/process_climate.py) trusts whatever paths
are in its config, because that config was normally hand-written by the
person running the CLI. Once a config can come from an agent, every path in
it is untrusted input, so this module is the single place that decides which
real filesystem locations a config is allowed to touch:

- input_csv must resolve inside data/
- every run's outputs are written to their own directory inside outputs/,
  and only the *filename* portion of the config's output_path fields is
  honoured, so a config cannot use '..' or an absolute path to write
  somewhere else on the host
"""

from __future__ import annotations

import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = (REPO_ROOT / "data").resolve()
OUTPUTS_ROOT = (REPO_ROOT / "outputs").resolve()


class PathSecurityError(ValueError):
    """Raised when a config-supplied path would escape its allowed root."""


def resolve_input_csv(raw_path: str) -> Path:
    """Resolve an input CSV path, constrained to live under data/."""
    candidate = Path(raw_path)
    resolved = (candidate if candidate.is_absolute() else (DATA_ROOT / candidate)).resolve()
    try:
        resolved.relative_to(DATA_ROOT)
    except ValueError:
        raise PathSecurityError(f"input_csv '{raw_path}' must resolve inside {DATA_ROOT}") from None
    if not resolved.is_file():
        raise PathSecurityError(f"input_csv '{raw_path}' does not exist under {DATA_ROOT}")
    return resolved


def output_filename(raw_path: str, *, label: str) -> str:
    """Reduce an output_path config value to a bare filename.

    Only the filename is used; any directory component the config supplied
    is discarded so the file always lands inside the run's own directory.
    """
    filename = Path(raw_path).name
    if not filename or filename in (".", ".."):
        raise PathSecurityError(f"{label} '{raw_path}' does not name a file")
    return filename


def new_run_dir() -> Path:
    """Create and return a fresh, unique directory under outputs/ for one run."""
    OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)
    run_dir = OUTPUTS_ROOT / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def new_data_csv_path(filename: str) -> Path:
    """Resolve a server-generated filename to a path under data/.

    For tools (like download_dwd_weather) that fetch data at the caller's
    request and save it for later use as input_csv. Only the filename portion
    is honoured, mirroring output_filename's guarantee -- even though callers
    here build the filename themselves rather than take one from a config,
    the same defense-in-depth applies: nothing written through this function
    can land outside DATA_ROOT.
    """
    filename = Path(filename).name
    if not filename or filename in (".", ".."):
        raise PathSecurityError(f"filename '{filename}' does not name a file")
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return DATA_ROOT / filename
