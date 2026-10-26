"""Tests for the training-side gold contract."""

from __future__ import annotations

import pandas as pd
import pytest
from pandera.errors import SchemaErrors

from velov.contracts import validate_station_hourly


def test_station_hourly_contract_accepts_valid_rows() -> None:
    dataframe = pd.DataFrame(
        {
            "station_id": [1],
            "timestamp": pd.to_datetime(["2026-10-26T14:00:00Z"], utc=True),
            "capacity": [20],
            "bikes_available": [8],
            "temperature": [14.5],
            "is_raining": [False],
        }
    )

    validated = validate_station_hourly(dataframe)

    assert list(validated.columns) == [
        "station_id",
        "timestamp",
        "capacity",
        "bikes_available",
        "temperature",
        "is_raining",
    ]


def test_station_hourly_contract_rejects_bikes_above_capacity() -> None:
    dataframe = pd.DataFrame(
        {
            "station_id": [1],
            "timestamp": pd.to_datetime(["2026-10-26T14:00:00Z"], utc=True),
            "capacity": [20],
            "bikes_available": [21],
            "temperature": [14.5],
            "is_raining": [False],
        }
    )

    with pytest.raises(SchemaErrors):
        validate_station_hourly(dataframe)
