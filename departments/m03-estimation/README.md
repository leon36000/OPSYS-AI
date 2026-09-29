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

Soumission brouillon en PDF (PLAN T2.3-f, `soumission.py`, `soumission_pdf.py`) : `m3_generer_soumission_brouillon`
rend le brouillon d'un devis durable en HTML (défaut) ou en PDF (`format: "pdf"`). Les deux formats partent de
`soumission.contenu_client` (liste blanche : ni coût ni marge, jamais) et passent par les mêmes gardes de rôle et de
propriétaire. Le PDF est rendu par ReportLab (BSD-3-Clause, Python pur, aucune bibliothèque système), extra
`soumission` de `pyproject.toml` (`pip install -e ".[soumission]"`, déjà dans l'image Docker et le job M3 de la
CI) ; les tests le relisent avec `pypdf` (extra `dev`). Sans l'extra, un verdict dit d'installer l'extra
`soumission` : jamais un HTML renommé en PDF. Un champ requis absent, un horodatage sans fuseau, un montant qui
exigerait un arrondi ou un caractère hors Windows-1252 (jamais un carré « ■ » silencieux) donnent aussi un verdict
qui dit quoi fournir. Montants `Decimal` repris du devis et mis en forme à la québécoise (« 1 234,56 $ »), jamais
recalculés ; les taxes (TPS/TVQ) ne sont pas calculées par M3 (M5, §8) : le document dit « taxes en sus ». Tout
texte du client est une donnée : échappé, jamais interprété par ReportLab. Mêmes entrées, mêmes octets (mode
`invariant`, date de création tirée de l'horodatage du devis, jamais de l'horloge). La mention BROUILLON est sur
toute page : le devis ne modélise aucune approbation. La sortie de l'outil est en base64 (`contenu_base64`, avec
`taille_octets` et `empreinte_sha256`) et ne peut dépasser la sortie qu'un outil transmet sans troncature
(`jetons.LIMITE_SORTIE_DEFAUT`, de l'ordre de vingt lignes selon la longueur des descriptions) : au-delà, `REJ-SOUMISSION-PDF-TROP-VOLUMINEUX`, jamais un PDF
coupé. Aucun envoi : l'envoi au client reste une frontière humaine (N4), sans outil.
