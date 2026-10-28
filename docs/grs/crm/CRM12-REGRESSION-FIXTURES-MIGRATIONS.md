# CRM12 — réconcilier les fixtures historiques après les migrations documentaires

## Constat et cause

La CI publiée sur `9e4b6edfb832e4303550dc9d0d45a10bd91040fb` a terminé avec 38 succès,
4 SKIP et 2 échecs : `socle (0)` et son gate agrégé. Les logs du job `122605942448`, run
`40624459178`, montrent 10 erreurs de setup et 2 échecs. Ces rouges restent historiques.

Les fixtures d’effacement imposaient encore `migrer() == 0027`, alors que ce contrat migre vers
la tête native, devenue 0028 en CI puis 0029 localement. Le comparateur des tables antérieures à
0024 sélectionnait les nouvelles pièces du META actuel, même après retour valide à 0023 où elles
n’existent pas. Aucun défaut de migration produit n’est déduit de ces erreurs de harnais.

## Correction et invariants conservés

`tests/test_effacement_cles.py` et `test_effacement_legacy.py` exigent désormais la tête Alembic
native du logiciel, sans numéro obsolète. Le downgrade refusé doit toujours conserver exactement
la révision observée avant tentative; aucune tolérance de révision partielle.

`tests/test_fusion_ap_saisie_migration.py._anciennes` exclut explicitement les tables de pièces
0028 et de classement 0029, comme les compartiments post-0023 déjà exclus. Aucun filtrage dynamique
« seulement si la table existe » : une table réellement attendue et absente doit encore faire échouer.
Le nouveau scénario sans parseur compare **l’ensemble exact des tables réellement en 0023**, un
journal fictif non vide conservé, puis les mêmes données en 0024 et à la tête courante.

Aucun changement de migration, code produit, permission, parseur ou gate CI. Les scénarios AP
originaux et leurs contrôles de contraintes, de rollback et de conservation restent présents.

## Vérification et limites

Préflight M10 privé frais avant modification; cette mémoire vide de développement n’est pas la
mémoire du projet. Reproduction locale : 10 erreurs `0029 != 0027`; le nouveau test causal échoue
bien sur `SELECT pieces_projet` après retour en 0023. Après correction : 12 tests ciblés passent
en 3,41 s, puis **89 tests passent en 28,69 s**, effacement/legacy, comparateur historique,
pièces, classement et import ancien état. Lint et vérificateur natif OK (306 outils, 177 déclarés
aux appareils). Cohortes recoupées avec les 253 tests CRM : ne pas additionner.

Une première tentative locale incluant les sept anciens tests AP s’est arrêtée sur leur
précondition PDF. Le probe natif bubblewrap a confirmé `loopback: Failed RTM_NEWADDR: Operation
not permitted`. Ces erreurs de prérequis ne deviennent ni bugs produit ni succès; aucun mock,
SKIP ajouté, relâchement d’isolation ou fallback. La CI Linux compatible doit encore exécuter ces
sept tests AP originaux sur le nouveau commit.

Enveloppe privée : CPU 1, mémoire 1 Gio, swap 0, PID 96, TTL 600 s, Source lecture seule, home/tmp
privés avant imports, création de sockets refusée, empreintes source et reçus durables. Revue
statique indépendante : aucun invariant affaibli identifié; elle ne remplace pas les sept essais AP.

## Statut et suite

Correction de harnais qualifiée sur les scénarios locaux exécutables. Publier normalement les
commits locaux dans la PR852 draft, sans rejouer/annuler le run rouge ni fusionner/déployer.
Qualifier la CI du nouveau SHA, notamment le socle et le gate; conserver toute autre anomalie.
OPSYS-AI reste PARTIAL, `runtime_GO=false`, `global_PASS=false`.
