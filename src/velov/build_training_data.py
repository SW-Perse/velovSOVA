"""Reconstruit une fenêtre d'entraînement réelle avec Vélo'v et la météo."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from velov.ingest import (
    HISTORICAL_VELOV_URL,
    fetch_historical_weather,
    fetch_json,
    parse_historical_station_status,
    write_raw_snapshot,
)

HISTORICAL_FILENAME = "stations-velo-v-de-la-metropole-de-lyon---disponibilites-temps-reel"


def _encode_pagination_url(url: str) -> str:
    """Réencode les liens paginés afin de préserver les signes des fuseaux horaires."""
    parts = urlsplit(url)
    query = urlencode(parse_qsl(parts.query.replace("+", "%2B"), keep_blank_values=True))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _latest_timestamp() -> datetime:
    params = {"maxfeatures": 1, "sortby": "-horodate", "filename": HISTORICAL_FILENAME}
    payload = fetch_json(f"{HISTORICAL_VELOV_URL}?{urlencode(params)}")
    values = payload.get("values", [])
    if not values:
        raise ValueError("L'API historique Vélo'v n'a renvoyé aucun enregistrement")
    return datetime.fromisoformat(values[0]["horodate"]).astimezone(UTC)


def _fetch_day(day: date, maxfeatures: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)
    params = {
        "horodate__gte": start.isoformat(),
        "horodate__lt": end.isoformat(),
        "maxfeatures": maxfeatures,
        "sortby": "-horodate",
        "filename": HISTORICAL_FILENAME,
    }
    records: list[dict[str, Any]] = []
    raw_pages: list[dict[str, Any]] = []
    next_url: str | None = f"{HISTORICAL_VELOV_URL}?{urlencode(params)}"
    while next_url:
        payload = fetch_json(next_url)
        raw_pages.append(payload)
        records.extend(parse_historical_station_status(payload))
        next_url = payload.get("next")
        if next_url:
            next_url = _encode_pagination_url(next_url)
    return records, raw_pages


def build_training_data(
    days: int = 90,
    output_dir: Path = Path("data/bronze"),
    maxfeatures: int = 10_000,
) -> dict[str, int | str]:
    """Récupère et déduplique la dernière fenêtre historique disponible."""
    if days < 1:
        raise ValueError("Le nombre de jours doit être au moins égal à 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    latest = _latest_timestamp()
    first_day = (latest - timedelta(days=days - 1)).date()
    last_day = latest.date()
    status_snapshots_inserted = 0
    fetched = 0
    current = first_day
    while current <= last_day:
        payload_rows, raw_pages = _fetch_day(current, maxfeatures)
        fetched += len(payload_rows)
        for page in raw_pages:
            _, inserted = write_raw_snapshot(page, output_dir, "historical_station_status")
            status_snapshots_inserted += int(inserted)
        current += timedelta(days=1)

    weather_payload = fetch_historical_weather(first_day.isoformat(), last_day.isoformat())
    _, weather_snapshot_inserted = write_raw_snapshot(
        weather_payload, output_dir, "historical_weather"
    )
    return {
        "first_date": first_day.isoformat(),
        "last_date": last_day.isoformat(),
        "fetched_status_rows": fetched,
        "inserted_status_snapshots": status_snapshots_inserted,
        "inserted_weather_snapshots": int(weather_snapshot_inserted),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Construit une fenêtre d'entraînement réelle Vélo'v.")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--output-dir", type=Path, default=Path("data/bronze"))
    parser.add_argument("--maxfeatures", type=int, default=10_000)
    args = parser.parse_args()
    print(build_training_data(args.days, args.output_dir, args.maxfeatures))


if __name__ == "__main__":
    main()
