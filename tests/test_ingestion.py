"""Tests for repeatable bronze ingestion."""

from __future__ import annotations

import json
from pathlib import Path

from velov.ingest import write_raw_snapshot


def test_identical_raw_payload_is_written_once(tmp_path: Path) -> None:
    payload = {"last_updated": 123, "data": {"stations": [{"station_id": "42"}]}}

    first_path, first_inserted = write_raw_snapshot(payload, tmp_path, "station_status")
    second_path, second_inserted = write_raw_snapshot(payload, tmp_path, "station_status")

    assert first_inserted is True
    assert second_inserted is False
    assert first_path == second_path
    files = list((tmp_path / "station_status").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text(encoding="utf-8")) == payload
    print(f"first_inserted={first_inserted}")
    print(f"second_inserted={second_inserted}")
    print(f"snapshot_files={len(files)}")
    print(f"payload_preserved={json.loads(files[0].read_text(encoding='utf-8')) == payload}")
