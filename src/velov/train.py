"""Entraînement du modèle v0 et production de l'artefact distribuable.

Ce qu'on distribue (S1) n'est pas "un modèle" mais un paquet :
- le pipeline sklearn complet (prétraitement + modèle) -> models/model.joblib
- ses métadonnées (version, features, métriques, empreinte SHA-256, versions des
  librairies, hash des données) -> models/metadata.json

Usage :
    python -m velov.train --data data/velov_history.csv --out models/
    python -m velov.train --data data/velov_history.csv --out models/ --mlflow
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import joblib
import mlflow
import numpy as np
import pandas as pd
import sklearn
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from velov.artifacts import METADATA_FILENAME, MODEL_FILENAME, sha256_of
from velov.contracts import validate_station_hourly
from velov.features import (
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    RAW_COLUMNS,
    TARGET,
    make_training_frame,
)

SKOPS_TRUSTED_TYPES = ["sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"]
MODEL_LEARNING_RATE = 0.1
MODEL_MAX_ITER = 200
PEAK_HOURS = (7, 8, 9, 17, 18, 19)


def build_pipeline(seed: int = 42) -> Pipeline:
    preprocess = ColumnTransformer(
        [
            ("station", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
            ("num", "passthrough", NUMERIC_FEATURES),
        ]
    )
    model = HistGradientBoostingRegressor(
        max_iter=MODEL_MAX_ITER,
        learning_rate=MODEL_LEARNING_RATE,
        random_state=seed,
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def temporal_split(df: pd.DataFrame, test_days: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Découpage temporel : on teste sur le futur, jamais sur un échantillon aléatoire."""
    cutoff = pd.to_datetime(df["timestamp"]).max() - pd.Timedelta(days=test_days)
    ts = pd.to_datetime(df["timestamp"])
    train, test = df[ts <= cutoff], df[ts > cutoff]
    if train.empty or test.empty:
        raise ValueError("Split vide : augmenter l'historique ou réduire test_days")
    return train, test


def load_gold_training_data(database_path: Path) -> pd.DataFrame:
    """Read and validate the dbt gold table through a read-only DuckDB connection."""
    import duckdb

    if not database_path.exists():
        raise FileNotFoundError(f"{database_path} introuvable : lancer `dbt build` d'abord")
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        gold = connection.sql(
            """
            select station_id, timestamp, capacity, bikes_available, temperature, is_raining
            from main.station_hourly
            order by station_id, timestamp
            """
        ).df()
    finally:
        connection.close()
    if gold.empty:
        raise ValueError("La table gold station_hourly est vide")
    gold["timestamp"] = pd.to_datetime(gold["timestamp"], utc=True)
    return validate_station_hourly(gold)


def train(
    data_path: Path,
    out_dir: Path,
    version: str = "0.1.0",
    test_days: int = 14,
    seed: int = 42,
) -> dict:
    """Entraîne, évalue contre une baseline, écrit l'artefact. Retourne les métadonnées."""
    if not data_path.exists():
        raise FileNotFoundError(f"{data_path} introuvable : lancer d'abord `python -m velov.data`")

    raw = pd.read_csv(data_path, parse_dates=["timestamp"])
    frame = make_training_frame(raw)
    train_df, test_df = temporal_split(frame, test_days)

    pipeline = build_pipeline(seed)
    pipeline.fit(train_df[FEATURES], train_df[TARGET])

    y_test = test_df[TARGET]
    pred = np.clip(pipeline.predict(test_df[FEATURES]), 0, test_df["capacity"])
    mae_model = float(mean_absolute_error(y_test, pred))
    peak_hours = pd.to_datetime(test_df["timestamp"]).dt.tz_convert("Europe/Paris").dt.hour.isin(PEAK_HOURS)
    if not peak_hours.any():
        raise ValueError("Le jeu de test ne contient aucune heure de pointe")
    mae_model_peak_hours = float(mean_absolute_error(y_test[peak_hours], pred[peak_hours]))
    # Baseline "persistance" : dans 1 h, il y aura autant de vélos que maintenant.
    # Le modèle doit justifier sa complexité face à cette baseline (exigence EX-05).
    mae_baseline = float(mean_absolute_error(y_test, test_df["bikes_available"]))
    evaluation_start = pd.to_datetime(test_df["timestamp"]).min().isoformat()
    evaluation_end = pd.to_datetime(test_df["timestamp"]).max().isoformat()

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / MODEL_FILENAME
    joblib.dump(pipeline, model_path)

    metadata = {
        "model_name": "velov-availability",
        "model_version": version,
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "task": "Prédire le nombre de vélos disponibles à H+1 par station",
        "input_columns": RAW_COLUMNS,
        "features": FEATURES,
        "target": TARGET,
        "parameters": {
            "test_days": test_days,
            "seed": seed,
            "learning_rate": MODEL_LEARNING_RATE,
            "max_iter": MODEL_MAX_ITER,
        },
        "metrics": {
            "mae_model": round(mae_model, 3),
            "mae_baseline_persistence": round(mae_baseline, 3),
            "mae_model_peak_hours": round(mae_model_peak_hours, 3),
            "test_days": test_days,
            "n_train": int(len(train_df)),
            "n_test": int(len(test_df)),
        },
        "data_period": {
            "start": pd.to_datetime(raw["timestamp"]).min().isoformat(),
            "end": pd.to_datetime(raw["timestamp"]).max().isoformat(),
        },
        "evaluation_period": {
            "start": evaluation_start,
            "end": evaluation_end,
            "days": test_days,
        },
        "artifact": {"file": MODEL_FILENAME, "sha256": sha256_of(model_path)},
        "data_sha256": sha256_of(data_path),
        "runtime": {
            "python": platform.python_version(),
            "scikit-learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    }
    (out_dir / METADATA_FILENAME).write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


def git_commit() -> str:
    """Retourne le commit Git qui a produit le modèle."""
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git est nécessaire pour associer le run MLflow à un commit")
    result = subprocess.run(  # noqa: S603
        [executable, "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_dirty() -> str:
    """Retourne l'état de modification du dépôt qui a produit le modèle."""
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git est nécessaire pour associer l'état du dépôt au run MLflow")
    result = subprocess.run(  # noqa: S603
        [executable, "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    )
    return str(bool(result.stdout.strip())).lower()


def log_to_mlflow(metadata: dict, out_dir: Path) -> None:
    """Journalise le contexte, les résultats et le modèle dans MLflow."""
    tracking_uri = os.getenv("MLFLOW_TRACKING_URI")
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    pipeline = joblib.load(out_dir / MODEL_FILENAME)
    sample = make_training_frame(
        pd.DataFrame(
            {
                "station_id": [1, 1],
                "timestamp": pd.to_datetime(["2026-06-01T06:00Z", "2026-06-01T07:00Z"]),
                "capacity": [20, 20],
                "bikes_available": [8, 5],
                "temperature": [21.0, 22.0],
                "is_raining": [False, False],
            }
        )
    )[FEATURES]

    mlflow.set_experiment("velov-availability")
    with mlflow.start_run(run_name=f"v{metadata['model_version']}"):
        mlflow.log_params(
            {
                "model": "HistGradientBoostingRegressor",
                "model_version": metadata["model_version"],
                "test_days": metadata["parameters"]["test_days"],
                "seed": metadata["parameters"]["seed"],
                "learning_rate": metadata["parameters"]["learning_rate"],
                "max_iter": metadata["parameters"]["max_iter"],
            }
        )
        mlflow.log_metrics({k: v for k, v in metadata["metrics"].items() if k.startswith("mae")})
        mlflow.set_tags(
            {
                "git_commit": git_commit(),
                "git_dirty": git_dirty(),
                "data_sha256": metadata["data_sha256"],
                "data_period_start": metadata["data_period"]["start"],
                "data_period_end": metadata["data_period"]["end"],
                "evaluation_period_start": metadata["evaluation_period"]["start"],
                "evaluation_period_end": metadata["evaluation_period"]["end"],
                "evaluation_days": metadata["evaluation_period"]["days"],
            }
        )
        mlflow.log_artifact(str(out_dir / MODEL_FILENAME), artifact_path="model-package")
        mlflow.log_artifact(str(out_dir / METADATA_FILENAME), artifact_path="model-package")
        mlflow.sklearn.log_model(
            pipeline,
            name="model",
            signature=infer_signature(sample, pipeline.predict(sample)),
            input_example=sample,
            # Depuis MLflow 3.x, sklearn est sérialisé par défaut en skops (format sûr,
            # sans exécution de code arbitraire), plus en pickle. skops refuse les types
            # qu'il ne connaît pas : on déclare explicitement ceux qu'on a vérifiés.
            serialization_format="skops",
            skops_trusted_types=SKOPS_TRUSTED_TYPES,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Entraîne le modèle Vélo'v v0.")
    parser.add_argument("--data", type=Path, default=Path("data/velov_history.csv"))
    parser.add_argument("--gold-db", type=Path, help="Lire et valider main.station_hourly dans DuckDB")
    parser.add_argument("--out", type=Path, default=Path("models"))
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--mlflow", action="store_true", help="journaliser aussi dans MLflow")
    args = parser.parse_args()

    if args.gold_db:
        gold = load_gold_training_data(args.gold_db)
        temporary_data = args.gold_db.with_name("gold-training-data.csv")
        gold.to_csv(temporary_data, index=False)
        try:
            metadata = train(temporary_data, args.out, version=args.version, seed=args.seed)
        finally:
            temporary_data.unlink(missing_ok=True)
    else:
        metadata = train(args.data, args.out, version=args.version, seed=args.seed)
    m = metadata["metrics"]
    print(f"MAE modèle   : {m['mae_model']:.3f} vélos")
    print(f"MAE baseline : {m['mae_baseline_persistence']:.3f} vélos (persistance)")
    print(f"Artefact     : {args.out / MODEL_FILENAME} (sha256 {metadata['artifact']['sha256'][:12]}...)")
    if args.mlflow:
        log_to_mlflow(metadata, args.out)
        print("Run journalisé dans MLflow (voir `mlflow ui`)")


if __name__ == "__main__":
    main()
