# M7 — observation Growth saisie humainement

La console privée permet désormais à un admin ou propriétaire actif de saisir une
observation marketing et de la relire après réouverture de SQLite. Le serveur
enregistre son identité, son rôle et l'heure UTC. **M7 reste PARTIEL** : cette
provenance prouve la saisie console; le chiffre, la source et la confiance restent
`DECLAREE_NON_VERIFIEE`.

## Parcours et propriétaires

La page `GET /marketing/growth`, sous le préfixe configuré, conserve sa consultation
par période. Sans période, elle ne lit pas le registre. Après lecture, elle présente
le formulaire avec la tête courante. Les nouveaux POST
`/marketing/growth/observations` et `/api/marketing/growth/observations` réutilisent
le registre unique `m07-marketing/growth`, la transaction canonique SQLite et les
reçus d'idempotence existants. Aucun outil agent ni registre parallèle n'est ajouté.

Le métier interne `m7_enregistrer_observation_humaine` est distinct de l'ancien
writer agent : identité et origine console sont établies par le serveur. Un appel
legacy garde sa forme V1 et un auteur inconnu. Les nouvelles observations V2 ont une
provenance fermée incluse dans leur empreinte; les anciens octets ne sont pas réécrits.

## Autorité, concurrence et refus

Les deux POST exigent session active admin/owner et CSRF. Leur accès DB et leur
métier synchrones passent dans le threadpool. Les corps sont bornés à 32 KiB,
les champs sont fermés, les doublons et JSON trop profonds sont refusés, le rendu
est échappé et les réponses privées sont `no-store`.

L'heure est créée après réclamation d'idempotence et n'entre pas dans le hash de
requête. Le rejeu exact rend le même reçu après contrôle des droits actuels, sans
refaire l'ancien CAS ni ajouter un maillon. Une charge changée ou une tête périmée
est refusée. La tête compare nombre/rangs contigus et SHA du préfixe brut, encadré
par les longueurs UTF-8; ce hash local ne protège pas contre un administrateur DB
qui modifie puis rehash.

Avant matérialisation/décodage, SQL applique les limites du lecteur : 1 000 maillons,
32 Ki caractères par maillon et 1 Mi caractères au total. Ces budgets incluent les
plans historiques. Tout le préfixe est validé avant append, même hors période.
Le rôle est relu avant append et avant finalisation; une exception annule aussi le
reçu provisoire. La concurrence dernière place/tête est testée sur SQLite réelle.

## Qualification ROOT

La campagne finale passe **120 cas**, zéro échec, erreur ou skip, et Ruff sur les
six fichiers modifiés. Elle exécute cinq fichiers complets : console Growth,
lecteur Growth, Brand/Growth/local, console métier et commande métier. Les
**664 chemins sélectionnés** restent identiques avant/après; ce n'est pas une
fermeture de tout le dépôt. Durée totale 33,79 s, pic RSS 182 681 600 octets,
réserve minimale 1 255 682 048 octets; aucun changement des compteurs OOM ni
processus survivant. [Reçu et artefacts bruts](../../research/REPRISE-2026-10-03/preuves/m7-growth-humain/VERIFICATION-ROOT.json).

Les scénarios couvrent session/CSRF et HTTP réels, rôles/champs forgés, provenance,
rejeu après réouverture, révocation, rollback après append, concurrence/quota,
V1/V2 mélangés, corruption hors période, valeurs non finies, doublons, JSON profond
et XSS. Les sources sont fictives. La passe antérieure de 119 cas et le rouge Ruff
restent [archivés séparément](/workspace/poursuite-opsys-2026-10-02-r1/M7-GROWTH-HUMAIN-ROOT-r1/);
ces campagnes se recouvrent et ne s'additionnent pas.

Cette tranche ne qualifie pas de source analytique externe, dictionnaire commun de
métriques, baseline, causalité, croissance ou ROI. Aucun fournisseur, publication,
OAuth, navigateur, mobile dédié, PostgreSQL d'écriture ou VPS n'est qualifié. Le
writer legacy demeure compatible; ses quotas d'écriture ne sont pas rétroactivement
garantis. La prochaine tranche pourra exploiter ces observations dans une stratégie
CMO durable, en distinguant objectifs, hypothèses et résultats déclarés.

Sources : [writer](../../../departments/m07-marketing/src/m7_marketing/growth.py),
[lecteur](../../../departments/m07-marketing/src/m7_marketing/growth_lecture.py),
[routeur](../../../src/opsys/console/marketing_growth_ui.py),
[commande privée](../../../src/opsys/console/metier.py),
[matrice](M7-MATRICE-CAPACITES-2026-09-30.md).
