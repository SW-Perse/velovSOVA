"""Tests de l'API. Les fixtures (client, valid_payload, model_dir) sont dans conftest.py.

TODO 8 [Must] : faire passer les deux tests ci-dessous (une prédiction valide, une entrée invalide). ✓
TODO 9 [Should] : en ajouter d'autres, par exemple :
  - /health renvoie 200 et /ready 503 quand MODEL_DIR pointe vers un dossier vide 
  - un champ inconnu renvoie 422 ✓
  - un timestamp sans fuseau ("2026-10-06T08:00:00") renvoie 422 ✓
  - la prédiction est comprise entre 0 et capacity ✓
  - (Stretch) une station jamais vue à l'entraînement ne fait pas planter l'API
"""

from datetime import UTC, datetime
from fastapi.testclient import TestClient
from velov.api.main import STATE, app


def test_predict_valid(client, valid_payload):
    r = client.post("/v1/predict", json=valid_payload)
    assert r.status_code == 200
    # 8 h à Lyon (+02:00) + 1 h = 7 h UTC, quel que soit le fuseau dans lequel l'API répond
    target = datetime.fromisoformat(r.json()["target_timestamp"])
    assert target == datetime(2026, 10, 6, 7, tzinfo=UTC)


def test_predict_rejects_bikes_above_capacity(client, valid_payload):
    r = client.post("/v1/predict", json={**valid_payload, "bikes_available": 25})
    assert r.status_code == 422


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

def test_ready_ok(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"
    assert "model_version" in r.json()

def test_ready_returns_503(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_DIR", str(tmp_path))
    with TestClient(app) as c:
        r = c.get("/ready")
        assert r.status_code == 503

# Un champ inconnu renvoie 422 (grâce à extra="forbid")
def test_predict_rejects_unknown_field(client, valid_payload):
    payload_with_extra = {**valid_payload, "extra_field": "valeur_inattendue"}
    r = client.post("/v1/predict", json=payload_with_extra)
    assert r.status_code == 422


# Un timestamp sans fuseau horaire renvoie 422 (AwareDatetime)
def test_predict_rejects_naive_timestamp(client, valid_payload):
    payload_naive_time = {**valid_payload, "timestamp": "2026-10-06T08:00:00"}
    r = client.post("/v1/predict", json=payload_naive_time)
    assert r.status_code == 422


# La prédiction est strictement bornée entre 0 et capacity
def test_predict_bounds_between_zero_and_capacity(client, valid_payload):
    r = client.post("/v1/predict", json=valid_payload)
    assert r.status_code == 200
    pred = r.json()["predicted_bikes"]
    assert 0.0 <= pred <= float(valid_payload["capacity"])


# (Stretch) une station jamais vue à l'entraînement ne fait pas planter l'API
def test_predict_unseen_station_does_not_crash(client, valid_payload):
    # On prend un ID arbitrairement très grand qui n'existe pas dans le jeu d'entraînement
    payload_unseen_station = {**valid_payload, "station_id": 999_999}
    
    r = client.post("/v1/predict", json=payload_unseen_station)
    
    # L'API doit répondre 200 avec une prédiction valide
    assert r.status_code == 200
    data = r.json()
    assert "predicted_bikes" in data
    assert 0.0 <= data["predicted_bikes"] <= float(payload_unseen_station["capacity"])