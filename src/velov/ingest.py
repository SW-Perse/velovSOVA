"""Fonctions réutilisables de téléchargement et de normalisation du pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GBFS_BASE_URL = "https://download.data.grandlyon.com/files/rdata/jcd_jcdecaux.jcdvelov"
STATION_INFORMATION_URL = f"{GBFS_BASE_URL}/station_information.json"
STATION_STATUS_URL = f"{GBFS_BASE_URL}/station_status.json"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
HISTORICAL_VELOV_URL = (
    "https://data.grandlyon.com/fr/datapusher/ws/timeseries/"
    "jcd_jcdecaux.historiquevelov/all.json"
)
LYON_LATITUDE = 45.764043
LYON_LONGITUDE = 4.835659


def write_raw_snapshot(payload: dict[str, Any], directory: Path, feed: str) -> tuple[Path, bool]:
    """Write one immutable source payload, using a source-derived stable filename."""
    source_key = payload.get("last_updated")
    if source_key is None:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        source_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    target = directory / feed / f"{source_key}.json"
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target, True


def fetch_json(url: str, timeout: int = 30) -> dict[str, Any]:
    """Récupère un objet JSON depuis un endpoint HTTP public."""
    request = Request(url, headers={"User-Agent": "velov-mlops/1.0"})  # noqa: S310
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError(f"Un objet JSON était attendu depuis {url}")
    return payload


def parse_station_information(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise le flux GBFS d'informations sur les stations."""
    stations = payload.get("data", {}).get("stations", [])
    if not isinstance(stations, list):
        raise ValueError("Le payload station_information ne contient aucune station")
    return [
        {
            "station_id": str(station["station_id"]),
            "name": station.get("name"),
            "lat": station.get("lat"),
            "lon": station.get("lon"),
            "address": station.get("address"),
            "capacity": station.get("capacity"),
        }
        for station in stations
    ]


def parse_station_status(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise le flux GBFS d'état des stations."""
    stations = payload.get("data", {}).get("stations", [])
    if not isinstance(stations, list):
        raise ValueError("Le payload station_status ne contient aucune station")
    return [
        {
            "station_id": str(station["station_id"]),
            "last_reported": datetime.fromtimestamp(
                int(station["last_reported"]), tz=UTC
            ).isoformat(),
            "num_bikes_available": station.get("num_bikes_available"),
            "num_docks_available": station.get("num_docks_available"),
            "num_bikes_disabled": station.get("num_bikes_disabled"),
            "num_docks_disabled": station.get("num_docks_disabled"),
            "is_installed": station.get("is_installed"),
            "is_renting": station.get("is_renting"),
            "is_returning": station.get("is_returning"),
        }
        for station in stations
    ]


def parse_historical_station_status(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise les enregistrements de la série temporelle historique de la Métropole."""
    records = payload.get("values", [])
    if not isinstance(records, list):
        raise ValueError("Le payload historique Vélo'v ne contient aucune valeur")
    rows = []
    for record in records:
        total_stands = record.get("total_stands") or {}
        availabilities = total_stands.get("availabilities") or {}
        rows.append(
            {
                "station_id": str(record["number"]),
                "timestamp": datetime.fromisoformat(record["horodate"]).astimezone(UTC).isoformat(),
                "capacity": total_stands.get("capacity"),
                "bikes_available": availabilities.get("bikes"),
                "docks_available": availabilities.get("stands"),
                "status": record.get("status"),
            }
        )
    return rows


def fetch_weather(
    start_date: str | None = None,
    end_date: str | None = None,
    latitude: float = LYON_LATITUDE,
    longitude: float = LYON_LONGITUDE,
) -> dict[str, Any]:
    """Récupère la météo horaire de Lyon via Open-Meteo sans clé API.

    Sans dates, Open-Meteo renvoie hier, aujourd'hui et demain. Des dates
    explicites permettent de reconstituer la météo, mais pas la disponibilité
    passée de Vélo'v.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,precipitation,rain",
        "timezone": "UTC",
    }
    if start_date and end_date:
        params.update({"start_date": start_date, "end_date": end_date})
    else:
        params.update({"past_days": 1, "forecast_days": 2})
    return fetch_json(f"{OPEN_METEO_URL}?{urlencode(params)}")


def fetch_historical_weather(
    start_date: str,
    end_date: str,
    latitude: float = LYON_LATITUDE,
    longitude: float = LYON_LONGITUDE,
) -> dict[str, Any]:
    """Récupère la météo horaire historique via l'API d'archive Open-Meteo."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date,
        "end_date": end_date,
        "hourly": "temperature_2m,precipitation,rain",
        "timezone": "UTC",
    }
    return fetch_json(f"{OPEN_METEO_ARCHIVE_URL}?{urlencode(params)}")


def parse_weather(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise la météo horaire Open-Meteo selon le schéma du projet."""
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    temperatures = hourly.get("temperature_2m", [])
    precipitation = hourly.get("precipitation", [])
    rain = hourly.get("rain", [])
    if not all(isinstance(value, list) for value in (times, temperatures, precipitation, rain)):
        raise ValueError("Le payload Open-Meteo ne contient pas les tableaux météo horaires")
    if not len({len(times), len(temperatures), len(precipitation), len(rain)}) == 1:
        raise ValueError("Les tableaux horaires Open-Meteo ont des longueurs différentes")
    return [
        {
            "hour_ts": timestamp,
            "temperature": temperature,
            "precipitation": precipitation_value,
            "is_raining": rain_value > 0,
        }
        for timestamp, temperature, precipitation_value, rain_value in zip(
            times, temperatures, precipitation, rain, strict=True
        )
    ]

