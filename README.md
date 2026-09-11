# MCP Climate Example Repo

This repository contains a small, deterministic example that can be called through an MCP.

## Mock scientific purpose of the example

This is an example that uses mock climate data and aggregates and plots the data. Input: `data/mock_climate.csv` with `date, temperature_c, precipitation_mm, humidity_pct` values per day for one month. 
The output is (1) `outputs/climate_summary.csv` with `month, avg_temperature_c, total_precipitation_mm` for each month. The daily temperature values are aggregated using their mean, while the daily precipitation values are aggregated using their sum; (2) a plot of the data over time.

## Mock user workflow

The user workflow is the following:
1. User obtains `data` from (server, weather station)
2. User prepares the `config` file for the run
3. User executes the script using `data` and `config`
4. User verifies the data by visual inspection of the plot and the summary

This workflow currently requires the user to install the package (hurdle 1), write in a yaml file (hurdle 2), and provide relative paths (hurdle 3). It also requires the user to be in the correct relative directory when running the script (hurdle 4). These hurdles can be circumvented using the functionality through an agent.

Here, an MCP builds the foundation: It defines the API, executes the software, and takes/returns data. It does not explain the workflow or the observations in the data, but serves as the technical interface to the agent - the MCP server wraps the code into a new tool that the agent can call. The implementation is hidden behind a typed interface. Another advantage is portability: An MCP server works on any other MCP-compatible client, and can be available remotely. Using the MCP, the researchers only interact with the scientific workflow ("process climate data") and not the implementation.

## Relevant repo content

- `config/example.yaml`: input parameters for the processing run
- `data/mock_climate.csv`: mock climate time-series data
- `scripts/process_climate.py`: processing and plotting script
- `outputs/`: generated summary CSV and plot files
- `tests/`: unit tests for the processing/plotting script and the MCP server

### Relevant content for stage 1 of the MCP
- `mcp_server/`: MCP server wrapping the script (see [MCP server](#mcp-server) below).

## Data processing order in the script

The script does the following in the given order:
1. Parses the command-line arguments giving the relative position of the config file: `parse_args()` 
2. Reads the YAML config file: `load_config()`
3. Loads the mock climate CSV: `run_pipeline()` -> `pd.read_csv()`
4. Cleans and converts the climate data: `prepare_data()`
5. Aggregates the daily data to monthly and saves to `outputs/`: `build_monthly_summary()`
6. Creates and exports a plot of the data: `create_plot()`

## Missing data policy:

- The config takes an optional top-level missing_policy block.
- The four values and what each does: interpolate / zero_fill / drop / fail.
- Defaults: interpolate for temperature_c, zero_fill for precipitation_mm

## Installing and executing the script

The necessary dependencies can be installed into a Python environment using `pip` or `uv`:
```bash
pip install -r requirements.txt
```

The script is then executed using 
```bash
python scripts/process_climate.py --config config/example.yaml
```

## Expected outputs

The expected outputs are stored in the folder given in the config file, for the default values:
- `outputs/climate_summary.csv`
- `outputs/climate_plot.png`

## Unit tests

Unit tests require installing dev dependencies and can then be run via
```bash
pip install -r requirements-dev.txt
python -m pytest
```

## MCP server

`mcp_server/` wraps the pipeline as an MCP server (`mcp_server/server.py`), so an agent can call it as a tool. 

The MCP server then calls `process_climate.run_pipeline()` directly (no subprocess) and reuses `config/schema.json` for validation.

This provides the following tools to the agent:
- `get_config_schema` — the JSON Schema a config must satisfy (also exposed as the resource `climate://config-schema`)
- `list_sample_data` — CSV files available under `data/`, with their column names
- `validate_climate_config` — validate a config without running the pipeline
- `process_climate_data` — run the pipeline on an inline config; returns a text report (row count, monthly summary table, data_quality, policy and aggregation) plus the rendered plot image

### New user workflow

Using the tools provided through the MCP, the script no longer uses the path to a config file. Instead, the `config` choices are passed inline as json and validated against the stored schema.

This makes sure that user input errors are correct before running the pipeline, as well as it restricts the file system access by the MCP server. 

For security reasons, each path in the input is by default untrusted, and must resolve under certain directories in the file system: `input_csv` must resolve inside `data/`, and the outputs do not contain any paths anymore but only filenames, that resolve to a fresh directory in `outputs/`. This ensures that concurrent or repeated runs never collide or overwrite each other's results, and that a config cannot point anywhere else on the disk.

The workflow and agent steps taken are as follows:

1. The user states the intent and where the data is found:
> User: "For the data in the data/ folder, prepare a summary and a plot for me using the climate mcp."

2. The statement is read by the LLM, and the decision to use the climate_mcp tools was taken. The LLM then follows the server instructions given in `instructions`:
    a. Call to `get_config_schema()` and `list_sample_data()`
    b. The result is used to construct the config in the next step

3. The LLM emits the tool call for `process_climate_data` through the harness to the MCP, using the MCP over JSON-RPC 2.0 protocol. The harness already did a handshake with the MCP at session init / upon MCP connection. Through the handshake, the harness initialized the server and obtained the tool list (`@mcp.tool()` decorators) and their docstrings for the LLM.
In the tool call, the LLM emits the built config `json` based on the information obtained in 1. and 2., providing a structured output. The harness converts the call into the proper request:
```
{"jsonrpc":"2.0","id":N,"method":"tools/call",
 "params":{"name":"process_climate_data","arguments":{"config":{...}}}}
 ```
 4. The MCP server then reads it, routes to the correct Python function `process_climate_data()` and runs synchronously through the following steps:
    - validate the schema: `_schema_errors()`
    - builds the run config dictionary: `run_config`
    - creates a new directory under `outputs` not to overwrite prior data: `paths.new_run_dir()`
    - then starts the processing pipeline (same as before): `pc.run_pipeline()`
    - the output is noted: `result` is a dict captured from the pipeline, containing run information  

    The server then provides the tool call results back to the harness as JSON-RPC.

5. The harness converts the result back to actual PNG bytes and text, and hands it to the LLM. The LLM reports the result to the user.


### Running the server

To test out the server, you can start it locally. Either you can run it through the console, after having installed all the requirements into your environment, using
```bash
pip install -r requirements.txt   # now includes mcp[cli]
python -m mcp_server.server       # stdio transport
```
or, after `pip install -e .`, you may run it via the console script `climate-mcp-server`.

To start using the MCP with your agent, you need to register it with the agent. Most agents will start the server for you, so you do not need to run the above command.

#### Claude Code

To register the MCP with Claude Code, use:
```bash
claude mcp add climate-example -- python -m mcp_server.server
```
in your Claude chat. This will create/add to the  `.claude.json` file in your home directory. Restart Claude to then load it into the session.

#### VSCode and GitHub Copilot

To register the MCP with VSCode and GitHub Copilot, you need to place a `mcp.json` file with the following content in the `.vscode` directory:
```
{
  "servers": {
    "climate-mcp-local": {
      "type": "stdio",
      "command": "<path-to-your-environment>/climate-mcp-server",
      "args": []
    }
  }
}
```
Here, you can then also start and stop the MCP server using the little "play" button as shown in the json file.

#### Pi coding agent

To register the MCP with the Pi coding agent, add it to `mcp.json` (global: `~/.pi/agent/mcp.json`, or project-local `.pi/mcp.json`):
```json
{
  "mcpServers": {
    "climate-example": {
      "command": "<path-to-your-environment>/climate-mcp-server",
      "args": []
    }
  }
}
```
Pi's tools are then exposed with the prefix `mcp_climate-example_<tool-name>`.

#### Vibe Mistral coding agent

Vibe uses a TOML config file (`config.toml`). Add a `[[mcp_servers]]` table:
```toml
[[mcp_servers]]
name = "climate-example"
transport = "stdio"
command = "<path-to-your-environment>/climate-mcp-server"
args = []
```
Vibe exposes the tools under the pattern `climate-example_<tool-name>`.

#### Codex

To register the MCP with the Codex CLI, use:
```bash
codex mcp add climate-example -- python -m mcp_server.server
```
This writes to `~/.codex/config.toml` (or `.codex/config.toml` for a project-scoped, trusted-only registration); equivalently, you can add the entry there directly:
```toml
[mcp_servers.climate-example]
command = "<path-to-your-environment>/climate-mcp-server"
args = []
```

### Testing

`tests/test_mcp_server.py` calls the tool functions directly (they stay plain, callable Python functions under the `@mcp.tool()` decorator) and covers the sandboxing rules above, including path-traversal attempts in `input_csv` and `output_path`. Run it with the rest of the suite via `python -m pytest`.

## Skill

`.claude/skills/climate-missing-data/SKILL.md` supplies the judgment the MCP deliberately does not encode — which missing_policy to choose, and what the result means once it comes back.

- at startup the harness reads only the name and description
- when a request matches the description, the whole SKILL.md is loaded
- referenced files load later still, only if the workflow reaches them

### Workflow with the skill

1. User states intent, saying nothing about data quality: "Process missing_climate2.csv and give me the monthly rainfall total."
2. The description matches; the harness loads the full SKILL.md.
3. Before the call: the skill's rules decide missing_policy: drop rather than the default zero_fill, and that goes into the tool-call arguments.
4. The call: identical to the MCP workflow already documented — JSON-RPC, schema validation, fresh run directory, run_pipeline(), result returned with data_quality.
5. After the call: the skill's rules turn coverage: 92.9% into "a lower bound, not a measurement", and decide to ask whether the figure is exploratory or headed for a report.

The skill wraps the tool call on both sides; it changes the arguments going in and the claim coming out, and changes nothing in between.

## Security

Once a config can come from an agent rather than a human hand-writing YAML, every path and value in it is untrusted input. The server treats it that way:

- **Path sandboxing** (`mcp_server/paths.py`): `input_csv` is resolved and checked with `relative_to(DATA_ROOT)`, so any absolute path or `../` sequence that would escape `data/` is rejected before the file is opened. Output paths (`plot.output_path`, `summary.output_path`) are reduced to their bare filename (`Path(raw_path).name`) — any directory component the config supplied, including `..`, is simply discarded, not just checked, so there is no path left to escape with.
- **Per-run isolation** (`paths.new_run_dir()`): every call to `process_climate_data` writes into a fresh, UUID-named directory under `outputs/`, never into a caller-chosen location. Concurrent or repeated runs can't collide or overwrite each other's results, and a config cannot direct output anywhere else on the host.
- **Schema validation before execution** (`_schema_errors()` in `mcp_server/server.py`, reusing `config/schema.json`): the config is validated against the JSON Schema and rejected with the specific violations before the pipeline ever runs, rather than failing partway through or on bad assumptions.
- **No subprocess / no shell**: the MCP server calls `process_climate.run_pipeline()` in-process as a plain Python function, not via `subprocess`/shell string-building. There's no command-line assembly for a malicious value to break out of.
- **Config is inline JSON, not a file path**: the agent passes the config as structured data in the tool call, never a path to a config file on disk. This also means the agent — and by extension the LLM — never needs or gets to know the server's filesystem layout beyond what `list_sample_data`/`get_config_schema` deliberately expose.

What this setup does *not* provide: authentication/authorization on the tool calls themselves, rate limiting, or resource limits (CPU/memory/time) on a pipeline run. That's acceptable for a local, single-user, stdio-transport example where the trust boundary is "whoever can spawn the server process" (i.e. you, or your agent running as you) — see the deployment notes below for what changes if that boundary moves.

`tests/test_mcp_server.py` exercises the sandboxing directly, including path-traversal attempts against both `input_csv` and `output_path`.

## MCP server deployment

In this repo the server only runs as a **local stdio subprocess**: `mcp.run()` in `mcp_server/server.py` uses the default `"stdio"` transport, and `main()` takes no arguments to change that. The underlying `mcp` library also ships SSE and streamable-HTTP transports (`run_sse_async`, `run_streamable_http_async`), but this example does not wire them up — there is no network listener, no port, and nothing to expose accidentally.

Consequences of the stdio model:
- The server process is spawned and owned by whichever client starts it (Claude Code, VSCode, Pi, Vibe, Codex — see the registration snippets above), lives only as long as that client keeps it running, and is reachable only by that one client over its own stdin/stdout pipe. There is no separate "deploy the server somewhere" step for local use — registering it with a client *is* deployment.
- Because it's a subprocess of a trusted parent, not a network service, there is no built-in authentication layer — the trust boundary is entirely "who can launch this process," per the security notes above.
- Filesystem access is still bounded by `mcp_server/paths.py` regardless of who launches it, so a misbehaving or compromised client can't use the server to reach outside `data/`/`outputs/`, but it *can* run the pipeline as fast/often as it likes — there's no throttling.

If you wanted to run this server centrally instead (e.g. one server shared by multiple users or agents over a network), that would mean:
- switching to the streamable-HTTP or SSE transport instead of stdio,
- adding an authentication/authorization layer in front of it (the library's transports don't provide one out of the box),
- putting it behind TLS (a reverse proxy is the usual choice) since MCP itself doesn't encrypt the transport,
- adding resource/rate limits per caller, since `DATA_ROOT`/`OUTPUTS_ROOT` sandboxing only constrains *where* files land, not *how much* processing a caller can trigger,
- and likely running each request's pipeline in some isolated worker (process/container) rather than in the long-lived server process, so one bad or huge input can't stall other callers.

None of that is implemented here as it is out of scope for this basic example, but it represents the gap between "runs on my machine via stdio" and "runs as a shared service."
