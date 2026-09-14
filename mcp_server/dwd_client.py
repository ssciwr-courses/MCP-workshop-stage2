"""Client for downloading daily weather data from the DWD (Deutscher Wetterdienst).

Wraps the `wetterdienst` package, which handles the DWD Open Data station
lookup and file parsing, and does two things this pipeline needs on top of it:

- turns "nearest station to (latitude, longitude)" plus a date range into a
  normalized DataFrame with the same columns and units as
  data/mock_climate.csv (date, temperature_c, precipitation_mm,
  humidity_pct), so a download can be used as input_csv for
  process_climate_data without editing config/schema.json's metrics mapping
- turns wetterdienst's various failure modes (network, bad parameters, no
  station coverage for the window) into one DwdFetchError with a message
  meant to be read by whoever is holding the tool call, not a traceback

The network call is isolated in _query_dwd() so tests can monkeypatch it and
exercise the rest (validation, unit conversion, station selection) without
depending on DWD's servers being reachable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from wetterdienst.model.result import StationsResult, ValuesResult

# DWD's daily "climate_summary" dataset covers exactly the metrics this
# pipeline knows about (see data/mock_climate.csv), all at once, so a single
# request/station covers the whole download.
_PARAMETERS = "daily/climate_summary"

# Renames DWD's raw column names (already converted by wetterdienst's default
# settings to degree_celsius / millimeter / a 0..1 humidity fraction -- see
# _query_dwd) to the schema data/mock_climate.csv uses. Humidity is further
# scaled from that fraction to the 0..100 percent scale the mock data uses.
_TEMPERATURE_COLUMN = "temperature_air_mean_2m"
_PRECIPITATION_COLUMN = "precipitation_height"
_HUMIDITY_COLUMN = "humidity"

_MAX_RANGE_DAYS = 5 * 365


class DwdFetchError(ValueError):
    """Raised when DWD data cannot be fetched, or none is available for the request."""


@dataclass
class DwdFetchResult:
    """A normalized DataFrame plus the metadata of the station it came from."""

    dataframe: pl.DataFrame
    station_id: str
    station_name: str
    station_state: str
    distance_km: float

    @property
    def rows(self) -> int:
        return self.dataframe.height


def _normalize(df: pl.DataFrame) -> pl.DataFrame:
    """Rename/convert a raw wide values DataFrame to this pipeline's schema.

    Expects the columns _query_dwd's request produces: date,
    temperature_air_mean_2m, precipitation_height, humidity -- for a single
    station. Humidity arrives as a 0..1 fraction; this multiplies it back to
    the 0..100 percent scale data/mock_climate.csv uses.
    """
    return df.select(
        pl.col("date").dt.strftime("%Y-%m-%d").alias("date"),
        pl.col(_TEMPERATURE_COLUMN).alias("temperature_c"),
        pl.col(_PRECIPITATION_COLUMN).alias("precipitation_mm"),
        (pl.col(_HUMIDITY_COLUMN) * 100).round(1).alias("humidity_pct"),
    ).sort("date")


def _query_dwd(
    latitude: float, longitude: float, start: date, end: date
) -> tuple["StationsResult", "ValuesResult"]:
    """Run the actual wetterdienst request against DWD's Open Data service.

    Isolated from fetch_daily_weather so tests can monkeypatch this one
    function and exercise validation/normalization/file-writing without
    making a real network call.
    """
    from wetterdienst.provider.dwd.observation import DwdObservationRequest
    from wetterdienst.settings import Settings

    request = DwdObservationRequest(
        parameters=_PARAMETERS,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        settings=Settings(ts_shape="wide"),
    )
    stations = request.filter_by_rank(latlon=(latitude, longitude), rank=1)
    values = stations.values.all()
    return stations, values


def fetch_daily_weather(
    latitude: float, longitude: float, start_date: str, end_date: str
) -> DwdFetchResult:
    """Download daily temperature/precipitation/humidity for the DWD station
    nearest to (latitude, longitude), for [start_date, end_date] inclusive.

    latitude/longitude are decimal degrees; start_date/end_date are
    'YYYY-MM-DD' strings. Raises DwdFetchError if those are malformed or out
    of range, if the DWD service can't be reached, or if no station has data
    for the requested window.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise DwdFetchError(f"start_date/end_date must be 'YYYY-MM-DD': {exc}") from None
    if end < start:
        raise DwdFetchError(f"end_date ({end_date}) is before start_date ({start_date})")
    if (end - start).days > _MAX_RANGE_DAYS:
        raise DwdFetchError(
            f"date range spans more than {_MAX_RANGE_DAYS} days -- narrow it for this demo"
        )
    if not (-90 <= latitude <= 90):
        raise DwdFetchError(f"latitude {latitude} is out of range [-90, 90]")
    if not (-180 <= longitude <= 180):
        raise DwdFetchError(f"longitude {longitude} is out of range [-180, 180]")

    try:
        stations, values = _query_dwd(latitude, longitude, start, end)
    except DwdFetchError:
        raise
    except Exception as exc:  # network/service errors from wetterdienst+aiohttp
        raise DwdFetchError(f"Could not reach the DWD service: {exc}") from exc

    df = values.df
    if df.is_empty():
        raise DwdFetchError(
            f"No DWD data available near ({latitude}, {longitude}) between "
            f"{start_date} and {end_date}. DWD's 'recent' data usually lags a few "
            "days behind today -- try an earlier end_date, or widen the range."
        )

    station_id = df["station_id"][0]
    df = df.filter(pl.col("station_id") == station_id)
    station_row = stations.df.filter(pl.col("station_id") == station_id).row(0, named=True)

    return DwdFetchResult(
        dataframe=_normalize(df),
        station_id=str(station_id),
        station_name=station_row["name"],
        station_state=station_row["state"],
        distance_km=round(station_row["distance"], 2),
    )
