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
from contextlib import asynccontextmanager
from pathlib import Path
import pandas as pd
import psycopg2

import joblib
from fastapi import FastAPI, HTTPException

from velov.api.schemas import PredictionRequest, PredictionResponse  # noqa: F401
from velov.features import FEATURES, add_features  # noqa: F401
from velov.train import METADATA_FILENAME, sha256_of

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

# TODO 7 [Must] : POST /v1/predict ✓
#   - entrée : PredictionRequest ; sortie : PredictionResponse ✓
#   - construire un DataFrame d'une ligne, appliquer add_features, sélectionner FEATURES ✓
#   - prédire, borner entre 0 et capacity, target_timestamp = timestamp + 1 h ✓
#     (l'instant porte son fuseau : le contrat l'a validé)
#   - 503 si le modèle n'est pas chargé ✓
#   Question : pourquoi importer add_features plutôt que recalculer les features ici ? ✓
@app.post("/v1/predict", response_model=PredictionResponse)
def predict(request: PredictionRequest) -> PredictionResponse:
    # Verifier que le modèle est chargé
    if STATE["model"] is None:
        raise HTTPException(status_code=503, detail="Modèle non chargé")
    
    # Construire un DataFrame à partir du contenu de la requête
    df = pd.DataFrame([request.model_dump()])

    # Utiliser la méthode de preprocessing packagée "add_features" pour extraire les features
    df_features = add_features(df)
    # Sélectionner uniquement les colonnes de features attendues par le modèle
    X = df_features[FEATURES]
    # Question : pourquoi importer add_features plutôt que recalculer les features ici ?
    # Précisément pour éviter le training-serving skew : 
    # Le code de preprocessing reste l même en train et en production, donc les features sont cohérentes.

    # Calculer la prédiction
    prediction = float(STATE["model"].predict(X)[0])

    # Borner la prédiction entre 0 et capacity
    prediction_bounded = max(0.0, min(prediction, float(request.capacity)))

    # Calculer le timestamp de la cible (timestamp + 1 heure)
    target_timestamp = request.timestamp + pd.Timedelta(hours=1)

    # Récupérer la version du modèle depuis l'état global
    model_version = STATE["metadata"]["model_version"]

    # Sauvegarder la prédiction dans la base de données PostgreSQL
    save_prediction(
        station_id=request.station_id,
        target_timestamp=target_timestamp,
        predicted_bikes=prediction_bounded,
        model_version=model_version,
    )

    # Renvoyer la réponse sous forme de PredictionResponse
    return PredictionResponse(
        station_id=request.station_id,
        target_timestamp=target_timestamp,
        predicted_bikes=prediction_bounded,
        model_version=STATE["metadata"]["model_version"],
        )

# IA utilisée : 
# Gemini pour la gestion des codes d'erreurs (import HTTPException) et pour la correction du format output