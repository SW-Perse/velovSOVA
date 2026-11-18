# Courbe de saturation

SLO : p95 < 200 ms et taux d'erreur < 0,1 %.

| Utilisateurs | p50 (ms) | p95 (ms) | p99 (ms) | Débit (req/s) | Erreurs | SLO |
|---:|---:|---:|---:|---:|---:|:---:|
| 10 | 63.0 | 81.0 | 95.0 | 12.27 | 0.000% | OK |
| 25 | 62.0 | 88.0 | 170.0 | 30.25 | 0.000% | OK |
| 50 | 130.0 | 810.0 | 1300.0 | 49.67 | 0.000% | DÉPASSÉ |
| 100 | 1200.0 | 1800.0 | 2100.0 | 49.54 | 0.000% | DÉPASSÉ |
| 150 | 2200.0 | 2800.0 | 3100.0 | 48.95 | 0.000% | DÉPASSÉ |

Capacité sous le SLO : **30.25 req/s** au palier de 25 utilisateurs.
Premier palier hors SLO : **50 utilisateurs** (p95 810.0 ms, erreurs 0.000%).
