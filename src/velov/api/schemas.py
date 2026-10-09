"""Contrat d'entrée / sortie de l'API (validé par Pydantic, publié dans OpenAPI).

TP1, partie 2 : complétez les schémas. Mode : SANS IA pour cette partie.
"""

from __future__ import annotations

from datetime import UTC

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class PredictionRequest(BaseModel):
    """Une observation de station à l'instant t.

    TODO 1 [Must] : déclarer les 6 champs attendus par le modèle (voir velov.features.RAW_COLUMNS)
             avec leur type Python. Pour timestamp, utilisez AwareDatetime et non datetime :
             datetime accepte "2026-10-06T08:00:00" sans fuseau, un instant ambigu.
    TODO 2 [Must] : ajouter des bornes avec Field(...) : station_id >= 1, 0 < capacity <= 100,
             bikes_available >= 0, température entre -30 et 50 °C.
    TODO 3 [Must] : refuser un champ inconnu (indice : model_config / extra).
    TODO 4 [Must] : refuser bikes_available > capacity (indice : @model_validator(mode="after")).
    TODO 4 bis [Should] : normaliser timestamp en UTC
             (indice : @field_validator("timestamp") et value.astimezone(UTC)).
    """

    model_config = ConfigDict(extra="forbid") # TODO 3 model_config / extra

    # TODO 1 et 2
    station_id: int = Field(..., description="Identifiant de la station", ge=1)
    timestamp: AwareDatetime = Field(..., description="Date/heure avec fuseau obligatoire")
    capacity: int = Field(..., description="nombre total de bornes", gt=0, le=100)
    bikes_available: int = Field(..., description="vélos actuellement disponibles", ge=0)
    temperature: float = Field(..., description="température en °C", ge=-30, le=50)
    is_raining: bool = Field(..., description="indique s'il pleut")

    # TODO 4
    @model_validator(mode="after")
    def check_bikes_do_not_exceed_capacity(self):
        if self.bikes_available > self.capacity:
            raise ValueError("bikes_available ne peut pas dépasser capacity")
        return self

    # TODO 4 bis
    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp_to_utc(cls, value: AwareDatetime) -> AwareDatetime: # -> AwareDatetime Permet de dire au développeur que la sortie attendu est de type "AwareDatetime"
        return value.astimezone(UTC)

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