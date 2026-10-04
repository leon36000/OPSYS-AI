# M1 — résumé privé de réception, 4 octobre 2026

**Sous-capacité qualifiée localement ; M1 global PARTIEL.** Depuis la réception,
le propriétaire ou un administrateur choisit une date et consulte les agrégats
du journal durable. La CI du nouveau commit reste à obtenir séparément.

## Comportement livré

Les GET `/reception/digest` et `/api/reception/digest`, sous le préfixe réel
de console, réutilisent [le port canonique M1](../../../departments/m01-front-office/src/m1_front_office/outils.py)
et [ses calculs](../../../departments/m01-front-office/src/m1_front_office/digest.py).
Le [routeur dédié](../../../src/opsys/console/reception_digest_ui.py) expose
une grille de vingt paires canal/type, appels importés, suivi et transferts.
Un journal vide est explicitement distingué d’une date sans événements dans
un journal non vide. Ces compteurs sont des événements, pas des clients uniques.

La date fournie est ASCII ISO et calendaire ; paramètres inconnus, doublons,
date vide ou requête trop longue refusent. Sans paramètre, le jour UTC serveur
est retenu et affiché. La réponse distingue date de référence et heure UTC
de lecture. Le formulaire permet de choisir la date.

Les sessions sont vérifiées avant/après calcul puis après sérialisation :
identité active, rôle owner/admin et expiration. HTML et JSON sont privés,
`no-store`, sans contact ni contenu libre du journal. Erreurs de source,
décodage, enveloppe ou grammaire donnent un 503 générique sans données privées.
La connexion du préflight doit être celle du stockage durable M1/principal.

Aucune écriture : pas d’approbation, reçu de mutation, journal d’action,
CRM, notification, fournisseur ou LLM appelé. [Le montage](../../../src/opsys/console/application.py)
et [la réception existante](../../../src/opsys/console/frontoffice_marketing.py)
ajoutent seulement le routeur et son lien ; le producteur M1 reste inchangé.

## Bornes et méthode

SQLite durable uniquement. Le SQL précède la matérialisation du journal :
10 000 maillons, 65 536 octets UTF-8 par maillon, 8 388 608 octets cumulés,
bornes inclusives. Le texte propriétaire est limité à 32 768 octets ;
les nombres et lignes reconnus forment une grammaire fermée. Dépassement :
refus entier, sans troncature. Ce sont des bornes de données, sans garantie
universelle de consommation mémoire pour tout contenu admissible.

La grille suit les dates stockées ; les anciennes entrées sans date sont incluses.
Le suivi utilise le dernier état courant des conversations, même pour une
date ancienne. Les transferts suivent leurs dates d’ouverture/clôture.
Le parcours HTTP qualifié crée un SMS incomplet et un appel manqué le 3 octobre :
deux conversations à suivre. Un STOP du 4 octobre ferme celle du SMS :
le résumé du 3 octobre passe à une conversation, tout en conservant sa grille
datée et son transfert. L’écran explicite cette méthode composite.

## Vérification et preuves conservées

ROOT r142 : **1 667/1 667 sur 37 fichiers complets**, 95,034 s JUnit,
zéro échec/erreur/ignoré. Ruff sur quatre fichiers de code ; **1 242 sources**
gelées inchangées, aucune garde déclenchée, aucun nouvel OOM ou processus
survivant. Les suites couvrent toute la réception M1, commandes métier,
console réception/réputation, voicemail/upload et le nouvel écran.

[Les nouveaux tests](../../../tests/test_console_reception_digest.py) vérifient
les GET authentifiés sous préfixe, dates/distinction vide, compteurs canoniques,
non-écriture de toutes les tables, confidentialité, refus backend/décodage,
retraits simulés pendant calcul et rendu, expiration, retrait de rôle ou
désactivation **réellement commis en base après le rendu**, puis réponse refusée.
Les plafonds SQL réels sont exercés exactement et au-delà, dont UTF-8 multioctet,
limite par maillon et total plus un octet, 10 001 lignes ; le décodeur ne doit
jamais être appelé après un dépassement.

Les résultats rouges restent intacts : r137 prouve la route absente (404),
r139 conserve deux erreurs de fixture (journal vide et redirection suivie),
r140 conserve mon oracle qui omettait la seconde conversation de l’appel,
r141 conserve le lint des longues chaînes HTML. Le helper QA r2 ne reconnaissait
pas 174 méthodes de classes dans le JUnit r139 ; r3 ajoute le préfixe exact du
module en conservant attribution unique et couverture des fichiers. Son
readback donne 1 657 réussites/2 échecs ; aucun ancien reçu n’est réécrit.
Les versions documentaires et sources de revue restent historiques.

[Capsule](../../research/REPRISE-2026-10-04/preuves/M1-DIGEST-CONSOLE-r1.tar.xz),
[manifeste](../../research/REPRISE-2026-10-04/preuves/M1-DIGEST-CONSOLE-r1.json),
[conception](M1-DIGEST-CONSOLE-DESIGN-2026-10-04.md).
Les campagnes qui se recouvrent ne s’additionnent pas en couverture globale.

## Limites et suite

Pas de qualification PostgreSQL de ce lecteur, ni de validation cryptographique
intégrale du journal. Ce n’est pas un instantané historique uniforme, un SLA,
une preuve de contact réussi ou une téléphonie de production. Prise en charge
et tentatives de rappel sans contact restent à construire. Aucun statut global
de M1 ou OPSYS n’est promu.
