# Courbe de saturation

SLO : p95 < 200 ms et taux d'erreur < 0,1 %.

| Utilisateurs | p50 (ms) | p95 (ms) | p99 (ms) | Débit (req/s) | Erreurs | SLO |
|---:|---:|---:|---:|---:|---:|:---:|
| 10 | 61.0 | 75.0 | 94.0 | 12.21 | 0.000% | OK |
| 25 | 64.0 | 110.0 | 170.0 | 30.31 | 0.000% | OK |
| 50 | 100.0 | 350.0 | 560.0 | 55.49 | 0.000% | DÉPASSÉ |
| 100 | 940.0 | 1400.0 | 1600.0 | 59.09 | 0.000% | DÉPASSÉ |
| 150 | 1700.0 | 2100.0 | 3000.0 | 59.02 | 0.000% | DÉPASSÉ |

Capacité sous le SLO : **30.31 req/s** au palier de 25 utilisateurs.
Premier palier hors SLO : **50 utilisateurs** (p95 350.0 ms, erreurs 0.000%).
