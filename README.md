# velov-mlops

Projet fil rouge du cours **Industrialisation de l'IA dans le Cloud** (M2 Data Engineering / IA).

Objectif métier : prédire, pour chaque station Vélo'v, le nombre de vélos disponibles **dans une heure**, et servir cette prédiction via une API fiable, conteneurisée, puis déployée (on-premise et cloud).

---

## 1. Démarrage rapide & progression

Prérequis : Python 3.11+ (3.12 recommandé), git et Docker Desktop.

### Progression par session

Chaque étape du cours correspond à un tag git. Absent ou bloqué : repartez du tag de fin de la session précédente.

| Tag | Contenu |
|---|---|
| `s1-start` | Données simulées, features, entraînement. API à compléter (TP1) |
| `s1-end` | Modèle v0 servi par FastAPI, tests pytest |

Commandes identiques en **Bash** et en **PowerShell** :

```bash
git checkout s1-end          # récupérer l'état de fin de S1
git checkout -b mon-binome   # travailler sur sa propre branche
```

### Installation et lancement local

**Bash**

```bash
python -m venv .venv
source .venv/bin/activate            # Linux / macOS
pip install -r requirements-dev.txt
pip install -e .                     # rend le package velov importable

python -m velov.data                 # génère data/velov_history.csv (simulateur, seed fixe)
python -m velov.train                # entraîne et écrit models/model.joblib + models/metadata.json
docker compose up -d                 # démarre PostgreSQL, MLflow et l'API
pytest                               # tests unitaires et API
uvicorn velov.api.main:app --reload  # API sur http://127.0.0.1:8000/docs (--reload : en dev uniquement)
```

**PowerShell**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1           # Windows
pip install -r requirements-dev.txt
pip install -e .                     # rend le package velov importable

python -m velov.data                 # génère data/velov_history.csv (simulateur, seed fixe)
python -m velov.train                # entraîne et écrit models/model.joblib + models/metadata.json
docker compose up -d                 # démarre PostgreSQL, MLflow et l'API
pytest                               # tests unitaires et API
uvicorn velov.api.main:app --reload  # API sur http://127.0.0.1:8000/docs (--reload : en dev uniquement)
```

### Exemple d'appel à l'API

Le `timestamp` doit obligatoirement contenir un fuseau horaire (`+02:00`, `Z`, ...), sinon erreur 422. Les réponses sont renvoyées et journalisées en UTC.

**Bash**

```bash
curl -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"station_id": 3, "timestamp": "2026-10-06T08:00:00+02:00", "capacity": 20, "bikes_available": 12, "temperature": 14.5, "is_raining": false}'
```

**PowerShell**

```powershell
$body = '{"station_id": 3, "timestamp": "2026-10-06T08:00:00+02:00", "capacity": 20, "bikes_available": 12, "temperature": 14.5, "is_raining": false}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/predict `
  -ContentType "application/json" `
  -Body $body
```

---

## 2. Structure du dépôt

```text
src/velov/
  data.py                  simulateur de données (remplacé par l'open data en S3, même schéma)
  ingest.py                fetchers et parseurs partagés (Open Data / GBFS / Météo)
  build_training_data.py   backfill historique et fenêtre d'entraînement
  run_microbatch.py        collecte d'un lot temps réel (micro-batchs)
  features.py              features partagées entraînement / API (anti training-serving skew)
  train.py                 entraînement, baseline, artefact + metadata.json, option MLflow
  api/main.py              FastAPI : /health, /ready, /v1/model, /v1/predict, /v1/predict/batch
  api/schemas.py           contrat d'entrée / sortie (Pydantic)
tests/                     pytest (features, API, intégration MLflow)
docs/                      templates : model card, runbook, ADR
velov_dbt/                 pipeline dbt (couches médaillon silver/gold)
exercices/                 démo pickle (S1), audit test de charge (S5)
```

---

## 3. Ingestion des données & Pipeline dbt (S3)

### Collecte des données réelles

Le projet sépare les fonctions de téléchargement (`velov.ingest`) des deux orchestrations (commandes ci-dessous).

Le premier parcours l'API historique Vélo'v jour par jour, suit sa pagination, enregistre les réponses JSON brutes et déduplique les lignes normalisées avec `(station_id, timestamp)`. Il récupère aussi la météo horaire historique d'Open-Meteo. Le relancer reconstruit la fenêtre à partir de la date la plus récente réellement publiée par la source et ne crée pas de doublons.

Le second lit le flux GBFS courant et la météo récente. Le planificateur externe doit lancer cette commande toutes les cinq minutes. Les sorties sont écrites dans `data/bronze/` (répertoire ignoré par git).

Les fonctions partagées de `velov.ingest` récupèrent et normalisent également les informations de stations, l'état des stations et la météo lorsqu'elles sont utilisées par un orchestrateur.

Commandes identiques en **Bash** et en **PowerShell** :

```bash
# Reconstituer les 90 derniers jours disponibles pour l'entraînement
python -m velov.build_training_data --days 90 --output-dir data/bronze

# Collecter un seul lot temps réel (à planifier toutes les 5 minutes)
python -m velov.run_microbatch --output-dir data/bronze
```

- **Idempotence** : clé `(station_id, timestamp)` pour l'historique et `(station_id, last_reported)` pour le temps réel. Preuve conservée dans [`evidence/bronze-idempotency.txt`](evidence/bronze-idempotency.txt).
- **Planification Windows** : `run_microbatch` peut être exécuté via le Planificateur de tâches toutes les cinq minutes. Cela ne collecte rien pendant l'arrêt ou la veille de la machine ; pour une série continue, déployer la même commande sur une VM allumée en permanence. Une exécution manuelle reste utile après une période d'arrêt, car l'idempotence évite les doublons lors d'un rattrapage.

### Pipeline médaillon dbt

```text
data/bronze/ (JSON source conservés tels que reçus)
    -> velov_dbt/models/staging/ (silver typé et dédoublonné)
    -> velov_dbt/models/marts/station_hourly.sql (gold horaire sous contrat)
    -> dbt tests (qualité et absence de fuite temporelle)
    -> train.py --gold-db data/velov.duckdb (validation Pandera avant entraînement)
```

Exécution depuis la racine du dépôt :

**Bash**

```bash
cd velov_dbt
dbt build --vars '{"bronze_path": "../data/bronze"}'
python -m velov.train --gold-db data/velov.duckdb
```

**PowerShell**

```powershell
cd velov_dbt
dbt build --vars "{'bronze_path': '../data/bronze'}"
python -m velov.train --gold-db data/velov.duckdb
```

Le modèle gold est publié uniquement si son contrat dbt et ses tests passent. La preuve de l'idempotence bronze se trouve dans [`evidence/bronze-idempotency.txt`](evidence/bronze-idempotency.txt).

> **Politique de seuil à revoir** : le test `bikes_within_capacity` est actuellement bloquant : une seule ligne invalide fait échouer `dbt build` et empêche la publication de la table gold. Les diapositives du TP3 mentionnent une politique possible avec les seuils `warn_if` / `error_if` (par exemple, un avertissement pour un petit nombre d'anomalies). Cette politique n'est pas encore activée, car EX-12 interdit de publier une table gold invalide. Il faudra la revoir à la lumière des exigences métier et pédagogiques avant de la modifier.

---

## 4. Suivi MLflow, Registre & Promotion (S4)

Après `docker compose up -d`, l'interface MLflow est disponible sur <http://localhost:5000>. PostgreSQL conserve les prédictions de l'API dans `velov_db` et les métadonnées MLflow dans `mlflow` (artefacts dans le volume `mlflow_artifacts`).
Le service `mlflow-db-init` crée et migre les tables MLflow avant le démarrage du serveur.

### Entraînement avec journalisation MLflow

Depuis la machine hôte (URL interne depuis Docker : `http://mlflow:5000`) :

**Bash**

```bash
export MLFLOW_TRACKING_URI="http://localhost:5000"
python -m velov.train --mlflow
```

**PowerShell**

```powershell
$env:MLFLOW_TRACKING_URI = "http://localhost:5000"
python -m velov.train --mlflow
```

Chaque run conserve :

- les **paramètres** : `model_version`, `test_days`, `seed`, `learning_rate`, `max_iter` ;
- les **métriques** : `mae_model`, `mae_baseline_persistence`, `mae_model_peak_hours` (heures de pointe à Lyon 07:00–09:59 et 17:00–19:59 Europe/Paris) ;
- les **tags de traçabilité** : `git_commit`, `git_dirty`, `data_sha256`, `data_period_start`, `data_period_end` ;
- le **modèle sérialisé** avec signature et le paquet `model-package/` (`model.joblib` + `metadata.json`).

### Règle de promotion (`velov-availability`)

- **Fenêtre identique** : challenger et champion évalués sur exactement la même fenêtre (`evaluation_period_start` / `evaluation_period_end`, 14 derniers jours par défaut).
- **Critère 1 (Baseline)** : `mae_model < mae_baseline_persistence`.
- **Critère 2 (Gain minimal)** : si un champion existe déjà, amélioration d'au moins 2 % (`challenger_mae <= champion_mae * 0.98`).

- Le modèle enregistré s'appelle `velov-availability`. C'est le nom de la famille dans le Model Registry ; chaque version numérotée correspond à un run MLflow et à un modèle entraîné concret.
- `challenger` désigne la version candidate à évaluer, `champion` la version actuellement retenue comme meilleure.
- La durée de la fenêtre d'évaluation (14 jours par défaut, les derniers du jeu de données) est le paramètre `test_days`.
- Sans champion, un challenger qui bat la persistance devient éligible comme premier champion.

La différence entre deux seeds du même modèle mesure la variabilité expérimentale. Elle aide à justifier un seuil supérieur au bruit observé, mais elle ne remplace pas la règle fixe de 2 % et ne sert pas directement de seuil de promotion.

### Commandes de registre et de promotion

**Bash**

```bash
export MLFLOW_TRACKING_URI="http://localhost:5000"
python -m velov.registry --run-id <run-id>   # enregistre et pose l'alias challenger
python -m velov.promote                      # dry-run : vérifie la règle et audite les tags (eligible / rejected)
python -m velov.promote --apply              # déplace explicitement l'alias champion après validation humaine
```

**PowerShell**

```powershell
$env:MLFLOW_TRACKING_URI = "http://localhost:5000"
python -m velov.registry --run-id <run-id>   # enregistre et pose l'alias challenger
python -m velov.promote                      # dry-run : vérifie la règle et audite les tags (eligible / rejected)
python -m velov.promote --apply              # déplace explicitement l'alias champion après validation humaine
```

`python -m velov.promote` est un dry-run : il vérifie la fenêtre d'évaluation, la comparaison à la persistance et le gain minimal de 2 % sur le champion, puis affiche la décision sans modifier le registre. `--apply` ne rend pas la décision automatique : après validation humaine, il autorise uniquement le déplacement explicite de l'alias champion vers le challenger, et seulement si la règle autorise la promotion.

L'interface MLflow sert à consulter les runs, métriques, tags, artefacts et alias ; la commande est le point d'application contrôlé de la règle.

Chaque décision est auditée sur le run challenger avec les tags `promotion_decision`, `promotion_reason`, `promotion_previous_champion` et `promotion_rule_version`. Une décision positive en dry-run est marquée `eligible`, puis devient `promoted` seulement après `--apply` ; une décision négative est marquée `rejected`.

---

## 5. Performance, tests de charge & optimisation (TP5)

### 5.1 Protocole de mesure locale

- **Endpoint testé** : la mesure de référence porte sur `POST /v1/predict`. Elle utilise le modèle chargé et le chemin complet de l'API, y compris l'écriture de la prédiction dans PostgreSQL lorsqu'une `DATABASE_URL` est configurée. Le scénario Locust est dans `locustfile.py` et réutilise toujours le même payload valide fixe.
- **Configuration API** : Docker sans `--reload`, 1 seul worker Uvicorn, limite Docker stricte à 1 cœur CPU (`--cpus 1`). Ces réglages sont définis dans le service `api` de `docker-compose.yml`.
- **Générateur de charge** : Locust (`locustfile.py`) exécuté sur la machine hôte (hors conteneur API) pour que la limite CPU s'applique bien au service testé et non au générateur de charge.
- **Conditions d'exécution** : campagne du 17 novembre 2026, poste sur secteur, services locaux inutiles arrêtés.

**Validation initiale (smoke test)**

Le test court ci-dessous précède toute campagne plus longue : `/ready` doit répondre `200`, Locust doit afficher `0` requête échouée, et les fichiers CSV/HTML doivent être conservés localement. Pour une campagne reproductible, noter le commit, le modèle, le nombre d'utilisateurs, le débit de lancement, la durée, le nombre de workers et la limite CPU. Les résultats Locust donnent notamment le débit, le taux d'erreur et les percentiles p50, p95 et p99 de latence.

Prérequis : avoir créé `.env` et généré le modèle.

**Bash**

```bash
docker compose up -d --build
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
python -m pip install -r requirements-dev.txt
mkdir -p locust-results
locust --headless --locustfile locustfile.py \
  --host http://127.0.0.1:8000 \
  --users 10 --spawn-rate 2 --run-time 1m \
  --csv locust-results/tp5-smoke --html locust-results/tp5-smoke.html
docker compose ps api
docker compose down
```

**PowerShell**

```powershell
docker compose up -d --build
Invoke-WebRequest http://127.0.0.1:8000/health
Invoke-WebRequest http://127.0.0.1:8000/ready
python -m pip install -r requirements-dev.txt
New-Item -ItemType Directory -Force locust-results
locust --headless --locustfile locustfile.py `
  --host http://127.0.0.1:8000 `
  --users 10 --spawn-rate 2 --run-time 1m `
  --csv locust-results/tp5-smoke --html locust-results/tp5-smoke.html
docker compose ps api
docker compose down
```

### 5.2 Courbe de saturation & Capacité sous le SLO

- **SLO visé** : p95 < 200 ms et taux d'erreur < 0,1 %.
- **Protocole** : 1 minute d'échauffement puis 5 paliers de 2 minutes chacun (10, 25, 50, 100, 150 usagers) via le script `loadtest/paliers.ps1`.

La campagne complète mesure cinq paliers après une minute d'échauffement. Chaque palier dure deux minutes et produit les fichiers bruts Locust dans `locust-results/tp5-saturation`. Le scénario vérifie le statut HTTP et le contrat JSON de chaque prédiction : une réponse invalide est donc comptée comme une erreur.

L'API doit rester sur un worker et un cœur (`docker-compose.yml`), et Locust sur la machine hôte, avec l'API prête avant de lancer le script. Les paramètres peuvent être adaptés sans modifier le protocole de référence :

**Bash** (nécessite PowerShell Core, `pwsh`)

```bash
pwsh ./loadtest/paliers.ps1 -HostUrl http://127.0.0.1:8000 \
  -ResultsDirectory locust-results/tp5-saturation
```

**PowerShell**

```powershell
.\loadtest\paliers.ps1 -HostUrl http://127.0.0.1:8000 `
  -ResultsDirectory locust-results\tp5-saturation
```

Le rapport [`saturation-summary.md`](locust-results/tp5-saturation/saturation-summary.md) et le graphique [`saturation-summary.svg`](locust-results/tp5-saturation/saturation-summary.svg) sont générés automatiquement. La capacité sous le SLO est le débit du dernier palier dont le p95 reste inférieur à 200 ms et dont le taux d'erreur reste inférieur à 0,1 %. Le rapport indique aussi le premier palier qui dépasse le SLO. Les résultats doivent être accompagnés, dans le rendu, du commit, du modèle, de la machine, des versions, de la limite CPU et de l'heure de mesure.

| Utilisateurs | p50 (ms) | p95 (ms) | p99 (ms) | Débit (req/s) | Erreurs | SLO |
|---:|---:|---:|---:|---:|---:|---|
| 10 | 61 | 75 | 94 | 12,21 | 0,000 % | Respecté |
| 25 | 64 | 110 | 170 | 30,31 | 0,000 % | Respecté |
| 50 | 100 | 350 | 560 | 55,49 | 0,000 % | Dépassé |
| 100 | 940 | 1400 | 1600 | 59,09 | 0,000 % | Dépassé |
| 150 | 1700 | 2100 | 3000 | 59,02 | 0,000 % | Dépassé |

- **Capacité mesurée sous le SLO** : 30,31 req/s (au palier de 25 utilisateurs).
- **Premier dépassement du SLO** : 50 utilisateurs (p95 à 350 ms).
- **Preuves & graphique** : [`saturation-summary.md`](locust-results/tp5-saturation/saturation-summary.md) et [`saturation-summary.svg`](locust-results/tp5-saturation/saturation-summary.svg).
- **Ressources à saturation (50 usagers)** : CPU API jusqu'à 94,16 % (~164 MiB RAM) contre < 15 % CPU pour Locust ([`tp5-api-stats-50-users.txt`](evidence/tp5-api-stats-50-users.txt), [`tp5-locust-stats-50-users.txt`](evidence/tp5-locust-stats-50-users.txt), `saturation-summary.md`).

La courbe complète est disponible dans [`saturation-summary.svg`](locust-results/tp5-saturation/saturation-summary.svg) et le tableau détaillé dans [`saturation-summary.md`](locust-results/tp5-saturation/saturation-summary.md).

![Courbe de saturation](image.png)

Une campagne ciblée à 50 utilisateurs a également servi à documenter les ressources au moment de la saturation. Elle a mesuré un p95 de 540 ms, un débit de 51,32 req/s et zéro erreur. Les échantillons `docker stats` montrent un CPU API jusqu'à 94,16 % et environ 164 MiB de mémoire, tandis que le processus Python enfant de Locust est resté sous 15 % CPU. Ces mesures confirment que le goulot est l'API, et non le générateur de charge : [`tp5-api-stats-50-users.txt`](evidence/tp5-api-stats-50-users.txt), [`tp5-locust-stats-50-users.txt`](evidence/tp5-locust-stats-50-users.txt) et `saturation-summary-50.md` (locust-results\tp5-saturation-50\saturation-summary-50.md).

### 5.3 Analyse du goulot par étape

Le temps total de traitement est exposé par l'en-tête `X-Process-Time-Ms`. Une vérification HTTP peut être faite avec :

**Bash**

```bash
curl -i -X POST http://127.0.0.1:8000/v1/predict \
  -H "Content-Type: application/json" \
  -d '{"station_id":3,"timestamp":"2026-10-06T08:00:00+02:00","capacity":20,"bikes_available":12,"temperature":14.5,"is_raining":false}'
```

**PowerShell**

```powershell
curl.exe -i -X POST http://127.0.0.1:8000/v1/predict `
  -H "Content-Type: application/json" `
  -d '{"station_id":3,"timestamp":"2026-10-06T08:00:00+02:00","capacity":20,"bikes_available":12,"temperature":14.5,"is_raining":false}'
```

Le benchmark interne mesure les features, l'inférence et le post-traitement sans réseau ni écriture PostgreSQL. Sa sortie de référence est conservée dans [`tp5-bench-predict.txt`](evidence/tp5-bench-predict.txt). Commande :

**Bash**

```bash
python scripts/bench_predict.py --batch 1 100 1000 --runs 30 | tee evidence/tp5-bench-predict.txt
```

**PowerShell**

```powershell
python scripts\bench_predict.py --batch 1 100 1000 --runs 30 |
  Tee-Object -FilePath evidence\tp5-bench-predict.txt
```

Benchmark interne sans réseau ni base (`scripts/bench_predict.py`, 30 runs) — `tp5-bench-predict.txt` :

| Étape mesurée | Batch | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|
| `add_features` | 1 | 3,959 | 4,610 |
| `model.predict` | 1 | 5,011 | 5,891 |
| Post-traitement | 1 | 0,054 | 0,068 |
| **Total `_predict()`** | 1 | 9,055 | 10,302 |
| `add_features` | 100 | 5,286 | 6,007 |
| `model.predict` | 100 | 6,035 | 7,241 |
| Post-traitement | 100 | 1,040 | 1,502 |
| **Total `_predict()`** | 100 | 12,451 | 13,978 |
| `add_features` | 1000 | 10,403 | 12,824 |
| `model.predict` | 1000 | 7,083 | 7,963 |
| Post-traitement | 1000 | 8,194 | 9,971 |
| **Total `_predict()`** | 1000 | 26,053 | 29,868 |

Le temps API est mesuré par `X-Process-Time-Ms`, qui couvre `_predict()` et l'écriture PostgreSQL. Les 30 valeurs brutes sont conservées dans [`tp5-api-timings-ms.txt`](evidence/tp5-api-timings-ms.txt). Comparaison interne vs serveur vs réseau (Locust) :

| Mesure | Échantillon | p50 (ms) | p95 (ms) | Source |
|---|---|---:|---:|---|
| Interne `_predict()` (batch 1) | 30 runs | 9,055 | 10,302 | `tp5-bench-predict.txt` |
| Temps serveur `X-Process-Time-Ms` | 30 requêtes | 12,702 | 14,375 | `tp5-api-timings-ms.txt` |
| Latence Locust (10 usagers) | campagne 2 min | 61,000 | 75,000 | `saturation-summary.md` |

Le p50 mesuré par Locust à 10 usagers (61 ms) est nettement plus élevé que le p50 mesuré par l'API elle-même via `X-Process-Time-Ms` (12,702 ms) : l'écart est d'environ 48,3 ms. Ces deux mesures ne regardent pas la même chose. `X-Process-Time-Ms` est calculé à l'intérieur du serveur (validation, prédiction, écriture PostgreSQL) et ne compte ni le trajet HTTP ni l'attente éventuelle. Locust mesure depuis l'extérieur, du moment où la requête part jusqu'à la réception complète de la réponse : il inclut donc aussi le réseau local, la gestion HTTP et le temps passé en file d'attente quand plusieurs requêtes arrivent en même temps sur un seul cœur CPU.

Cet écart ne doit toutefois pas être lu comme le « coût du réseau » d'une requête. Les deux valeurs viennent de deux campagnes différentes : 30 requêtes envoyées une par une pour `X-Process-Time-Ms`, contre 2 minutes de charge à 10 utilisateurs simultanés pour Locust. Une partie de l'écart provient donc de la concurrence, et l'écart ne donne qu'un ordre de grandeur de ce que le chemin HTTP et la charge ajoutent au temps de traitement du serveur.

> Note : une première requête à froid a été observée séparément à 1807,512 ms dans `tp5-api-header.txt`.

**Conclusion**

- **Goulot interne (`_predict()`)** : pour une requête unitaire, le temps est principalement consommé par l'inférence du modèle (`model.predict` : p50 de 5,011 ms) combinée à la construction des features (`add_features` : p50 de 3,959 ms). Le post-traitement est négligeable (0,054 ms).
- **Coût de l'enveloppe API et base de données** : l'écart entre le traitement interne (9,055 ms) et le temps mesuré par l'en-tête `X-Process-Time-Ms` (12,702 ms) montre que la validation et l'écriture en base PostgreSQL ajoutent un surcoût faible et stable d'environ 3,65 ms par requête.
- **Passage à l'échelle et saturation CPU** : le traitement par lots (batching) s'amortit très bien (seulement 26,053 ms pour 1 000 lignes, où `add_features` devient l'étape la plus coûteuse avec 10,403 ms). En revanche, sur des requêtes unitaires concurrentes (écart de 48,298 ms entre `X-Process-Time-Ms` et Locust à 10 usagers dû au chemin HTTP et à la concurrence), le cœur CPU unique de l'API sature (jusqu'à 94,16 % à 50 usagers, tandis que Locust reste sous 15 %). Le débit plafonne ainsi autour de 59 req/s, provoquant une mise en file d'attente des requêtes et l'explosion de la latence. Ces mesures prouvent que le calcul API, et non le générateur de charge, limite la capacité.

### 5.4 Comparaison après modification unique (2 workers / 2 cœurs)

La seule modification appliquée est le passage de l'API de un à deux workers Uvicorn et d'une à deux unités CPU. Le modèle, le payload, le scénario Locust, la base PostgreSQL, la machine hôte et les paliers sont restés identiques. L'override est [`compose.workers.yaml`](compose.workers.yaml) et les commandes utilisées sont :

**Bash**

```bash
docker compose -f docker-compose.yml -f compose.workers.yaml up -d --build api
api_id=$(docker compose -f docker-compose.yml -f compose.workers.yaml ps -q api)
docker update --cpus 2 "$api_id"
pwsh ./loadtest/paliers.ps1 -HostUrl http://localhost:8000 -ResultsDirectory locust-results/w2
```

**PowerShell**

```powershell
docker compose -f docker-compose.yml -f compose.workers.yaml up -d --build api
$apiId = (docker compose -f docker-compose.yml -f compose.workers.yaml ps -q api).Trim()
docker update --cpus 2 $apiId
.\loadtest\paliers.ps1 -HostUrl http://localhost:8000 -ResultsDirectory locust-results\w2
```

| Utilisateurs | p50 1w/1c (ms) | p95 1w/1c (ms) | Débit 1w/1c (req/s) | p50 2w/2c (ms) | p95 2w/2c (ms) | Débit 2w/2c (req/s) | Erreurs 2w/2c | SLO 2w/2c |
|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 10 | 61 | 75 | 12,21 | 63 | 81 | 12,27 | 0,000 % | Respecté |
| 25 | 64 | 110 | 30,31 | 62 | 88 | 30,25 | 0,000 % | Respecté |
| 50 | 100 | 350 | 55,49 | 130 | 810 | 49,67 | 0,000 % | Dépassé |
| 100 | 940 | 1400 | 59,09 | 1200 | 1800 | 49,54 | 0,000 % | Dépassé |
| 150 | 1700 | 2100 | 59,02 | 2200 | 2800 | 48,95 | 0,000 % | Dépassé |

**La capacité sous le SLO ne double pas.** Elle passe de 30,31 req/s à 30,25 req/s au palier de 25 utilisateurs, soit une variation négligeable de −0,20 %. Aux paliers saturés, le débit est même inférieur avec deux workers (49,67 req/s contre 55,49 req/s à 50 utilisateurs). Deux workers et deux cœurs ne suppriment donc pas le goulot dans ce protocole : la capacité mesurée reste limitée par le chemin API et ses dépendances.

La mémoire augmente presque proportionnellement au nombre de workers : `docker stats` mesure environ 164 MiB pour la configuration 1 worker / 1 cœur et jusqu'à 316,6 MiB pour 2 workers / 2 cœurs, soit environ 1,93×. Le CPU API atteint 204,87 %, ce qui confirme que les deux cœurs sont utilisés. Les rapports Locust bruts sont conservés dans [`evidence/tp5-saturation-w2/`](evidence/tp5-saturation-w2/) et les mesures Docker dans [`tp5-api-stats-w2.txt`](evidence/tp5-api-stats-w2.txt).

---

## 6. Intégration continue (CI) & tests d'intégration

Le workflow GitHub Actions `.github/workflows/ci.yml` s'exécute sur chaque push vers `tp4`, `main` et `master`, ainsi que sur chaque pull request. Les actions qu'il utilise sont épinglées sur un commit SHA complet afin de garantir une exécution reproductible et d'éviter qu'une mise à jour externe imprévue ne modifie le comportement de la CI. Il effectue :

- Lint Ruff sur `src/` et `tests/`
- Tests unitaires et modèle : `pytest -m "not integration"`
- Scan de secrets Gitleaks

Le test `tests/test_mlflow_stack.py` est marqué `integration` et reste exclu de la CI standard, car il nécessite Docker Compose et un fichier `.env` local.

Le test d'intégration de la stack MLflow se lance séparément et écrit sa preuve dans [`evidence/mlflow-local-stack.txt`](evidence/mlflow-local-stack.txt). Commande identique en **Bash** et en **PowerShell** :

```bash
pytest tests/test_mlflow_stack.py -m integration
```

Après avoir créé `.env` à partir des variables documentées, le test vérifie l'interpolation Compose sans afficher les secrets, l'état de PostgreSQL et des migrations MLflow, les endpoints HTTP MLflow, la présence de la base MLflow et la conservation des métadonnées après un redémarrage du serveur. Le résultat reproductible est écrit dans [`evidence/mlflow-local-stack.txt`](evidence/mlflow-local-stack.txt).

---

## 7. Exigences & déclaration d'usage de l'IA

- **Exigences** : le service couvre les exigences définies dans [`docs/exigences.md`](docs/exigences.md) (S1 à S9, incluant EX-16 à EX-18 pour le TP5).
- **Usage de l'IA générative** : chaque activité respecte son mode (sans IA, IA déclarée ou IA imposée). En mode IA déclarée (ex. : `scripts/bench_predict.py`, scripts d'automatisation Locust), l'outil utilisé, les demandes formulées ainsi que les vérifications et corrections apportées par le binôme sont consignés dans les commits et le rendu.
