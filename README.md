# velov-mlops

Projet fil rouge du cours **Industrialisation de l'IA dans le Cloud** (M2 Data Engineering / IA).

Objectif métier : prédire, pour chaque station Vélo'v, le nombre de vélos disponibles **dans une heure**,
et servir cette prédiction via une API fiable, conteneurisée, puis déployée (on-premise et cloud).

## Progression par session

Chaque étape du cours correspond à un tag git. Absent ou bloqué : repartez du tag de fin de la session précédente.

| Tag | Contenu |
|---|---|
| `s1-start` | Données simulées, features, entraînement. API à compléter (TP1) |
| `s1-end` | Modèle v0 servi par FastAPI, tests pytest |

```bash
git checkout s1-end          # récupérer l'état de fin de S1
git checkout -b mon-binome   # travailler sur sa propre branche
```

## Démarrage rapide

Prérequis : Python 3.11+ (3.12 recommandé), git. Docker sera nécessaire en S2.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
pip install -e .                     # rend le package velov importable

python -m velov.data                 # génère data/velov_history.csv (simulateur, seed fixe)
python -m velov.train                # entraîne et écrit models/model.joblib + models/metadata.json
python -m velov.train --mlflow       # idem + journalisation MLflow (puis : mlflow ui)
pytest                               # tests
uvicorn velov.api.main:app --reload  # API sur http://127.0.0.1:8000/docs (--reload : en dev uniquement)
```

### Ingestion des données réelles

Le projet sépare les fonctions de téléchargement dans `velov.ingest` des deux
orchestrations qui les utilisent :

```bash
# Reconstituer les 90 derniers jours disponibles pour l'entraînement
python -m velov.build_training_data --days 90 --output-dir data/bronze

# Collecter un seul lot temps réel (à planifier toutes les cinq minutes)
python -m velov.run_microbatch --output-dir data/bronze
```

Le premier parcours l'API historique Vélo'v jour par jour, suit sa pagination,
enregistre les réponses JSON brutes et déduplique les lignes normalisées avec
`(station_id, timestamp)`. Il récupère aussi la météo horaire historique
d'Open-Meteo. Le relancer reconstruit la fenêtre à partir de la date la plus
récente réellement publiée par la source et ne crée pas de doublons.

Le second lit le flux GBFS courant et la météo récente. Le planificateur
externe doit lancer cette commande toutes les cinq minutes. Les sorties sont
écrites dans `data/bronze/` (répertoire ignoré par git).

Les fonctions partagées de `velov.ingest` récupèrent et normalisent également
les informations de stations, l'état des stations et la météo lorsque ces
fonctions sont utilisées par un orchestrateur.

Les observations temps réel sont conservées en bronze puis agrégées en heures
dans le pipeline dbt. Leur clé d'idempotence est `(station_id, last_reported)`.
La clé d'une ligne historique est `(station_id, timestamp)`.

Exemple d'appel :

```bash
curl -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"station_id": 3, "timestamp": "2026-10-06T08:00:00+02:00", "capacity": 20,
       "bikes_available": 12, "temperature": 14.5, "is_raining": false}'
```

Le `timestamp` doit porter un fuseau (`+02:00`, `Z`...) : sans fuseau, l'API répond 422.
Les instants sont renvoyés et journalisés en UTC (`"target_timestamp": "2026-10-06T07:00:00Z"`).

## Exigences du projet

Le service doit respecter les exigences de [docs/exigences.md](docs/exigences.md), de S1 à S9.
Chaque rendu indique celles qu'il couvre et comment le vérifier.

### Pipeline TP3

Le pipeline suit les couches médaillon :

```text
data/bronze/ (JSON source conservés tels que reçus)
    -> velov_dbt/models/staging/ (silver typé et dédoublonné)
    -> velov_dbt/models/marts/station_hourly.sql (gold horaire sous contrat)
    -> dbt tests (qualité et absence de fuite temporelle)
    -> train.py --gold-db data/velov.duckdb (validation Pandera avant entraînement)
```

Depuis la racine du dépôt, après installation des dépendances de développement :

```bash
cd velov_dbt
dbt build --vars '{"bronze_path": "../data/bronze"}'
python -m velov.train --gold-db data/velov.duckdb
```

Le modèle gold est publié uniquement si son contrat dbt et ses tests passent.
La preuve de l'idempotence bronze se trouve dans
[evidence/bronze-idempotency.txt](evidence/bronze-idempotency.txt).

> **Politique de seuil à revoir :** le test `bikes_within_capacity` est
> actuellement bloquant : une seule ligne invalide fait échouer `dbt build` et
> empêche la publication de la table gold. Les diapositives du TP3 mentionnent
> une politique possible avec les seuils `warn_if`/`error_if` (par exemple, un
> avertissement pour un petit nombre d'anomalies). Cette politique n'est pas
> encore activée, car EX-12 interdit de publier une table gold invalide. Il
> faudra la revoir à la lumière des exigences métier et pédagogiques avant de
> la modifier.


## Structure

```
src/velov/
  data.py          simulateur de données (remplacé par l'open data en S3, même schéma)
  ingest.py        fetchers et parseurs partagés
  build_training_data.py  backfill historique et fenêtre d'entraînement
  run_microbatch.py        collecte d'un lot temps réel
  features.py      features partagées entraînement / API (anti training-serving skew)
  train.py         entraînement, baseline, artefact + metadata.json, option MLflow
  api/main.py      FastAPI : /health, /ready, /v1/model, /v1/predict, /v1/predict/batch
  api/schemas.py   contrat d'entrée / sortie (Pydantic)
tests/             pytest (features, API)
docs/              templates : model card, runbook, ADR
exercices/         démo pickle (S1)
```

Sur Windows, `run_microbatch` peut être lancé par le Planificateur de tâches
toutes les cinq minutes. Cela ne collecte rien pendant l'arrêt ou la veille de
la machine ; pour une série continue, déployer la même commande sur une VM
allumée en permanence. Une exécution manuelle reste utile après une période
d'arrêt, car l'idempotence évite les doublons lors d'un rattrapage.

## Usage de l'IA générative

Chaque activité indique son mode : **sans IA**, **IA déclarée** ou **IA imposée**.
En mode IA déclarée, ajoutez dans la description de vos commits ou de votre rendu :
outil utilisé, ce que vous lui avez demandé, ce que vous avez vérifié ou corrigé.
