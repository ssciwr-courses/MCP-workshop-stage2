# MCP server implementation plan

Status: **stages 1-5 implemented and verified**; not yet committed. This
document tracks the plan for wrapping `scripts/process_climate.py` as an MCP
server and how far that plan has been carried out, so it can be picked back
up without re-deriving the design.

## Goal

Remove the four hurdles named in the README's "Mock user workflow" section
(install the package, hand-write YAML, get relative paths right, run from
the correct directory) by exposing the pipeline as MCP tools instead of a
CLI script. The pipeline itself (`process_climate.py`) is already a clean
seam for this: `run_pipeline(config: dict, project_root: Path)` is a pure
function with no CLI/file-path assumptions baked in, so it's called
directly — no subprocess, no refactor of the science code.

## Key design decisions

- **SDK**: official `mcp` Python SDK. The `mcp-example` conda env resolved
  `mcp` 2.1.1, a recent major version where `FastMCP` was renamed to
  `MCPServer` (`from mcp.server.mcpserver import MCPServer, Image`) — a
  different API from the more commonly documented 1.x `FastMCP`. Built and
  verified against the actual installed API, and pinned
  `mcp[cli]>=2.1.1,<3` in `requirements.txt` / `pyproject.toml` so the
  example doesn't silently break on a future v3 rename.
- **Transport**: stdio (`mcp.run()` default) — matches local Claude
  Code/Desktop usage; no HTTP/SSE server needed for this example.
- **Config is passed inline as JSON**, not as a path to a YAML file the
  caller writes and places correctly. This is what actually removes hurdles
  2-4: the agent gets the shape from `get_config_schema`, valid
  `input_csv` values from `list_sample_data`, and can pre-check a draft with
  `validate_climate_config` before running it.
- **Every path in a config is untrusted input**, resolved by the server
  (`mcp_server/paths.py`), not passed to the pipeline verbatim:
  - `input_csv` must resolve inside `data/` (rejects `..` and absolute
    paths escaping it, and must exist)
  - the `output_path` fields under `plot`/`summary` are reduced to their
    **filename only** — any directory component is discarded
  - each call to `process_climate_data` gets its own fresh
    `outputs/<uuid>/` directory, so concurrent/repeated runs never collide
    or overwrite each other's results, and a config cannot choose a
    filesystem location outside that sandbox
- **Validation is separate from execution**: `process_climate_data`
  re-validates against `config/schema.json` before touching the filesystem
  (the schema check isn't inside `run_pipeline` itself), and
  `validate_climate_config` exposes the same check standalone so an agent
  can self-correct without a real run.
- **Response shape**: a tool call shouldn't force the caller to open
  generated files separately, so `process_climate_data` returns a text
  report (row count, the monthly summary table inline) followed by the
  rendered plot as an embedded `Image` — not just a path.

## File layout

```
mcp_server/
  __init__.py
  paths.py     # sandboxing: resolve_input_csv, output_filename, new_run_dir
  pipeline.py  # sys.path shim to import scripts/process_climate.py as `pc`
  server.py    # MCPServer instance, tool/resource definitions, main()
pyproject.toml # packaging + `climate-mcp-server` console script entry point
tests/test_mcp_server.py
```

## Tool surface

| Tool | Purpose |
|---|---|
| `get_config_schema` | Returns `config/schema.json` (also exposed as resource `climate://config-schema`). |
| `list_sample_data` | Lists CSVs under `data/` with their columns. |
| `validate_climate_config` | Schema-validates a config dict without running anything; returns `{valid, errors}`. |
| `process_climate_data` | Validates, sandboxes paths, runs `run_pipeline()` in a fresh run directory, returns report text + plot image. |

## Build order and status

1. ✅ `pyproject.toml` + `mcp` dependency, server skeleton with
   `get_config_schema` only — verified it lists via `mcp.list_tools()`.
2. ✅ `list_sample_data`, `validate_climate_config` — read-only tools.
3. ✅ `process_climate_data` with sandboxing + run-isolated outputs.
4. ✅ Image/summary embedding in the tool response.
5. ✅ Tests (`tests/test_mcp_server.py`, 8 tests: schema, sample listing,
   validation pass/fail, a real pipeline run, run-isolation between two
   calls, and 3 path-escape cases) + README section + no CI changes needed
   (`requirements-dev.txt` already pulls `requirements.txt`, which now
   includes `mcp[cli]`).

Manually verified, beyond the automated tests:
- `mcp.list_tools()` / `list_resources()` show all 4 tools + the schema
  resource
- a real `process_climate_data` call end-to-end (31 rows → summary + PNG)
- path-traversal attempts (`../requirements.txt`, `/etc/passwd`,
  `../../evil.png`) are blocked or defanged to a bare filename inside the
  sandboxed run dir
- both `python -m mcp_server.server` and the `climate-mcp-server` console
  script (after `pip install -e .`) start cleanly over stdio

## Not done / possible next steps

- Not committed to git yet.
- No CI step exercises the packaged console script or a real stdio
  handshake (tests call the tool functions directly, which is sufficient
  for unit coverage but doesn't cover the protocol layer).
- No example `claude_desktop_config.json` / `.mcp.json` file committed —
  README shows the `claude mcp add` command instead.
- `process_climate_data` requires a fully inline config (by explicit
  choice — see prior conversation); an "override a base config" mode was
  considered and deliberately deferred.
- Outputs accumulate under `outputs/<uuid>/` with no cleanup/TTL — fine for
  a workshop example, would need attention for long-running deployments.
