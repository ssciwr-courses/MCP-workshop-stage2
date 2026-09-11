from pathlib import Path

import pandas as pd
import pytest
import yaml

import process_climate as pc

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_resolve_path_absolute(tmp_path):
    absolute = tmp_path / "some" / "file.csv"
    assert pc.resolve_path(Path("/whatever"), str(absolute)) == absolute


def test_resolve_path_relative(tmp_path):
    result = pc.resolve_path(tmp_path, "sub/file.csv")
    assert result == (tmp_path / "sub/file.csv").resolve()


def test_prepare_data_interpolates_and_fills():
    frame = pd.DataFrame(
        {
            "date": ["2026-01-03", "2026-01-01", "2026-01-02"],
            "temp": [None, 1.0, 3.0],
            "precip": [2.0, None, 1.0],
        }
    )

    processed = pc.prepare_data(frame, "date", "temp", "precip", rolling_window_days=2)

    assert list(processed.index) == list(pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]))
    assert processed["temp"].isna().sum() == 0
    assert processed.loc[pd.Timestamp("2026-01-03"), "temp"] == pytest.approx(3.0)
    assert processed["precip"].isna().sum() == 0
    assert processed.loc[pd.Timestamp("2026-01-01"), "precip"] == pytest.approx(0.0)
    assert "temp_rolling_mean" in processed.columns
    assert "precip_rolling_sum" in processed.columns


def test_build_monthly_summary():
    index = pd.to_datetime(["2026-01-01", "2026-01-15", "2026-02-01"])
    frame = pd.DataFrame({"temp": [0.0, 10.0, 100.0], "precip": [1.0, 3.0, 5.0]}, index=index)

    monthly = pc.build_monthly_summary(frame, "temp", "precip")

    jan = monthly[monthly["month"] == pd.Timestamp("2026-01-01")].iloc[0]
    feb = monthly[monthly["month"] == pd.Timestamp("2026-02-01")].iloc[0]
    assert jan["avg_temperature_c"] == pytest.approx(5.0)
    assert jan["total_precipitation_mm"] == pytest.approx(4.0)
    assert feb["avg_temperature_c"] == pytest.approx(100.0)
    assert feb["total_precipitation_mm"] == pytest.approx(5.0)


def _valid_config_dict(input_csv="data.csv", plot_path="out/plot.png", summary_path="out/summary.csv"):
    return {
        "input_csv": input_csv,
        "date_column": "date",
        "metrics": {"temperature_c": "temperature_c", "precipitation_mm": "precipitation_mm"},
        "rolling_window_days": 3,
        "plot": {"title": "Test", "output_path": plot_path, "width": 6, "height": 4},
        "summary": {"output_path": summary_path},
    }


def test_load_config_valid_repo_example():
    config = pc.load_config(REPO_ROOT / "config" / "example.yaml")
    assert config["date_column"] == "date"
    assert config["metrics"]["temperature_c"] == "temperature_c"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.pop("date_column"),
        lambda c: c.update(unexpected_field="surprise"),
        lambda c: c.update(rolling_window_days=0),
    ],
    ids=["missing-required-field", "unknown-field", "bad-rolling-window-days"],
)
def test_load_config_rejects_invalid_config(tmp_path, mutate):
    config = _valid_config_dict()
    mutate(config)
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(yaml.safe_dump(config))

    with pytest.raises(ValueError):
        pc.load_config(config_path)


def test_run_pipeline_end_to_end(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_path = data_dir / "mini_climate.csv"
    csv_path.write_text(
        "date,temperature_c,precipitation_mm\n"
        "2026-01-01,1.0,0.0\n"
        "2026-01-02,2.0,1.0\n"
        "2026-01-03,3.0,0.0\n"
        "2026-02-01,4.0,2.0\n"
    )

    config = _valid_config_dict(
        input_csv="data/mini_climate.csv",
        plot_path="outputs/plot.png",
        summary_path="outputs/summary.csv",
    )

    result = pc.run_pipeline(config, tmp_path)

    summary_path = Path(result["summary_path"])
    plot_path = Path(result["plot_path"])
    assert summary_path.exists()
    assert plot_path.exists()
    assert plot_path.stat().st_size > 0
    assert result["rows_processed"] == 4

    summary = pd.read_csv(summary_path)
    assert list(summary["month"]) == ["2026-01-01", "2026-02-01"]
    assert summary.loc[0, "avg_temperature_c"] == pytest.approx(2.0)
    assert summary.loc[1, "avg_temperature_c"] == pytest.approx(4.0)


def test_run_from_config_path_matches_repo_example():
    result = pc.run_from_config_path(REPO_ROOT / "config" / "example.yaml")

    assert Path(result["summary_path"]).exists()
    assert Path(result["plot_path"]).exists()
    assert result["rows_processed"] > 0


def test_apply_missing_policy_interpolate():
    series = pd.Series([1.0, None, 3.0])
    result = pc.apply_missing_policy(series, "interpolate", label="temperature_c")
    assert result.isna().sum() == 0
    assert result.iloc[1] == pytest.approx(2.0)


def test_apply_missing_policy_zero_fill():
    series = pd.Series([1.0, None, 3.0])
    result = pc.apply_missing_policy(series, "zero_fill", label="precipitation_mm")
    assert result.iloc[1] == pytest.approx(0.0)


def test_apply_missing_policy_drop_leaves_nan_for_skipna():
    series = pd.Series([1.0, None, 3.0])
    result = pc.apply_missing_policy(series, "drop", label="precipitation_mm")
    assert result.isna().sum() == 1
    assert result.sum() == pytest.approx(4.0)


def test_apply_missing_policy_fail_raises_with_count():
    series = pd.Series([1.0, None, None])
    with pytest.raises(ValueError, match="2 missing"):
        pc.apply_missing_policy(series, "fail", label="precipitation_mm")


def test_apply_missing_policy_fail_passes_on_complete_series():
    series = pd.Series([1.0, 2.0])
    result = pc.apply_missing_policy(series, "fail", label="temperature_c")
    assert list(result) == [1.0, 2.0]


def test_apply_missing_policy_rejects_unknown_policy():
    with pytest.raises(ValueError, match="unknown missing_policy"):
        pc.apply_missing_policy(pd.Series([1.0]), "guess", label="temperature_c")


def _specs(temp_policy="interpolate", precip_policy="drop"):
    return {
        "temperature_c": {
            "column": "temp",
            "aggregation": "mean",
            "missing_policy": temp_policy,
        },
        "precipitation_mm": {
            "column": "precip",
            "aggregation": "sum",
            "missing_policy": precip_policy,
        },
    }


def test_assess_data_quality_counts_missing_and_coverage():
    frame = pd.DataFrame({"temp": [1.0, None, 3.0, 4.0], "precip": [0.0, 1.0, None, None]})

    quality = pc.assess_data_quality(frame, _specs())

    assert quality["rows_read"] == 4
    assert quality["metrics"]["temperature_c"]["missing"] == 1
    assert quality["metrics"]["temperature_c"]["coverage"] == pytest.approx(0.75)
    assert quality["metrics"]["precipitation_mm"]["missing"] == 2
    assert quality["metrics"]["precipitation_mm"]["coverage"] == pytest.approx(0.5)


def test_assess_data_quality_echoes_policy_and_aggregation():
    frame = pd.DataFrame({"temp": [1.0], "precip": [2.0]})

    quality = pc.assess_data_quality(frame, _specs(precip_policy="fail"))

    assert quality["metrics"]["precipitation_mm"]["policy"] == "fail"
    assert quality["metrics"]["precipitation_mm"]["aggregation"] == "sum"
    assert quality["metrics"]["temperature_c"]["column"] == "temp"


def test_assess_data_quality_treats_non_numeric_as_missing():
    frame = pd.DataFrame({"temp": ["1.0", "n/a"], "precip": [0.0, 1.0]})

    quality = pc.assess_data_quality(frame, _specs())

    assert quality["metrics"]["temperature_c"]["missing"] == 1


def test_assess_data_quality_reports_longest_gap():
    frame = pd.DataFrame(
        {
            "temp": [1.0, None, None, None, 5.0, None, 7.0],
            "precip": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        }
    )

    quality = pc.assess_data_quality(frame, _specs())

    assert quality["metrics"]["temperature_c"]["missing"] == 4
    assert quality["metrics"]["temperature_c"]["longest_gap"] == 3
    assert quality["metrics"]["precipitation_mm"]["longest_gap"] == 0


def test_longest_gap_distinguishes_scattered_from_consecutive():
    """Same missing count and coverage, different longest_gap - the reason the
    field exists."""
    scattered = pd.DataFrame({"temp": [None, 1.0, None, 2.0, None, 3.0], "precip": [0.0] * 6})
    consecutive = pd.DataFrame({"temp": [None, None, None, 1.0, 2.0, 3.0], "precip": [0.0] * 6})

    a = pc.assess_data_quality(scattered, _specs())["metrics"]["temperature_c"]
    b = pc.assess_data_quality(consecutive, _specs())["metrics"]["temperature_c"]

    assert a["missing"] == b["missing"] == 3
    assert a["coverage"] == b["coverage"]
    assert a["longest_gap"] == 1
    assert b["longest_gap"] == 3


def test_assess_data_quality_gap_runs_to_end_of_series():
    frame = pd.DataFrame({"temp": [1.0, None, None], "precip": [0.0, 1.0, 2.0]})

    quality = pc.assess_data_quality(frame, _specs())

    assert quality["metrics"]["temperature_c"]["longest_gap"] == 2


def test_prepare_data_defaults_reproduce_current_behaviour():
    """No policy arguments -> exactly what the pipeline did before."""
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "temp": [1.0, None, 3.0],
            "precip": [2.0, None, 1.0],
        }
    )

    processed = pc.prepare_data(frame, "date", "temp", "precip", rolling_window_days=2)

    assert processed["temp"].isna().sum() == 0
    assert processed.loc[pd.Timestamp("2026-01-02"), "temp"] == pytest.approx(2.0)
    assert processed.loc[pd.Timestamp("2026-01-02"), "precip"] == pytest.approx(0.0)


def test_prepare_data_honours_explicit_policies():
    frame = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "temp": [1.0, None, 3.0],
            "precip": [2.0, None, 1.0],
        }
    )

    processed = pc.prepare_data(
        frame, "date", "temp", "precip", rolling_window_days=2, precip_policy="drop"
    )

    assert processed["precip"].isna().sum() == 1


def test_prepare_data_fail_policy_raises():
    frame = pd.DataFrame(
        {"date": ["2026-01-01", "2026-01-02"], "temp": [1.0, 2.0], "precip": [0.0, None]}
    )

    with pytest.raises(ValueError, match="precipitation_mm"):
        pc.prepare_data(
            frame, "date", "temp", "precip", rolling_window_days=2, precip_policy="fail"
        )


def _write_gappy_csv(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    csv_path = data_dir / "gappy.csv"
    csv_path.write_text(
        "date,temperature_c,precipitation_mm\n"
        "2026-01-01,1.0,4.0\n"
        "2026-01-02,2.0,\n"
        "2026-01-03,3.0,\n"
        "2026-01-04,4.0,6.0\n"
    )
    return csv_path


def test_run_pipeline_returns_data_quality(tmp_path):
    _write_gappy_csv(tmp_path)
    config = _valid_config_dict(
        input_csv="data/gappy.csv",
        plot_path="outputs/plot.png",
        summary_path="outputs/summary.csv",
    )

    result = pc.run_pipeline(config, tmp_path)

    quality = result["data_quality"]
    assert quality["rows_read"] == 4
    precip = quality["metrics"]["precipitation_mm"]
    assert precip["missing"] == 2
    assert precip["longest_gap"] == 2
    assert precip["coverage"] == pytest.approx(0.5)
    assert precip["aggregation"] == "sum"
    assert precip["policy"] == "zero_fill"  # the default


def test_run_pipeline_applies_missing_policy_from_config(tmp_path):
    _write_gappy_csv(tmp_path)
    config = _valid_config_dict(
        input_csv="data/gappy.csv",
        plot_path="outputs/plot.png",
        summary_path="outputs/summary.csv",
    )
    config["missing_policy"] = {"precipitation_mm": "fail"}

    with pytest.raises(ValueError, match="precipitation_mm"):
        pc.run_pipeline(config, tmp_path)


def test_run_pipeline_zero_fill_and_drop_give_the_same_total(tmp_path):
    """The teaching case: identical number, different coverage."""
    _write_gappy_csv(tmp_path)

    totals = {}
    for policy in ("zero_fill", "drop"):
        config = _valid_config_dict(
            input_csv="data/gappy.csv",
            plot_path=f"outputs/plot_{policy}.png",
            summary_path=f"outputs/summary_{policy}.csv",
        )
        config["missing_policy"] = {"precipitation_mm": policy}
        result = pc.run_pipeline(config, tmp_path)
        summary = pd.read_csv(result["summary_path"])
        totals[policy] = summary.loc[0, "total_precipitation_mm"]

    assert totals["zero_fill"] == pytest.approx(totals["drop"]) == pytest.approx(10.0)
