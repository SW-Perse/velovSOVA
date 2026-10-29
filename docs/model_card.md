# Model card : velov-availability

> Template à compléter 
> Inspirée de Mitchell et al., "Model Cards for Model Reporting" (2019)

## 1. Identité
- Nom / version : `velov-availability` / version du Model Registry
- Date d'entraînement :
- Responsables (binôme) :
- Emplacement de l'artefact (fichier, registre, image) :
  `models/model.joblib` et `models/metadata.json` localement, puis
  `velov-availability` dans le registre MLflow.
- Alias : `challenger` est la version candidate ; `champion` est la version
  actuellement autorisée pour la livraison.

## 2. Usage prévu
- Ce que le modèle prédit :
- Utilisateurs et décisions alimentées :
- Usages hors périmètre (ce qu'il ne faut PAS faire avec ce modèle) :

## 3. Données
- Source, période couverte, volume :
- Découpage entraînement / test (et pourquoi temporel) :
- Fenêtre d'évaluation : les `test_days` derniers jours réellement disponibles
  dans la table d'entraînement (14 par défaut), enregistrés dans chaque run
  par `evaluation_period_start` et `evaluation_period_end`. Le challenger et
  le champion doivent partager exactement cette fenêtre.
- Limites connues (stations absentes, événements exceptionnels, météo...) :

## 4. Performance
| Métrique | Modèle | Baseline (persistance) | Seuil d'acceptation |
|---|---|---|---|
| MAE (vélos) | `mae_model` | `mae_baseline_persistence` | modèle < baseline |

- Performance par segment (heure de pointe, week-end, station) :
  `mae_model_peak_hours` est également enregistrée.
- Promotion : en présence d'un champion, la MAE du challenger doit être
  inférieure ou égale à `champion_mae * 0.98` sur la même fenêtre. Sans
  champion, battre la persistance suffit pour une première promotion.
- Variabilité : les différences entre seeds servent à observer le bruit
  expérimental ; elles ne remplacent pas le seuil fixe de 2 %.

## 5. Contrat d'entrée / sortie
- Champs d'entrée, types, bornes :
- Sortie et unité :
- Comportement sur entrée inconnue (nouvelle station...) :

## 6. Risques et limites
- Dérive attendue (saisonnalité, travaux, nouvelles stations) :
- Données personnelles : oui / non, justification :

## 7. Exploitation
- Latence cible :
- Fréquence de réentraînement prévue :
- Lien vers le runbook :
- Validation de promotion : `python -m velov.promote` affiche la décision sans
  changer le registre ; `python -m velov.promote --apply` applique explicitement
  une décision positive en déplaçant l'alias `champion`.
- Audit : chaque décision écrit `promotion_decision`,
  `promotion_reason`, `promotion_previous_champion` et
  `promotion_rule_version` sur le run challenger.
