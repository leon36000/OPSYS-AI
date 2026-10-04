# M1 — résumé privé de réception : conception du 4 octobre 2026

Statut : **sous-capacité qualifiée localement par ROOT r142**. M1 global demeure **PARTIEL**.
Cette note fixe le contrat attendu ; le [rapport de qualification](M1-DIGEST-CONSOLE-RAPPORT-2026-10-04.md)
sépare les observations existantes de la qualification à venir.

## Usage et propriétaire

L’adjointe ou le propriétaire ouvre « Résumé de réception », choisit une date
et lit les compteurs du registre anti-perte : événements par canal et type,
appels importés, conversations à suivre, transferts, plaintes et urgences.
Ces nombres sont des événements enregistrés, pas des clients uniques ni une
mesure de performance commerciale. Un registre vide produit une absence
explicitement datée.

Réutiliser le producteur [M1 `digest.py`](../../../departments/m01-front-office/src/m1_front_office/digest.py),
le port [canonique `m1_produire_digest`](../../../departments/m01-front-office/src/m1_front_office/outils.py)
et sa lecture dans [la console métier](../../../src/opsys/console/metier.py).
Les calculs et le schéma de cet outil restent inchangés. Le routeur dédié,
`src/opsys/console/reception_digest_ui.py`, adapte son résultat textuel ;
[le montage](../../../src/opsys/console/application.py) et
[la réception existante](../../../src/opsys/console/frontoffice_marketing.py)
ajoutent seulement les routes et leur accès visuel. Aucun parser partagé de
commandes n’est élargi.

## Transport privé attendu

Deux GET, sous le préfixe réel de la console :

- `/reception/digest?date_reference=YYYY-MM-DD` : page privée ;
- `/api/reception/digest?date_reference=YYYY-MM-DD` : JSON privé.

Si fournie, la date est ASCII, calendaire et exactement au format ISO.
Sans paramètre, le jour UTC serveur est retenu et affiché explicitement.
Paramètre inconnu, dupliqué ou date invalide : refus, sans calcul.
La réponse distingue `date_reference`, `lu_le` en UTC serveur, `digest`,
`methode` et `limites`. Session authentifiée admin ou owner, identité et rôle
relus en base avant le SQL du journal, après la lecture puis après construction
de la réponse, avant retour. Une révocation refuse sans résumé.
`Cache-Control: no-store` s’applique aux deux représentations.

## Lecture bornée et confidentialité

Périmètre initial : **SQLite durable seulement**, registre M1 `principal`.
Le préflight SQL précède toute matérialisation ou tout décodage du journal.
Préflight et calcul doivent lire la même source transactionnelle ; PostgreSQL
est refusé tant que ce chemin n’est pas qualifié.

| Borne inclusive | Limite |
|---|---:|
| Maillons M1/principal | 10 000 |
| Un maillon, octets UTF-8 | 65 536 |
| Somme des maillons, octets UTF-8 | 8 388 608 |
| Texte du digest, octets UTF-8 | 32 768 |

Tout dépassement refuse l’ensemble ; aucune troncature silencieuse des totaux.
L’enveloppe exige un succès et une chaîne. Une grammaire fermée reconnaît
les seules lignes canoniques, compteurs ASCII non négatifs et statuts d’appel
`manque`, `voicemail`, `inconnu`. Une ligne inattendue, un décodage invalide ou
une source non couverte refuse sans restituer le journal ni du texte brut en
erreur. Le HTML est échappé ; le JSON expose des agrégats, sans contact ni
contenu libre. Cette adaptation ne prouve pas l’intégrité cryptographique
complète du journal ou la détection de toute réécriture privilégiée.

## Méthode temporelle et limites

La grille suit les dix premiers caractères des horodatages enregistrés.
Les anciennes entrées sans date restent incluses par compatibilité. Le suivi
des conversations utilise leur dernier état connu dans le journal courant :
une clôture tardive peut donc modifier un résumé portant une date ancienne.
Les transferts utilisent leurs dates d’ouverture et de clôture. L’écran doit
rendre ces trois méthodes visibles ; aucune conversion Toronto/UTC, situation
historique uniforme de fin de journée ou promesse « temps réel » n’est ajoutée.

Cette lecture ne crée ni outil agent, LLM, fournisseur, approbation, reçu de
mutation, journal d’action, écriture CRM, notification, paiement ou scheduler.
La prise en charge et les tentatives de rappel non terminales constituent une
**prochaine tranche distincte** : le résumé ne les implémente pas.

## Qualification requise

ROOT r142 vérifie le parcours HTTP réel avec SQLite migré, préfixe console,
date choisie ou défaut UTC exposé et erreurs fermées ; les bornes exactes et +1, y compris
Unicode multioctet avant décodage ; les lignes canoniques complètes et textes
sensibles refusés ; la révocation pendant lecture et rendu ; no-store et
l’absence d’écriture. Le cas de clôture tardive doit préserver la méthode du
producteur. Conserver les oracles [digest](../../../departments/m01-front-office/tests/test_digest.py)
et [suivi](../../../departments/m01-front-office/tests/test_suivi_conversation.py)
ainsi que les parcours réception existants. La campagne passe 1 667 tests sur 37 fichiers complets, sans échec/erreur/skip ;
Ruff vert, 1 242 sources inchangées. Les preuves et limites sont dans le rapport.
