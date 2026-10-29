from __future__ import annotations

import json

from velov.data import simulate
from velov.train import train


def test_training_records_actual_evaluation_period(tmp_path) -> None:
    data_path = tmp_path / "history.csv"
    output_dir = tmp_path / "models"
    simulate(days=20, n_stations=3, seed=0).to_csv(data_path, index=False)

    metadata = train(data_path, output_dir, test_days=3)
    persisted = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))

    assert metadata["evaluation_period"]["days"] == 3
    assert metadata["evaluation_period"]["start"] == "2026-06-17T21:00:00+00:00"
    assert metadata["evaluation_period"]["end"] == "2026-06-20T20:00:00+00:00"
    assert persisted["evaluation_period"] == metadata["evaluation_period"]
