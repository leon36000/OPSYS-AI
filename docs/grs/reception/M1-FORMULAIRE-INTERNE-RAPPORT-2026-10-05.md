# M1 — Pont interne de demandes du site

Date : 5 octobre 2026 UTC. **QUALIFIÉ LOCAL**, périmètre ci-dessous ; M1 et OPSYS-AI
restent **PARTIEL**. Changements préparés localement, non publiés : la dernière
tentative de lecture GitHub reste refusée par HTTP 401.

## Comportement livré

Le pont `POST /interne/m1/formulaire` est monté dans la vraie fabrique de console,
désactivé par défaut. Une configuration machine explicite permet de recevoir un courriel,
un message et leurs UTM depuis un serveur de site autorisé. Une demande de gouttières
à Laval traverse `Capacites.appeler`, le registre durable M1 et son événement transactionnel.
Le vrai consommateur M2 transforme ensuite cet événement en dossier CRM. La réception HTTP
ne promet pas que le répartiteur M2 a déjà travaillé.

Le serveur n’invente pas d’identité humaine : le courriel du visiteur reste déclaré,
non vérifié. Aucun message client, rendez-vous, publication ou paiement n’est exécuté.
Le rejeu exact garde un seul signal M1 et un seul événement de lead ; M2 publie normalement
son événement interne `m2.client_associe` lors de la consommation, ce qui n’est pas un envoi client.

La clé HMAC dédiée doit être fournie côté serveur avec `site_formulaire` et
`secret_formulaire` à `creer_application`. La fabrique refuse la réutilisation de la clé
des cookies. Aucun paramètre CLI, environnement, champ navigateur ou écran de configuration
ne l’active implicitement. Sans configuration ou M1 installé, le pont répond 503.

Le protocole signé couvre `v1`, `POST`, le chemin canonique `/interne/m1/formulaire`,
le site, le timestamp, le nonce et les octets du JSON, séparés par des sauts de ligne.
Une fenêtre de ±300 secondes s’applique. Site et outil sont fixés côté instance ; les
en-têtes d’authentification dupliqués sont refusés. Le flux est borné à 24 000 octets,
le message à 4 000 octets, le contact à 254 et chaque UTM à 200. Les réponses sont
génériques, sans cache ni écho de données privées.

Les erreurs de configuration métier et le budget épuisé renvoient 503, pour que le serveur
du site conserve la demande. Le profil, la zone et les services suivent les verdicts du
socle existant. La route n’évite pas ces contrôles. Un JSON ambigu, un surrogate Unicode
invalide ou une structure non conforme est refusé en 400 sans écriture.

Fichiers : `src/opsys/console/formulaire_recepteur.py`, montage dans `application.py`,
`tests/test_formulaire_recepteur.py` et `tests/test_console_formulaire.py`.
Le [design](M1-FORMULAIRE-INTERNE-DESIGN-2026-10-05.md) explique le choix de cette tranche.

## Vérification ROOT

**r220 : 438/438 tests**, 14 fichiers complets, aucun échec, erreur ni skip.
Ruff et `opsys-metier verifier` réussissent. Le contrôle source avant/après garde
**1 323 chemins identiques** ; durée totale du pilote : **40,577 secondes**.
Les reçus vérifient l’attribution unique des cas, les limites de ressources, l’absence
de changement des compteurs OOM et l’absence de processus survivant. Cela ne remplace
pas une CI GitHub au SHA courant.

| Fichiers complets | Cas |
|---|---:|
| Pont interne / montage console | 25 / 6 |
| Console générale / configuration OCR / PDF natif / console OCR | 46 / 15 / 49 / 14 |
| Réception / réception canal / UTM / conversation | 90 / 25 / 69 / 38 |
| Rejeu M1–M2 / HTML du site / capacités / plaintes | 3 / 10 / 10 / 38 |

Le nominal HTTP dans la vraie application exerce SQLite migré, le répartiteur, l’outbox et
le consommateur M2 réels, avec données fictives. Les autres tests du routeur utilisent
le même moteur métier ; horloge, configuration et requêtes sont fictives. La lecture HTML
ne prouve pas un envoi navigateur. Les régressions OCR vérifient l’interface existante,
sans nouvelle qualification d’un worker ou d’un corpus OCR dans cette campagne.

Historique conservé : r214, six échecs avant montage de la console ; r215, 25P/1F car le
test comptait incorrectement l’événement normal M2 comme un envoi ; r216, 30P/1F avec
deux erreurs de montage des nouveaux cas ROOT (capacité au lieu de sa méthode et Unicode
doublement échappé) ; r217, **27P/4F** sur les trois profils invalides et le surrogate ;
r218, **31/31** après correction ; r219, collecte des 438 cas ; r220, campagne complète.
Les sorties antérieures du worker sont aussi conservées, y compris les erreurs de runtime,
de fixture, de style et de construction de requête. Son gel final compte 20 cas en r7
(2,29 s), code `420ef983…`, tests `2769b281…` ; son rapport figé contient encore l’ancien
SHA de tests et un libellé de r6. Le reçu ROOT de promotion corrige cet écart sans l’écraser.

La revue statique indépendante a identifié le problème de classification des profils.
Son hypothèse de HTTP 500 sur le JSON était trop forte : ROOT a reproduit une 503 sur
le surrogate, puis une 400 après correction. Le corps d’erreur reste opaque.

Preuves et variantes :
[capsule](../../research/REPRISE-2026-10-05/preuves/M1-FORMULAIRE-INTERNE-r1.tar.xz),
[manifeste](../../research/REPRISE-2026-10-05/preuves/M1-FORMULAIRE-INTERNE-r1.json).

## Limites et suite

Le formulaire HTML garde son marqueur et reste débranché. Le protocole court refuse un nom
ou téléphone secondaire non vide, car le contrat canonique ne sait pas encore les conserver
comme contact déclaré. Une clé n’est jamais mise dans le navigateur. Le serveur public du
site, son stockage de reprise, les coordonnées supplémentaires, TLS, restriction réseau,
limitation de débit, rotation des clés et qualification VPS restent à réaliser.

Rejouer la même enveloppe est possible dans la fenêtre de 300 secondes. Au-delà, changer
le timestamp avec le même nonce devient une contradiction M1 : la résolution après expiration
reste opérateur, sans création automatique d’un nouveau nonce. Concurrence, perte de réponse
après commit, reprise réseau et volumétrie ne sont pas qualifiées par cette campagne.
Les budgets et politiques existants restent applicables ; une réception sans perte absolue
n’est pas démontrée. Aucun nouveau chemin de capture M10 général n’est annoncé.

La suite produit doit d'abord conserver les contacts secondaires sous un contrat canonique
et définir la reprise du serveur émetteur avant d'activer le formulaire public.

## Addendum — portée du rejeu signé, 11 octobre 2026

**Préparé ; qualification fraîche en attente.** Les résultats historiques ci-dessus ne
qualifient pas ce changement. Le rejeu générique M1 conserve sa règle documentée au §13.3
de `M1-canaux.md` : un UTM différent n'écrit rien et peut rendre `non_porte`.

Le pont HTTP signé exige désormais, pour un même site et nonce, le même UTM que la ligne
signal persistée, et pas seulement celui d'un lead. Changement, ajout ou retrait d'UTM
valide est refusé en 400 avant toute restitution de doublon, y compris pour une demande
incomplète ou une plainte. Une absence historique reste une absence ; aucun maillon
n'est réécrit. L'ordre des clés JSON n'est pas identitaire. Un nouveau nonce suit le
traitement ordinaire, sans remplacement d'un lead déjà gelé.

Une portée immutable liée au signal et à l'UTM est posée après HMAC dans le worker
synchrone, puis restaurée dans `finally`. M1 vérifie la cohérence de cette portée avant
même un premier signal. Aucune permission supplémentaire, identité humaine, variable
d'environnement, argument public ou table de réception n'est créée.

Les oracles préparés couvrent la divergence signée, le rejeu générique conservé,
les premières écritures incohérentes, la plainte sans lead, le reset et deux workers
SQLite concurrents au même nonce. Leurs résultats restent à constater ; ils ne
prouveront ni la reprise du serveur public, ni PostgreSQL, ni une identité de visiteur.
