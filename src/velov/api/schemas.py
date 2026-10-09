"""Contrat d'entrée / sortie de l'API (validé par Pydantic, publié dans OpenAPI).

TP1, partie 2 : complétez les schémas. Mode : SANS IA pour cette partie.
"""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import UTC


class PredictionRequest(BaseModel):
    """Une observation de station à l'instant t.

    Les 6 champs attendus par le modèle sont : ls features extraites de RAW_COLUMNS :
    "station_id",
    "timestamp",
    "capacity",
    "bikes_available",
    "temperature",
    "is_raining"

    TODO 1 [Must] : déclarer les 6 champs attendus par le modèle (voir velov.features.RAW_COLUMNS)
             avec leur type Python. Pour timestamp, utilisez AwareDatetime et non datetime :
             datetime accepte "2026-10-06T08:00:00" sans fuseau, un instant ambigu.  ✓
    TODO 2 [Must] : ajouter des bornes avec Field(...) : station_id >= 1, 0 < capacity <= 100,
             bikes_available >= 0, température entre -30 et 50 °C. ✓
    TODO 3 [Must] : refuser un champ inconnu (indice : model_config / extra). ✓
    TODO 4 [Must] : refuser bikes_available > capacity (indice : @model_validator(mode="after")). ✓
    TODO 4 bis [Should] : normaliser timestamp en UTC
             (indice : @field_validator("timestamp") et value.astimezone(UTC)). ✓
    """

    model_config = ConfigDict(extra="forbid")  
    # Paramètre extra="forbid : ValidationError si un champ inconnu est fourni, 
    # renvoie HTTP 422 Unprocessable Entity avec le détail du champ inconnu.

    station_id: int = Field(..., ge=1, description="Identifiant de la station")
    timestamp: AwareDatetime = Field(..., description="Instant de l'observation, avec fuseau horaire")
    capacity: int = Field(..., gt=0, le=100, description="Nombre total de places à la station")
    bikes_available: int = Field(..., ge=0, description="Nombre de vélos disponibles à la station")
    temperature: float = Field(..., ge=-30, le=50, description="Température en °C")
    is_raining: bool = Field(..., description="True si il pleut, False sinon")

    # Refuser bikes_available > capacity
    @model_validator(mode="after")
    def check_bikes_available_le_capacity(self):
        if self.bikes_available > self.capacity:
            raise ValueError(f"bikes_available {self.bikes_available} ne peut pas être supérieur à capacity {self.capacity}")
        return self

    # Normaliser timestamp en UTC
    @field_validator("timestamp")
    def normalize_timestamp_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(tz=UTC)


class PredictionResponse(BaseModel):
    station_id: int
    target_timestamp: AwareDatetime = Field(..., description="Instant prédit (t + 1 h)")
    predicted_bikes: float = Field(..., ge=0)
    model_version: str


# STRETCH : BatchPredictionRequest (1 à 1000 PredictionRequest) et BatchPredictionResponse
class BatchPredictionRequest(BaseModel):
    items: list[PredictionRequest] = Field(..., min_length=1, max_length=1000)


class BatchPredictionResponse(BaseModel):
    predictions: list[PredictionResponse]