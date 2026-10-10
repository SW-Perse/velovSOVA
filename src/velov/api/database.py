from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DATABASE_URL = os.getenv("DATABASE_URL")

engine: Engine | None = (
    create_engine(DATABASE_URL, pool_pre_ping=True)
    if DATABASE_URL
    else None
)

def init_database() -> None:
    if engine is None:
        return

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS predictions (
                    id BIGSERIAL PRIMARY KEY,
                    station_id INTEGER NOT NULL,
                    input_timestamp TIMESTAMPTZ NOT NULL,
                    target_timestamp TIMESTAMPTZ NOT NULL,
                    capacity INTEGER NOT NULL,
                    bikes_available INTEGER NOT NULL,
                    temperature DOUBLE PRECISION NOT NULL,
                    is_raining BOOLEAN NOT NULL,
                    predicted_bikes DOUBLE PRECISION NOT NULL,
                    model_version TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        