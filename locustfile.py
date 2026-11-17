"""Scénario Locust de référence pour mesurer POST /v1/predict."""

from locust import HttpUser, between, task


class PredictionUser(HttpUser):
    """Utilisateur virtuel envoyant des observations réalistes."""

    wait_time = between(0.5, 1.0)

    payload = {
        "station_id": 2,
        "timestamp": "2026-10-06T08:00:00+02:00",
        "capacity": 20,
        "bikes_available": 12,
        "temperature": 14.5,
        "is_raining": False,
    }

    @task
    def predict(self) -> None:
        """Mesure une prédiction complète, y compris sa persistance éventuelle."""
        with self.client.post(
            "/v1/predict",
            json=self.payload,
            name="POST /v1/predict",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"Statut HTTP inattendu: {response.status_code}")
                return

            try:
                body = response.json()
            except ValueError:
                response.failure("La réponse n'est pas un JSON valide")
                return

            required_fields = {
                "station_id",
                "target_timestamp",
                "predicted_bikes",
                "model_version",
            }
            missing_fields = required_fields.difference(body)
            if missing_fields:
                response.failure(f"Champs manquants: {sorted(missing_fields)}")
