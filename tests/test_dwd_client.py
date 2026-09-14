"""Tests for mcp_server/dwd_client.py.

None of these hit the network: _query_dwd (the one function that talks to
DWD) is monkeypatched with small hand-built polars DataFrames shaped like a
real response, so validation, unit conversion and station selection are
exercised deterministically and offline.
"""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

from mcp_server import dwd_client
from mcp_server.dwd_client import DwdFetchError, fetch_daily_weather


class _FakeStationsResult:
    def __init__(self, df: pl.DataFrame) -> None:
        self.df = df


class _FakeValuesResult:
    def __init__(self, df: pl.DataFrame) -> None:
        self.df = df


def _values_df(*, station_id: str = "05906", rows: list[tuple] | None = None) -> pl.DataFrame:
    if rows is None:
        rows = [
            ("2023-06-01", 20.8, 0.0, 0.46),
            ("2023-06-02", 16.7, 1.2, 0.54),
        ]
    return pl.DataFrame(
        {
            "station_id": [station_id] * len(rows),
            "date": [datetime(int(d[:4]), int(d[5:7]), int(d[8:10])) for d, *_ in rows],
            "temperature_air_mean_2m": [r[1] for r in rows],
            "precipitation_height": [r[2] for r in rows],
            "humidity": [r[3] for r in rows],
        }
    )


def _stations_df(*, station_id: str = "05906", name: str = "Mannheim", distance: float = 14.5688) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "station_id": [station_id],
            "name": [name],
            "state": ["Baden-Württemberg"],
            "distance": [distance],
        }
    )


def _patch_query(monkeypatch, *, values_df: pl.DataFrame | None = None, stations_df: pl.DataFrame | None = None):
    values_df = _values_df() if values_df is None else values_df
    stations_df = _stations_df() if stations_df is None else stations_df

    def _fake_query_dwd(latitude, longitude, start, end):
        return _FakeStationsResult(stations_df), _FakeValuesResult(values_df)

    monkeypatch.setattr(dwd_client, "_query_dwd", _fake_query_dwd)


def test_fetch_daily_weather_normalizes_columns_and_units(monkeypatch):
    _patch_query(monkeypatch)

    result = fetch_daily_weather(49.4093, 8.6939, "2023-06-01", "2023-06-02")

    assert result.station_id == "05906"
    assert result.station_name == "Mannheim"
    assert result.station_state == "Baden-Württemberg"
    assert result.distance_km == pytest.approx(14.57, abs=0.01)
    assert result.rows == 2

    df = result.dataframe
    assert df.columns == ["date", "temperature_c", "precipitation_mm", "humidity_pct"]
    assert df["date"].to_list() == ["2023-06-01", "2023-06-02"]
    assert df["temperature_c"].to_list() == [20.8, 16.7]
    assert df["precipitation_mm"].to_list() == [0.0, 1.2]
    # humidity arrives from DWD as a 0..1 fraction and must be scaled to 0..100
    assert df["humidity_pct"].to_list() == [46.0, 54.0]


def test_fetch_daily_weather_keeps_only_the_selected_station(monkeypatch):
    # a defensive case: if the raw values frame ever mixed stations, only the
    # first station_id's rows should end up in the result
    mixed = pl.concat([_values_df(station_id="05906"), _values_df(station_id="00433")])
    _patch_query(monkeypatch, values_df=mixed)

    result = fetch_daily_weather(49.4093, 8.6939, "2023-06-01", "2023-06-02")

    assert result.station_id == "05906"
    assert result.rows == 2


def test_fetch_daily_weather_rejects_bad_date_format():
    with pytest.raises(DwdFetchError, match="YYYY-MM-DD"):
        fetch_daily_weather(49.4093, 8.6939, "01-06-2023", "2023-06-02")


def test_fetch_daily_weather_rejects_end_before_start():
    with pytest.raises(DwdFetchError, match="before start_date"):
        fetch_daily_weather(49.4093, 8.6939, "2023-06-10", "2023-06-01")


def test_fetch_daily_weather_rejects_overly_wide_range():
    with pytest.raises(DwdFetchError, match="more than"):
        fetch_daily_weather(49.4093, 8.6939, "2000-01-01", "2020-01-01")


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91.0, 8.0), (-91.0, 8.0), (49.0, 181.0), (49.0, -181.0)],
)
def test_fetch_daily_weather_rejects_out_of_range_coordinates(latitude, longitude):
    with pytest.raises(DwdFetchError, match="out of range"):
        fetch_daily_weather(latitude, longitude, "2023-06-01", "2023-06-02")


def test_fetch_daily_weather_reports_no_data(monkeypatch):
    _patch_query(monkeypatch, values_df=_values_df(rows=[]))

    with pytest.raises(DwdFetchError, match="No DWD data available"):
        fetch_daily_weather(49.4093, 8.6939, "2023-06-01", "2023-06-02")


def test_fetch_daily_weather_wraps_network_errors(monkeypatch):
    def _boom(latitude, longitude, start, end):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(dwd_client, "_query_dwd", _boom)

    with pytest.raises(DwdFetchError, match="Could not reach the DWD service"):
        fetch_daily_weather(49.4093, 8.6939, "2023-06-01", "2023-06-02")
