"""MCP server exposing the mock climate pipeline (scripts/process_climate.py) as tools.

Tools:
  - get_config_schema      -- the JSON Schema a config must satisfy
  - list_sample_data       -- CSVs available under data/, with their columns
  - validate_climate_config -- validate a config without running the pipeline
  - process_climate_data   -- run the pipeline on an inline config

Design notes (see mcp_server/paths.py for the security rationale):
  - configs are passed inline as JSON, not as a path to a YAML file on disk,
    so the caller never has to know the server's filesystem layout
  - input_csv is resolved against data/; output_path values are treated as
    filenames only, and every run gets its own directory under outputs/
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema
import pandas as pd
from mcp.server.mcpserver import Image, MCPServer

from mcp_server import paths
from mcp_server.pipeline import pc

mcp = MCPServer(
    "climate-example",
    instructions=(
        "Tools for the mock climate processing pipeline: aggregating daily "
        "temperature/precipitation data to monthly summaries and a plot. "
        "Call get_config_schema first to see the required config shape, and "
        "list_sample_data to see which input_csv values are available. The "
        "optional missing_policy block chooses what happens to gaps in the "
        "data; the result reports coverage and the longest gap per metric, so "
        "check it before reporting any total as if it were complete."
    ),
)


def _schema_errors(config: dict[str, Any]) -> list[str]:
    """Validate config against config/schema.json, returning all violations."""
    validator = jsonschema.Draft7Validator(pc.load_schema())
    return [
        f"{'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
        for error in validator.iter_errors(config)
    ]


@mcp.resource("climate://config-schema")
@mcp.tool()
def get_config_schema() -> dict[str, Any]:
    """Return the JSON Schema a climate processing config must satisfy.

    Call this before process_climate_data to see the required and optional
    fields: input_csv, date_column, metrics, rolling_window_days, plot, summary.
    """
    return pc.load_schema()


@mcp.tool()
def list_sample_data() -> list[dict[str, Any]]:
    """List CSV files available under data/, with their column names.

    Use one of the returned "filename" values as input_csv in a config
    passed to process_climate_data.
    """
    entries = []
    for csv_path in sorted(paths.DATA_ROOT.glob("*.csv")):
        try:
            columns = list(pd.read_csv(csv_path, nrows=0).columns)
        except (pd.errors.ParserError, OSError, UnicodeDecodeError) as exc:
            columns = [f"<unreadable: {exc}>"]
        entries.append({"filename": csv_path.name, "columns": columns})
    return entries


@mcp.tool()
def validate_climate_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate a climate processing config against the schema, without running it.

    Returns {"valid": true} or {"valid": false, "errors": [...]}.
    """
    errors = _schema_errors(config)
    return {"valid": not errors, "errors": errors}


@mcp.tool()
def process_climate_data(config: dict[str, Any]) -> list[str | Image]:
    """Run the climate processing pipeline on an inline config and return the results.

    config must satisfy the schema returned by get_config_schema. `input_csv`
    is resolved against the server's data/ directory (see list_sample_data
    for available files); the `output_path` fields under `plot` and `summary`
    are treated as filenames only -- every run writes to its own directory,
    so a config cannot choose where on disk anything is written.

    `missing_policy` is optional: omit it and each metric uses the pipeline's
    default (interpolate for temperature_c, zero_fill for precipitation_mm).
    Set it per metric to interpolate, zero_fill, drop or fail. The right choice
    depends on the question being asked, not on the data alone: temperature is
    averaged over the month, so an estimated day washes out, while precipitation
    is summed, so a zero-filled day lowers the total permanently.

    Returns a text report (row count, per-metric data quality, monthly summary
    table) followed by the rendered plot image. The data-quality section gives
    the missing count, coverage and longest consecutive gap for each metric, so
    the effect of the chosen policy is visible in the result.
    """
    schema_errors = _schema_errors(config)
    if schema_errors:
        raise ValueError("Invalid config:\n" + "\n".join(schema_errors))

    run_config = dict(config)
    run_config["input_csv"] = str(paths.resolve_input_csv(config["input_csv"]))
    run_config["plot"] = dict(config["plot"])
    run_config["plot"]["output_path"] = paths.output_filename(
        config["plot"]["output_path"], label="plot.output_path"
    )
    run_config["summary"] = dict(config["summary"])
    run_config["summary"]["output_path"] = paths.output_filename(
        config["summary"]["output_path"], label="summary.output_path"
    )

    run_dir = paths.new_run_dir()
    result = pc.run_pipeline(run_config, project_root=run_dir)

    summary_path = Path(result["summary_path"])
    plot_path = Path(result["plot_path"])
    summary_preview = summary_path.read_text(encoding="utf-8")

    quality = result["data_quality"]
    quality_lines = "\n".join(
        f"  {name}: column={info['column']}, aggregation={info['aggregation']}, "
        f"policy={info['policy']}, missing={info['missing']}, "
        f"coverage={info['coverage']:.1%}, longest_gap={info['longest_gap']}"
        for name, info in quality["metrics"].items()
    )

    report = (
        f"Processed {result['rows_processed']} rows from "
        f"{Path(config['input_csv']).name} (run {run_dir.name}).\n\n"
        f"Data quality ({quality['rows_read']} rows read):\n{quality_lines}\n\n"
        f"Monthly summary ({summary_path.name}):\n{summary_preview}"
    )

    return [report, Image(path=str(plot_path), format="png")]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
