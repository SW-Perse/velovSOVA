"""Runtime contracts for data consumed by model training."""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

GOLD_COLUMNS = [
    "station_id",
    "timestamp",
    "capacity",
    "bikes_available",
    "temperature",
    "is_raining",
]


class StationHourly(pa.DataFrameModel):
    station_id: pa.typing.Series[int] = pa.Field(gt=0)
    timestamp: pa.typing.Series[pd.DatetimeTZDtype] = pa.Field(
        dtype_kwargs={"unit": "us", "tz": "UTC"}
    )
    capacity: pa.typing.Series[int] = pa.Field(ge=1, le=100)
    bikes_available: pa.typing.Series[int] = pa.Field(ge=0)
    temperature: pa.typing.Series[float] = pa.Field(ge=-25, le=50)
    is_raining: pa.typing.Series[bool]

    @pa.dataframe_check
    @classmethod
    def bikes_le_capacity(cls, dataframe: pd.DataFrame) -> pd.Series:
        return dataframe["bikes_available"] <= dataframe["capacity"]

    @pa.dataframe_check
    @classmethod
    def timestamps_are_utc(cls, dataframe: pd.DataFrame) -> bool:
        return isinstance(dataframe["timestamp"].dtype, pd.DatetimeTZDtype) and str(
            dataframe["timestamp"].dt.tz
        ) == "UTC"

    class Config:
        strict = True
        unique = ["station_id", "timestamp"]


def validate_station_hourly(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Validate and return the gold data without coercing invalid timestamps."""
    normalized = dataframe.copy()
    for column in ("station_id", "capacity", "bikes_available"):
        normalized[column] = normalized[column].astype("int64")
    validated = StationHourly.validate(normalized, lazy=True)
    return validated[GOLD_COLUMNS]
