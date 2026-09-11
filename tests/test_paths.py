"""Tests for MCP path sandboxing."""

import pytest

from mcp_server import paths
from mcp_server.paths import PathSecurityError


@pytest.mark.parametrize(
    "raw_output_path",
    ["..", ".", "foo/.."],
    ids=["dotdot", "dot", "nested-dotdot"],
)
def test_output_filename_rejects_dot_names(raw_output_path):
    with pytest.raises(PathSecurityError):
        paths.output_filename(raw_output_path, label="plot.output_path")
