"""API de serving du modèle Vélo'v.

TP1, partie 3 : exposez le modèle. Mode : IA déclarée autorisée pour cette partie.

Endpoints attendus (niveaux du TP1 : Must, Should, Stretch) :
    POST /v1/predict        [Must]    une prédiction
    GET  /health            [Should]  liveness : le process répond (ne dépend pas du modèle)
    GET  /ready             [Should]  readiness : 200 si le modèle est chargé, 503 sinon
    GET  /v1/model, POST /v1/predict/batch   [Stretch]

Lancement :
    uvicorn velov.api.main:app --reload
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Sequence
from contextlib import asynccontextmanager
from pathlib import Path

import joblib
import pandas as pd
import psycopg2
from fastapi import FastAPI, HTTPException, Response

from velov.api.schemas import PredictionRequest, PredictionResponse  # noqa: F401
from velov.artifacts import METADATA_FILENAME, sha256_of
from velov.features import FEATURES, add_features  # noqa: F401

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("velov.api")

STATE: dict = {"model": None, "metadata": None}

def save_prediction(
    station_id: int,
    target_timestamp,
    predicted_bikes: float,
    model_version: str,
) -> None:
    """Inserts the generated prediction into the PostgreSQL predictions table."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.warning("DATABASE_URL not found, skipping DB insert.")
        return

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO predictions (station_id, target_timestamp, predicted_bikes, model_version)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (
                        station_id,
                        target_timestamp.isoformat(),
                        predicted_bikes,
                        model_version,
                    ),
                )
                conn.commit()
    except Exception:
        logger.exception("Failed to store prediction in database.")


def load_model(model_dir: Path) -> tuple[object, dict]:
    """Fourni : charge le modèle APRÈS avoir vérifié son empreinte SHA-256."""
    metadata_path = model_dir / METADATA_FILENAME
    if not metadata_path.exists():
        raise FileNotFoundError(f"{metadata_path} introuvable")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    model_path = model_dir / metadata["artifact"]["file"]
    if sha256_of(model_path) != metadata["artifact"]["sha256"]:
        raise RuntimeError(f"Empreinte invalide pour {model_path}")
    return joblib.load(model_path), metadata


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Fourni : exécuté une fois au démarrage (avant yield) et à l'arrêt (après yield)."""
    model_dir = Path(os.getenv("MODEL_DIR", "models"))
    try:
        STATE["model"], STATE["metadata"] = load_model(model_dir)
        logger.info("Modèle %s chargé", STATE["metadata"]["model_version"])
    except Exception:
        logger.exception("Échec du chargement du modèle depuis %s", model_dir)
    yield
    STATE.update(model=None, metadata=None)


app = FastAPI(title="Vélo'v availability API", version="1.0.0", lifespan=lifespan)


# TODO 5 [Should] : GET /health -> {"status": "ok"}
@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe : indique simplement que le processus web tourne."""
    return {"status": "ok"}

# TODO 6 [Should] : GET /ready -> 200 + version du modèle si chargé, sinon HTTPException 503
@app.get("/ready")
def ready() -> dict[str, str]:
    """Readiness probe : 200 si le modèle est prêt à servir, 503 sinon."""
    if STATE["model"] is None or STATE["metadata"] is None:
        raise HTTPException(
            status_code=503,
            detail="Modèle non chargé",
        )
    return {
        "status": "ready",
        "model_version": STATE["metadata"]["model_version"],
    }

def _predict(
    requests: Sequence[PredictionRequest],
    model: object,
    model_version: str,
) -> tuple[list[PredictionResponse], dict[str, float]]:
    """Execute la preparation des features et l'inference sans reseau ni base."""
    started_at = time.perf_counter()

    features_started_at = time.perf_counter()
    df = pd.DataFrame([request.model_dump() for request in requests])
    df_features = add_features(df)
    X = df_features[FEATURES]
    features_ms = (time.perf_counter() - features_started_at) * 1000

    inference_started_at = time.perf_counter()
    predictions = model.predict(X)
    inference_ms = (time.perf_counter() - inference_started_at) * 1000

    postprocessing_started_at = time.perf_counter()
    responses = []
    for request, prediction in zip(requests, predictions, strict=True):
        prediction_bounded = max(0.0, min(float(prediction), float(request.capacity)))
        responses.append(
            PredictionResponse(
                station_id=request.station_id,
                target_timestamp=request.timestamp + pd.Timedelta(hours=1),
                predicted_bikes=prediction_bounded,
                model_version=model_version,
            )
        )
    postprocessing_ms = (time.perf_counter() - postprocessing_started_at) * 1000

    return responses, {
        "features_ms": features_ms,
        "inference_ms": inference_ms,
        "postprocessing_ms": postprocessing_ms,
        "total_ms": (time.perf_counter() - started_at) * 1000,
    }


# TODO 7 [Must] : POST /v1/predict
#   - entree : PredictionRequest ; sortie : PredictionResponse
#   - construire les features, predire et borner entre 0 et capacity
#   - target_timestamp = timestamp + 1 h
#   - 503 si le modele n'est pas charge
@app.post("/v1/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest, response: Response) -> PredictionResponse:
    """Sert une prediction et expose le temps total de traitement de l'API."""
    if STATE["model"] is None or STATE["metadata"] is None:
        raise HTTPException(status_code=503, detail="Modele non charge")

    started_at = time.perf_counter()
    predictions, timings = _predict(
        [request],
        STATE["model"],
        STATE["metadata"]["model_version"],
    )

    database_started_at = time.perf_counter()
    prediction = predictions[0]
    save_prediction(
        station_id=prediction.station_id,
        target_timestamp=prediction.target_timestamp,
        predicted_bikes=prediction.predicted_bikes,
        model_version=prediction.model_version,
    )
    database_ms = (time.perf_counter() - database_started_at) * 1000
    total_ms = (time.perf_counter() - started_at) * 1000

    response.headers["X-Process-Time-Ms"] = f"{total_ms:.3f}"
    logger.debug(
        "Temps prediction: total=%.3f ms features=%.3f ms inference=%.3f ms "
        "postprocessing=%.3f ms base=%.3f ms",
        total_ms,
        timings["features_ms"],
        timings["inference_ms"],
        timings["postprocessing_ms"],
        database_ms,
    )
    return prediction

# IA utilisée :
# Gemini pour la gestion des codes d'erreurs (import HTTPException) et pour la correction du format output
