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

Identité authentifiée (PLAN T1.4-c4, T2.3-d, puis T1.4-k2, docs/architecture/ROLES.md) : pendant un appel
d'appareil, la vue d'un devis vient du rôle confirmé en base (l'employé ne voit ni coût, ni marge, ni prix ;
`role` ne peut que restreindre). Depuis T1.4-k2, un vendeur ne lit (`m3_lire_devis`) et n'obtient le
brouillon (`m3_generer_soumission_brouillon`) que des devis des leads dont il est le propriétaire : M3 relit
ce propriétaire à la source du bus (`m2.lead_assigne`, publié par M2 à la qualification), jamais depuis les
arguments, et sans importer M2. Le devis d'un autre, celui d'un lead sans propriétaire connu et un devis
inconnu donnent le même refus (`REJ-DEVIS-INTROUVABLE`). L'admin et la voie des agents ne sont pas filtrés.
