# M5 — retenue fédérale QC et composition préparatoires

Capsule scellée et relue par ROOT le 2 octobre 2026. Archive :
[M5-FEDERAL-COMPOSITION-2026-10-02.tar.gz](M5-FEDERAL-COMPOSITION-2026-10-02.tar.gz),
129809 octets, 81 membres, SHA-256 `2037fd27a8692b7e5d7b2f72010929ceecdffa002d2e9bee1807af2eb4732b3c`.

**79 cas ROOT uniques passent**, sans échec, erreur ou saut : 33 de composition,
30 d'impôt Québec et 16 fédéraux. Ruff est vert, les 12 sources testées sont
copiées exactement et comparées au checkout courant au scellement. Temps :
1,383908 s ; RSS maximal 51 970 048 octets ; réserve minimale 1 824 997 376 octets.
Aucun nouvel OOM, survivant ou changement des sources pendant cette campagne.

Le calcul fédéral consomme les demandes brutes via la façade publique et
préserve la précision intermédiaire. Le correctif Québec isole son contexte
Decimal du contexte appelant. Le périmètre est la première période de janvier–juin
2026, résident QC déclaré, salaire fixe bihebdomadaire, 26 périodes, PM=12,
emploi continu, cumuls nuls et assiettes concordantes. Les preuves déclarées
ne sont pas authentifiées. Net, DAS globale, CCQ, coût employeur complet,
bulletin et paie officielle ne sont pas qualifiés ; aucune action financière.

Les campagnes ROOT101 et ROOT33 sont conservées avec leurs snapshots distincts.
Les rouges auteur et les préimages sont conservés. Ces nombres se recouvrent
et ne s'additionnent pas. La [capsule RRQ](../M5-RRQ-26P-2026-10-02/README.md)
est référencée par son SHA, avec ses limites propres. Les documents primaires
sont référencés par hash, sans copie des gros PDFs dans cette archive.

[Qualification et index](QUALIFICATION.json). L'archive contient son manifeste
par membre et les conducteurs ; le conducteur de scellement ne relance aucun test.
