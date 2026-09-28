# M3-estimation

Estimation Intelligence — vision, mesures a bornes, prix/marge

Statut: LIVRÉ (S001 à S009 — les neuf stories du PRD sont implémentées et
testées vertes : validation des entrées (S001), qualification de la qualité
photo (S002), hiérarchie des références d'échelle (S003), garde anti-
précision-inventée / prix bloqué (S004), Monte Carlo déterministe (S005),
plancher rentable (S006), contrat de sortie EstimationV1 et devis_id (S007),
registre append-only estimé-vs-réel (S008), échappatoires D-032 et digest
quotidien déterministe (S009). Outils d'agent exposés dans
`src/m3_estimation/outils.py` (`m3_estimer_projet` et les outils unitaires).
Suite de tests et suite de mutation vertes (`departments/m03-estimation/tests`).)
