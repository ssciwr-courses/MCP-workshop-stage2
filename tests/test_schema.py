import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "config" / "schema.json"


@pytest.fixture(scope="module")
def schema():
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def valid_config():
    return {
        "input_csv": "data/mock_climate.csv",
        "date_column": "date",
        "metrics": {"temperature_c": "temperature_c", "precipitation_mm": "precipitation_mm"},
        "rolling_window_days": 7,
        "plot": {"title": "Trends", "output_path": "outputs/plot.png", "width": 12, "height": 7},
        "summary": {"output_path": "outputs/summary.csv"},
    }


def test_valid_config_passes(schema, valid_config):
    validate(instance=valid_config, schema=schema)


def test_minimal_config_without_optional_fields_passes(schema, valid_config):
    del valid_config["rolling_window_days"]
    del valid_config["plot"]["title"]
    del valid_config["plot"]["width"]
    del valid_config["plot"]["height"]
    validate(instance=valid_config, schema=schema)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.pop("date_column"),
        lambda c: c["metrics"].pop("temperature_c"),
        lambda c: c["plot"].pop("output_path"),
        lambda c: c.update(extra="not allowed"),
        lambda c: c["plot"].update(extra="not allowed"),
        lambda c: c.update(rolling_window_days=0),
        lambda c: c["plot"].update(width=-1),
        lambda c: c.update(date_column=42),
        lambda c: c.update(date_column=""),
    ],
    ids=[
        "missing-top-level-field",
        "missing-nested-field",
        "missing-plot-output-path",
        "unknown-top-level-field",
        "unknown-nested-field",
        "bad-rolling-window-days",
        "negative-plot-width",
        "wrong-type",
        "empty-string",
    ],
)
def test_invalid_configs_fail(schema, valid_config, mutate):
    mutate(valid_config)
    with pytest.raises(ValidationError):
        validate(instance=valid_config, schema=schema)


def test_config_without_missing_policy_is_valid(schema, valid_config):
    """The field is optional - existing configs must keep working."""
    assert "missing_policy" not in valid_config
    validate(instance=valid_config, schema=schema)


def test_config_with_missing_policy_is_valid(schema, valid_config):
    valid_config["missing_policy"] = {"precipitation_mm": "drop"}
    validate(instance=valid_config, schema=schema)


def test_config_with_both_metrics_specified_is_valid(schema, valid_config):
    valid_config["missing_policy"] = {"temperature_c": "fail", "precipitation_mm": "fail"}
    validate(instance=valid_config, schema=schema)


@pytest.mark.parametrize(
    "policy_block",
    [
        {"precipitation_mm": "ignore"},
        {"temperature_c": "median"},
        {"humidity_pct": "drop"},
        {"precipitation_mm": 3},
    ],
    ids=["unknown-policy", "another-unknown-policy", "unknown-metric", "wrong-type"],
)
def test_invalid_missing_policy_blocks_fail(schema, valid_config, policy_block):
    valid_config["missing_policy"] = policy_block
    with pytest.raises(ValidationError):
        validate(instance=valid_config, schema=schema)
