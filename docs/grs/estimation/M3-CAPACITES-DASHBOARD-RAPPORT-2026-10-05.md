# M3 — capacités visibles dans le dashboard

## Résultat et périmètre

La page des connecteurs comporte une fiche de préparation de devis M3 alimentée par le
catalogue réel du département. Elle distingue l'outil d'estimation, la qualification des photos,
les données requises et l'exécution non observée. Elle ne calcule aucun prix et ne consulte
aucun dossier client. Le contrat JSON existant de l'inventaire des connecteurs reste conservé.

Les photos et leur échelle, le contexte CRM et le barème restent nécessaires. La présence
d'un outil n'atteste ni photos reçues ni géométrie qualifiée. OSRM appartient aux trajets M4;
il ne mesure pas un bâtiment. Aucun fournisseur photo/géospatial ni authentification distante
n'est déclaré prêt par cette tranche.

Fichiers : src/opsys/console/connecteurs_ui.py et tests/test_console_connecteurs.py.
La fiche reste soumise aux droits existants de la console; elle ne montre aucune clé secrète.
Un catalogue absent ou illisible produit un état explicite, sans inventer une capacité.

## Vérifications

ROOT r299 : 66/66 cas dans cinq fichiers complets — connecteurs, configuration,
STT persistant, console métier et déclencheurs d'agents. Ruff et validation des manifestes
passent. Les sources gelées sont inchangées pendant l'exécution; aucun OOM observé.
Le reçu r298 conserve le premier échec de longueur de ligne; pytest n'y avait pas été lancé.
La correction de format a conservé l'AST avant la reprise r299.

[Audit initial des capacités](../../research/REPRISE-2026-10-05/conceptions/LOT6-CAPACITES-AUDIT-r1.md).
Cet audit décrit les sources avant modification de la fiche : ses empreintes sont historiques.

## Limites et suite

Cette livraison rend lisible une capacité locale existante. Le tableau complet des dix
départements, les connecteurs photo/géospatiaux, la précision mesurée et l'observation d'une
exécution restent à qualifier. Aucun chantier confirmé, devis réel ou agent autonome continu
n'est prouvé par cet affichage.

## Preuves conservées

[Capsule sources et reçus](../../research/REPRISE-2026-10-05/preuves/M3-CAPACITES-DASHBOARD-r1.tar.xz)
— SHA-256 2d6c1201578e83f72d3a772989bf673269e2d689242f5269b81736e0e14867e9.
[Inventaire](../../research/REPRISE-2026-10-05/preuves/M3-CAPACITES-DASHBOARD-r1.json).
Le contrôle des secrets r300 porte sur 26 fichiers et ne détecte aucun secret.
La capsule conserve le rapport avant ajout de ces liens.
