import pytest

from mcp_server import paths
from mcp_server.paths import PathSecurityError
from mcp_server.server import (
    get_config_schema,
    list_sample_data,
    process_climate_data,
    validate_climate_config,
)


def _valid_config(**overrides):
    config = {
        "input_csv": "mock_climate.csv",
        "date_column": "date",
        "metrics": {"temperature_c": "temperature_c", "precipitation_mm": "precipitation_mm"},
        "rolling_window_days": 3,
        "plot": {"title": "Test", "output_path": "plot.png", "width": 6, "height": 4},
        "summary": {"output_path": "summary.csv"},
    }
    config.update(overrides)
    return config


@pytest.fixture(autouse=True)
def _isolated_outputs_root(tmp_path, monkeypatch):
    """Redirect outputs/ to a temp dir so tests never touch the repo's outputs/."""
    monkeypatch.setattr(paths, "OUTPUTS_ROOT", tmp_path / "outputs")


def test_get_config_schema_matches_repo_schema():
    schema = get_config_schema()
    assert schema["title"] == "Climate processing config"
    assert "input_csv" in schema["required"]


def test_list_sample_data_finds_mock_csv():
    entries = list_sample_data()
    names = {entry["filename"] for entry in entries}
    assert "mock_climate.csv" in names
    mock_entry = next(e for e in entries if e["filename"] == "mock_climate.csv")
    assert set(mock_entry["columns"]) >= {"date", "temperature_c", "precipitation_mm"}


def test_validate_climate_config_accepts_valid_config():
    assert validate_climate_config(_valid_config()) == {"valid": True, "errors": []}


def test_validate_climate_config_reports_errors():
    result = validate_climate_config(_valid_config(rolling_window_days=0))
    assert result["valid"] is False
    assert result["errors"]


def test_process_climate_data_runs_and_returns_report_and_image():
    result = process_climate_data(_valid_config())

    assert len(result) == 2
    report, image = result
    assert "Processed 31 rows" in report
    assert "avg_temperature_c" in report
    assert image._mime_type == "image/png"
    assert len(image.data or b"") == 0  # loaded from path, not inline data
    assert image.path is not None and image.path.is_file()


def test_process_climate_data_writes_into_its_own_run_directory():
    result = process_climate_data(_valid_config())
    _, image = result
    assert image.path.parent.parent == paths.OUTPUTS_ROOT

    # a second run must not collide with or overwrite the first
    result2 = process_climate_data(_valid_config())
    _, image2 = result2
    assert image.path != image2.path
    assert image.path.is_file()
    assert image2.path.is_file()


def test_process_climate_data_rejects_invalid_config():
    config = _valid_config()
    del config["date_column"]
    with pytest.raises(ValueError):
        process_climate_data(config)


@pytest.mark.parametrize(
    "raw_input_csv",
    ["../requirements.txt", "/etc/passwd", "../../etc/passwd"],
    ids=["relative-escape", "absolute-outside", "deep-relative-escape"],
)
def test_process_climate_data_rejects_input_csv_outside_data_dir(raw_input_csv):
    config = _valid_config(input_csv=raw_input_csv)
    with pytest.raises(PathSecurityError):
        process_climate_data(config)


def test_process_climate_data_confines_output_paths_to_run_dir():
    config = _valid_config()
    config["plot"]["output_path"] = "../../evil.png"
    config["summary"]["output_path"] = "/etc/passwd"

    _, image = process_climate_data(config)

    assert image.path.name == "evil.png"
    assert image.path.parent.parent == paths.OUTPUTS_ROOT


def test_process_climate_data_reports_data_quality():
    report, _ = process_climate_data(_valid_config())

    assert "Data quality" in report
    assert "temperature_c" in report
    assert "coverage" in report
    assert "longest_gap" in report
    assert "policy=interpolate" in report


def test_process_climate_data_rejects_bad_missing_policy():
    config = _valid_config()
    config["missing_policy"] = {"precipitation_mm": "ignore"}
    with pytest.raises(ValueError):
        process_climate_data(config)


def test_process_climate_data_accepts_missing_policy_from_config():
    config = _valid_config()
    config["missing_policy"] = {"precipitation_mm": "fail"}
    # mock_climate.csv is complete, so 'fail' must still succeed
    report, _ = process_climate_data(config)
    assert "policy=fail" in report
