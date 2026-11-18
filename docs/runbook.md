# Runbook : API velov-availability

> Runbook opérationnel pour une personne d'astreinte qui doit vérifier,
> diagnostiquer ou rétablir le service.

## 1. Vue d'ensemble

L'API prédit le nombre de vélos disponibles dans une station pour l'heure
suivante. Elle charge le modèle local, calcule les features, expose FastAPI et
conserve les prédictions dans PostgreSQL.

Dépendances :

- conteneur `api` et modèle monté depuis `models/` ;
- PostgreSQL (`db`) pour l'écriture des prédictions ;
- Docker Compose et le fichier `.env` local.

## 2. SLO et capacité mesurée

Le SLO de production est : **p95 de latence strictement inférieur à 200 ms et
taux d'erreur strictement inférieur à 0,1 %**, pour `POST /v1/predict`.

La capacité sous le SLO est le débit du dernier palier dont les deux critères
sont respectés :

| Configuration | Capacité sous le SLO | Premier palier hors SLO |
|---|---:|---|
| 1 worker / 1 coeur | 30,31 req/s à 25 utilisateurs | 50 utilisateurs, p95 350 ms |
| 2 workers / 2 coeurs | 30,25 req/s à 25 utilisateurs | 50 utilisateurs, p95 810 ms |

La modification unique 2 workers / 2 coeurs n'a donc pas doublé le débit sous
ce SLO. La mémoire API observée par `docker stats` est passée d'environ 164 MiB
à 316,6 MiB, soit environ 1,93 fois plus.

## 3. Démarrer / arrêter

Configuration de référence :

```powershell
docker compose -f docker-compose.yml up -d --build
```

Configuration expérimentale 2 workers / 2 coeurs :

```powershell
docker compose -f docker-compose.yml -f compose.workers.yaml up -d --build api
$apiId = (docker compose -f docker-compose.yml -f compose.workers.yaml ps -q api).Trim()
docker update --cpus 2 $apiId
```

Arrêter les services :

```powershell
docker compose -f docker-compose.yml down
```

## 4. Vérifier que tout va bien

```powershell
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:8000/ready
docker compose -f docker-compose.yml ps api
docker stats --no-stream velov-api
```

Résultats attendus :

- `/health` répond HTTP 200 avec `{"status":"ok"}` ;
- `/ready` répond HTTP 200 avec `{"status":"ready",...}` ;
- le conteneur `api` est `Up` et `healthy` ;
- le modèle est chargé et la mémoire reste cohérente avec la configuration.

Pour mesurer le SLO avec le protocole TP5 :

```powershell
.\loadtest\paliers.ps1 -HostUrl http://localhost:8000 -ResultsDirectory locust-results\tp5-saturation
```

Le rapport doit conserver le commit, le modèle, la configuration CPU/workers,
la durée, les paliers et les fichiers CSV/HTML bruts.

## 5. Incidents connus et diagnostic

| Symptôme | Diagnostic | Action |
|---|---|---|
| `/ready` renvoie 503 | `docker compose logs api` puis vérifier `models/` et la base | Vérifier le modèle et PostgreSQL, puis redémarrer `api` |
| Le conteneur redémarre en boucle | `docker compose ps api` et `docker compose logs --tail 200 api` | Corriger l'erreur de démarrage avant tout nouveau test |
| p95 supérieur à 200 ms | Rejouer le palier, consulter le rapport Locust et `docker stats --no-stream velov-api` | Identifier le premier palier hors SLO et comparer CPU/mémoire |
| CPU proche de 100 % par coeur ou supérieur à 200 % avec 2 workers | Vérifier `docker inspect` et `docker stats`; le calcul API est saturé | Ne pas conclure à un gain de débit sans une nouvelle campagne complète |
| Débit plafonné avec latence croissante | Vérifier les paliers 50, 100 et 150 utilisateurs, puis les logs PostgreSQL et API | Traiter le composant saturé; conserver les rapports comme preuve |

Les mesures brutes de la campagne 2 workers / 2 coeurs sont dans
`evidence/tp5-saturation-w2/` et `evidence/tp5-api-stats-w2.txt`.

## 6. Déployer ou revenir à la configuration de référence

Pour revenir exactement à 1 worker et 1 coeur, sans modifier le modèle ni la
base de données :

```powershell
docker compose -f docker-compose.yml -f compose.workers.yaml down
docker compose -f docker-compose.yml up -d --build api
$apiId = (docker compose -f docker-compose.yml ps -q api).Trim()
docker update --cpus 1 $apiId
Invoke-WebRequest http://localhost:8000/health
Invoke-WebRequest http://localhost:8000/ready
```

Vérifier ensuite la commande et la limite :

```powershell
docker inspect --format '{{.HostConfig.NanoCpus}} {{.Config.Cmd}}' $apiId
```

La valeur CPU attendue est `1000000000` et la commande doit contenir
`--workers 1`. Cette procédure ne supprime pas les volumes PostgreSQL ou
MLflow.

## 7. Contacts et escalade

Conserver les rapports Locust, les sorties `docker stats`, le commit et les
logs associés avant toute escalade.
