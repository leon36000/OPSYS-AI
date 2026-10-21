# Revue de complétion liée aux sources M6

Cette voie distingue la proposition N4 depuis un appareil admin de l'exécution signée par le
propriétaire. Un classement M6 est une annotation humaine, pas une preuve de causalité physique,
de scène photographiée ou une accusation. Aucun ajustement stock/coût, nouveau WCT, M5 ou M10
n'est produit par la revue.

## Outils et enveloppes

`m4_lire_dossier_revue_completion_appareil` est T0/N0/admin. Ses seuls arguments sont
`intervention_id` et `demande_id` (null pour le dossier courant, un identifiant pour la demande
historique). La fonction rend un seul COUPLE `accepte/resultat` ou `accepte:false/verdict`,
enveloppé par `ok/resultat` du socle. Aucun Meta ni `rejoue` pour cette lecture.

`m4_resoudre_revue_completion_sources` est T1/N4/admin. Ses cinq arguments fermés sont
`intervention_id`, `decision` (`verifiee` ou `correction`), `horodatage`, `motif` et `sources`.
L'appel DEVICE propose une demande d'approbation, il ne réalise pas lui-même la transition.
`horodatage` reste l'heure proposée déclarée, distincte de `APP.decide_le` qui date la décision
serveur. Le motif est non vide et borné à 500 points Unicode ; il ne remplace pas le motif de
signature de la demande.

La capture source contient WCT/chantier, la ligne de complétion M4, la dernière transition de
cette intervention attendue, la référence variance publiée type/id/empreinte et le dernier
classement de chaque ligne critique. Position, matériau et référence de classement doivent
correspondre exactement à la sélection M6. Une référence null est une absence explicitement
observée ; elle est admise pour `correction`, jamais pour `verifiee`.

## Source et couverture

L'adaptateur relit la chaîne M4, le WCT publié et son catalogue/producteur, la charge M6 publiée
`m6-variance-<wct>-evaluee`, les besoins du devis, les mouvements/proofs/classements/refus M6.
Les rangs des copies SQL et les chaînes sont vérifiés. La cible intervention/WCT/chantier est
croisée. Aucun import des factories M6 ; les validateurs, projections et références purs M6 sont
réutilisés. Le WCT ne porte pas de chantier M6 : il vient des sources M6, pas d'un champ inventé.
L'empreinte de sa partie transition est distincte du `ligne_id` de la chaîne M4.

La source non publiée, la déclaration absente, une source non évaluée ou corrompue ne devient
ni une liste vide ni zéro ni un chantier vérifié. Les unités et ratios null sont conservés.
La vérification exige toutes les lignes critiques classées et les dernières révisions encore
actuelles au moment de l'exécution humaine différée. Une correction conserve
`completed_pending_review`, avec un maillon d'audit ; elle ne rouvre pas le chantier.

## Signature et reprises

Les preuves APP/JOURNAL et la corrélation de la décision appartiennent au helper Root
`opsys.approbations_completion_m4`, jamais à une requête APP/J recopiée dans M4.
`donnees_execution` retourne les sept clés fermées convenues : demandeId/hash args P/proposant,
approbateur SQL/rôle/heure serveur/association D. MetaD sert seulement à la corrélation, pas à
l'autorité. La réception et l'identité de l'appareil sont effacées avant le writer approuvé.
Une exécution sans ce contexte/provenance, y compris un appel console direct du nouvel outil,
est refusée ; la console historique reste explicitement non liée.

Le nouveau maillon `transition_statut` porte `version_schema:2`, les sources exactes, demandeId,
proposant du journal, approbateur SQL, empreinte des arguments P et association D. Le registre
ajoute ses `ligne_id` et `precedent_ligne_id`. Les anciens maillons v1 et leurs hashes ne sont
pas réécrits. `preuve_resolution_historique` valide le propre maillon et les arguments/signature
persistés, sans exiger la tête actuelle ni la dernière classification M6.

UUIDP confirme une création de demande, pas une exécution. UUIDD désigne sa propre tentative
humaine ; D1 succès et D2 même corps/heure refusée restent distincts. Un refus D sans propre
preuve ne certifie pas l'absence d'un effet ancien : issue inconnue, UUID et corps d'origine
conservés. Le nouveau reçu D doit être ajouté par Root et validé par le consommateur spécialisé ;
le résumé générique `_issue` ne contient pas le maillon.

## Bornes, rollback et compatibilité

Arguments signables : 1500 caractères JSON comme le lecteur d'approbations natif. Enveloppes
entières : `min(5400, Cap._limite)` ; mutation mesurée sous `rejoue:false` et `rejoue:true`.
La projection D complète anticipée (accusé, preuve et issue) est également bornée avant append.
Aucune omission d'une position critique ni troncature de fait pour rendre une demande signable.
Une lecture complète à 5400 ne garantit pas que sa proposition à 1500 puisse être signée.

Le plafond local M6 de 10000 porte sur les copies admises après chargement, pas sur une allocation
globalement bornée ni une promesse de 10000 sources signables. Le hook Cap pour les deux lectures
courante/historique doit refuser sans ARTEFACTS avant `_tronquer` ; c'est une responsabilité Root,
pas une propriété acquise par la seule borne DTO.

Après append, une panne de projection/quota lève RuntimeError et fait annuler l'effet métier par
le savepoint. APP=echec et journal peuvent rester les traces volontaires de la décision, sans
faux ACK ni nouvelle exécution automatique. Une nouvelle proposition après échec demande une
nouvelle signature humaine. Le factory rouvre le registre après rollback ; une ancienne instance
mémoire ne devient pas la tête courante par supposition.

L'ancien outil quatre arguments reste purement historique à la console. DEVICE direct est
refusé ; pour une ancienne demande différée, Root `autoriser_legacy` contrôle sa provenance avant
la fonction v1. Une demande DEVICE queued ne devient pas liée par ajout silencieux de références.
L'exception console n'autorise aucune affirmation « toutes décisions sont liées ».

## Qualification et limites

Tests purs : données et signature de pacte explicitement fictives, pas authentification N4.
Adaptateur : publications M4/M6 et writers SQLite existants, identité admin injectée puis
confirmée SQL ; comparaison de toutes les tables présentes sur lecture et refus. Le test de
panne postappend exerce le vrai stockage et le rollback/retry, avec un pacte de signature fictif.
La jonction Root Cap/APP/P/D, les DTO consommés via Gateway, la révocation du jeton et le
redémarrage natif restent des qualifications séparées. Aucun téléphone/Hermes/ExpoSQLite,
Postgres, provider, paiement ou preuve physique n'est revendiqué par les tests département.


## Frontière des contrats matériaux et garde R-020

M4 accède aux validateurs et projections canoniques de variance matériaux par
`opsys.contrats_variance_m6`, sans import direct du département M6, sans factory
ni copie des calculs. Les fonctions déléguées conservent les mêmes refus et
les mêmes octets de DTO/maillons. Le graphe d’import conserve les dépendances
SQL transitives de M6 ; les calculs de revue eux-mêmes ne lisent pas SQL.

Les clés natives `classements`, `classement_courant` et
`positions_sans_classement` décrivent les annotations humaines des causes de
variance des matériaux. Elles ne classent pas les techniciens ni ne certifient
une causalité physique. R-020 admet ces trois clés littérales exactes dans les
DTO fermés ; elle continue de refuser les identifiants, attributs, signatures
et clés de notation, performance, classement du personnel ou ranking, sans
exemption de fichier ni introduction dynamique. Les deux outils nouveaux
précèdent le trio historique de lecture/validation des heures, immédiatement
suivi de `m4_lire_retards_incidents`, qui reste le dernier outil historique.
L’ordre relatif et ce suffixe des outils historiques demeurent inchangés.
