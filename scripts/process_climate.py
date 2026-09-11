from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import yaml
from jsonschema import ValidationError, validate

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "config" / "schema.json"


def load_schema(schema_path: Path = SCHEMA_PATH) -> dict[str, Any]:
    with schema_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    try:
        validate(instance=config, schema=load_schema())
    except ValidationError as exc:
        raise ValueError(f"Invalid config at {config_path}: {exc.message}") from exc

    return config


def resolve_path(base_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else (base_dir / path).resolve()


MISSING_POLICIES = ("interpolate", "zero_fill", "drop", "fail")

METRIC_AGGREGATIONS = {"temperature_c": "mean", "precipitation_mm": "sum"}
DEFAULT_MISSING_POLICIES = {"temperature_c": "interpolate", "precipitation_mm": "zero_fill"}


def apply_missing_policy(series: pd.Series, policy: str, label: str) -> pd.Series:
    """Apply a missing-value policy to one metric's series.

    interpolate -- fill gaps from neighbouring values (continuous quantities)
    zero_fill   -- treat a missing value as a measured zero
    drop        -- leave the value missing so aggregation skips it; the row is
                   kept, so the other metric is unaffected
    fail        -- refuse to proceed if anything is missing
    """
    if policy not in MISSING_POLICIES:
        raise ValueError(f"{label}: unknown missing_policy {policy!r}")

    missing = int(series.isna().sum())
    if policy == "fail":
        if missing:
            raise ValueError(
                f"{label}: {missing} missing value(s) and missing_policy is 'fail'"
            )
        return series
    if missing == 0:
        return series
    if policy == "interpolate":
        return series.interpolate(limit_direction="both")
    if policy == "zero_fill":
        return series.fillna(0)
    return series  # "drop": excluded from aggregation via skipna


def _longest_missing_run(values: pd.Series) -> int:
    """Length of the longest run of consecutive missing values."""
    missing = values.isna()
    if not missing.any():
        return 0
    runs = (~missing).cumsum()
    return int(missing.groupby(runs).sum().max())


def assess_data_quality(frame: pd.DataFrame, metric_specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Report what is missing per metric, before any policy is applied.

    Coverage is the fraction of rows carrying a usable numeric value; it is the
    only thing that distinguishes a genuine zero from a filled-in one once the
    pipeline has run. longest_gap is the longest consecutive run of missing
    values, which coverage cannot express: scattered gaps and a single long gap
    can share a coverage figure while meaning very different things.
    """
    rows_read = len(frame)
    metrics: dict[str, Any] = {}
    for name, spec in metric_specs.items():
        column = spec["column"]
        values = pd.to_numeric(frame[column], errors="coerce")
        missing = int(values.isna().sum())
        metrics[name] = {
            "column": column,
            "missing": missing,
            "policy": spec["missing_policy"],
            "aggregation": spec["aggregation"],
            "coverage": round((rows_read - missing) / rows_read, 4) if rows_read else 0.0,
            "longest_gap": _longest_missing_run(values),
        }
    return {"rows_read": rows_read, "metrics": metrics}


def prepare_data(
    frame: pd.DataFrame,
    date_column: str,
    temp_column: str,
    precip_column: str,
    rolling_window_days: int,
    temp_policy: str = "interpolate",
    precip_policy: str = "zero_fill",
) -> pd.DataFrame:
    processed = frame.copy()
    processed[date_column] = pd.to_datetime(processed[date_column], errors="raise")
    processed[temp_column] = pd.to_numeric(processed[temp_column], errors="coerce")
    processed[precip_column] = pd.to_numeric(processed[precip_column], errors="coerce")
    processed = processed.sort_values(date_column).set_index(date_column)
    processed[temp_column] = apply_missing_policy(
        processed[temp_column], temp_policy, label="temperature_c"
    )
    processed[precip_column] = apply_missing_policy(
        processed[precip_column], precip_policy, label="precipitation_mm"
    )
    processed[f"{temp_column}_rolling_mean"] = processed[temp_column].rolling(rolling_window_days, min_periods=1).mean()
    processed[f"{precip_column}_rolling_sum"] = processed[precip_column].rolling(rolling_window_days, min_periods=1).sum()
    return processed


def build_monthly_summary(frame: pd.DataFrame, temp_column: str, precip_column: str) -> pd.DataFrame:
    monthly = frame.resample("MS").agg({
        temp_column: "mean",
        precip_column: "sum",
    })
    monthly = monthly.rename(columns={
        temp_column: "avg_temperature_c",
        precip_column: "total_precipitation_mm",
    })
    monthly.index.name = "month"
    return monthly.reset_index()


def create_plot(frame: pd.DataFrame, temp_column: str, precip_column: str, output_path: Path, title: str, width: float, height: float) -> None:
    fig, ax_temp = plt.subplots(figsize=(width, height))
    ax_precip = ax_temp.twinx()

    ax_temp.plot(frame.index, frame[temp_column], color="#2A6FDB", linewidth=1.8, label="Temperature (C)")
    ax_temp.plot(frame.index, frame[f"{temp_column}_rolling_mean"], color="#0B3A67", linewidth=2.5, linestyle="--", label="Rolling mean")
    ax_precip.bar(frame.index, frame[precip_column], color="#5CA9E6", alpha=0.25, width=0.8, label="Precipitation (mm)")

    ax_temp.set_title(title)
    ax_temp.set_xlabel("Date")
    ax_temp.set_ylabel("Temperature (C)")
    ax_precip.set_ylabel("Precipitation (mm)")
    ax_temp.grid(True, axis="y", alpha=0.25)

    handles_temp, labels_temp = ax_temp.get_legend_handles_labels()
    handles_precip, labels_precip = ax_precip.get_legend_handles_labels()
    ax_temp.legend(handles_temp + handles_precip, labels_temp + labels_precip, loc="upper right")

    fig.autofmt_xdate()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process mock climate data from a YAML config file.")
    parser.add_argument("--config", required=True, help="Path to the YAML configuration file")
    return parser.parse_args()


def run_pipeline(config: dict[str, Any], project_root: Path) -> dict[str, Any]:
    input_csv = resolve_path(project_root, config["input_csv"])
    date_column = config["date_column"]
    temp_column = config["metrics"]["temperature_c"]
    precip_column = config["metrics"]["precipitation_mm"]
    rolling_window_days = int(config.get("rolling_window_days", 7))

    policies = config.get("missing_policy", {})
    metric_specs = {
        name: {
            "column": config["metrics"][name],
            "aggregation": METRIC_AGGREGATIONS[name],
            "missing_policy": policies.get(name, DEFAULT_MISSING_POLICIES[name]),
        }
        for name in METRIC_AGGREGATIONS
    }

    plot_config = config["plot"]
    summary_config = config["summary"]
    plot_output = resolve_path(project_root, plot_config["output_path"])
    summary_output = resolve_path(project_root, summary_config["output_path"])

    frame = pd.read_csv(input_csv)
    data_quality = assess_data_quality(frame, metric_specs)
    processed = prepare_data(
        frame,
        date_column,
        temp_column,
        precip_column,
        rolling_window_days,
        temp_policy=metric_specs["temperature_c"]["missing_policy"],
        precip_policy=metric_specs["precipitation_mm"]["missing_policy"],
    )
    monthly_summary = build_monthly_summary(processed, temp_column, precip_column)

    summary_output.parent.mkdir(parents=True, exist_ok=True)
    monthly_summary.to_csv(summary_output, index=False)

    create_plot(
        processed,
        temp_column,
        precip_column,
        plot_output,
        plot_config.get("title", "Climate Trends"),
        float(plot_config.get("width", 12)),
        float(plot_config.get("height", 7)),
    )

    return {
        "input_csv": str(input_csv),
        "summary_path": str(summary_output),
        "plot_path": str(plot_output),
        "rows_processed": len(processed),
        "data_quality": data_quality,
    }


def run_from_config_path(config_path: Path) -> dict[str, Any]:
    """Assumes config_path lives at <project_root>/config/*.yaml, so that
    relative paths in the config (input_csv, output_path, ...) resolve
    against <project_root>."""
    config_path = config_path.resolve()
    config = load_config(config_path)
    project_root = config_path.parent.parent
    return run_pipeline(config, project_root)


def main() -> int:
    args = parse_args()
    result = run_from_config_path(Path(args.config))

    print(f"Read data from: {result['input_csv']}")
    print(f"Wrote summary to: {result['summary_path']}")
    print(f"Wrote plot to: {result['plot_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
