"""Collecte d'un lot temps réel idempotent de données Vélo'v et météo."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from velov.ingest import (
    STATION_INFORMATION_URL,
    STATION_STATUS_URL,
    fetch_json,
    fetch_weather,
    write_raw_snapshot,
)


def run_microbatch(output_dir: Path = Path("data/bronze")) -> dict[str, int | str]:
    """Collecte un lot temps réel ; cette commande est planifiée toutes les cinq minutes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    collected_at = datetime.now(UTC).isoformat()
    information_payload = fetch_json(STATION_INFORMATION_URL)
    _, information_snapshot_inserted = write_raw_snapshot(
        information_payload, output_dir, "station_information"
    )
    status_payload = fetch_json(STATION_STATUS_URL)
    _, status_snapshot_inserted = write_raw_snapshot(status_payload, output_dir, "station_status")
    weather_payload = fetch_weather()
    _, weather_snapshot_inserted = write_raw_snapshot(weather_payload, output_dir, "weather")
    return {
        "collected_at": collected_at,
        "information_snapshot_inserted": information_snapshot_inserted,
        "status_snapshot_inserted": status_snapshot_inserted,
        "weather_snapshot_inserted": weather_snapshot_inserted,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collecte un lot temps réel Vélo'v.")
    parser.add_argument("--output-dir", type=Path, default=Path("data/bronze"))
    args = parser.parse_args()
    print(run_microbatch(args.output_dir))


if __name__ == "__main__":
    main()
