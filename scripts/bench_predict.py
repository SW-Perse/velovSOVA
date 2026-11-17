"""Benchmark local des etapes internes de prediction, sans reseau ni base."""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from velov.api.main import _predict, load_model  # noqa: E402
from velov.api.schemas import PredictionRequest  # noqa: E402


def percentile(values: list[float], quantile: float) -> float:
    """Calcule un percentile par rang le plus proche."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * quantile))
    return ordered[index]


def build_requests(size: int) -> list[PredictionRequest]:
    """Construit un lot deterministe de requetes deja valides."""
    return [
        PredictionRequest(
            station_id=(index % 3) + 1,
            timestamp="2026-10-06T08:00:00+02:00",
            capacity=20,
            bikes_available=12,
            temperature=14.5,
            is_raining=False,
        )
        for index in range(size)
    ]


def measure(
    requests: list[PredictionRequest], model: object, model_version: str, runs: int
) -> dict[str, list[float]]:
    """Mesure les etapes internes apres une courte phase d'echauffement."""
    for _ in range(5):
        _predict(requests, model, model_version)

    measurements = {"total_ms": [], "features_ms": [], "inference_ms": [], "postprocessing_ms": []}
    for _ in range(runs):
        started_at = time.perf_counter()
        _, timings = _predict(requests, model, model_version)
        measurements["total_ms"].append((time.perf_counter() - started_at) * 1000)
        for name in ("features_ms", "inference_ms", "postprocessing_ms"):
            measurements[name].append(timings[name])
    return measurements


def summarize(values: Iterable[float]) -> str:
    """Formate les percentiles principaux en millisecondes."""
    values = list(values)
    return f"p50={statistics.median(values):.3f} ms p95={percentile(values, 0.95):.3f} ms"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=Path("models"))
    parser.add_argument("--batch", nargs="+", type=int, default=[1, 100, 1000])
    parser.add_argument("--runs", type=int, default=30)
    args = parser.parse_args()

    if args.runs < 2 or any(size < 1 for size in args.batch):
        parser.error("--runs doit etre superieur ou egal a 2 et --batch strictement positif")

    model, metadata = load_model(args.model_dir)
    model_version = metadata["model_version"]
    print(f"Modele: {model_version}")
    for size in args.batch:
        measurements = measure(build_requests(size), model, model_version, args.runs)
        print(f"Batch {size}: total {summarize(measurements['total_ms'])}")
        print(f"  features {summarize(measurements['features_ms'])}")
        print(f"  inference {summarize(measurements['inference_ms'])}")
        print(f"  post-traitement {summarize(measurements['postprocessing_ms'])}")


if __name__ == "__main__":
    main()
