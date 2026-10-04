# M10 — Consolidation planifiée : conception approuvée

> **État actuel au 30 septembre 2026 : choix A approuvé par le root et implémenté pour le développement seulement.**
> Le worker, les grants révocables, le canon des rapports et la CLI humaine existent désormais.
> Les mutations du job exigent une SQLite **persistante sur fichier** ; aucune sérialisation PostgreSQL n'est revendiquée.
> Le [guide actuel](M10-CONSOLIDATION-PLANIFIEE.md) décrit les interfaces et preuves du nouveau job,
> dont une vraie probe Gateway/cron sur un même hôte synthétique. Aucun parcours nocturne VPS n'est prouvé.
>
> **Archive de conception initiale ci-dessous.** Les formulations prospectives, chemins envisagés et 36 tests
> du socle décrivent l'état avant implémentation ; ils ne constituent pas une preuve du nouveau job.

Date de conception initiale : 30 septembre 2026. Choix A retenu ; B reste une alternative non implémentée.
But : auditer les sources et relations, conserver un rapport nocturne expurgé et un modèle de soi sourcé,
puis reprendre les travaux interrompus sans déclarer une tâche, une preuve ou M10 « terminé ».
Périmètre : développement et consolidation d'affaires restent deux traitements autorisés séparément.
Références : [définition M10](../../produit/DEFINITION-PRODUIT.md#m10--mémoire-long-terme-intelligence-conscience-opérationnelle),
[mémoire de développement actuelle](M10-MEMORY-DEVELOPPEMENT.md), [recherche R16](../../research/R16-2026-09-30/recherche-m10.md).

## Ce qui existe réellement

- [`consolidation.py`](../../../departments/m10-memoire/src/m10_memoire/consolidation.py), lignes 115–171 :
  résumé déterministe par `(affaire_id, jour)` ; rejeu sans nouvelle source sans écriture ; arrivée tardive
  produisant un nouvel agrégat avec toutes les sources, sans écraser les versions précédentes.
- [`developpement.py`](../../../departments/m10-memoire/src/m10_memoire/developpement.py), lignes 1184–1401 :
  audit des liens, claims et fraîcheurs, plafonné et explicitement partiel ; cette lecture ne persiste aucun rapport.
  `_connexion`/`_charger_registre`, lignes 260–384, reconstruisent **tout** le canon en SQLite mémoire à chaque appel.
- [`department.yaml`](../../../departments/m10-memoire/department.yaml), lignes 25–32, décrit déjà une nuit à 03:00.
  [`openclaw.py`](../../../src/opsys/openclaw.py), lignes 686–695, la projette en `--message` pour un agent :
  ce chemin demande un tour de modèle et ne constitue pas le job déterministe de développement proposé ici.
- Le cron natif conserve admissions/reçus et rattrapage dans
  [`timer-catchup.ts`](../../../core/src/cron/service/timer-catchup.ts) ;
  [`command-runner.ts`](../../../core/src/cron/command-runner.ts), ligne 92, exécute `payload.kind="command"`
  sans démarrer de modèle ; [`register.cron-add.ts`](../../../core/src/cli/cron-cli/register.cron-add.ts),
  lignes 160–241, accepte `--command-argv`, timeout et plafond de sortie.
- [`serveur_mcp.py`](../../../src/opsys/serveur_mcp.py), lignes 193–200 et 264–275, possède seulement
  une boucle de répartition du bus dans le cycle de vie HTTP, pas de calendrier M10 durable.

## Deux choix d'ordonnancement

| Choix | Déclenchement et coût | Limites |
|---|---|---|
| **A — cron natif du Core, recommandé** | Commande Python à argv fixes, sans shell ni modèle ; réutilise le runtime installé, reçus et rattrapage. | Le Gateway doit fonctionner ; son reçu ne prouve pas l'atomicité du travail M10. Autorité du job et canon M10 restent vérifiés en Python. |
| **B — boucle du serveur MCP existant** | `datetime`/`zoneinfo` pour les créneaux, tâche anyio dans le cycle de vie déjà présent ; même runner et état durable. | Ajouter soi-même calendrier/rattrapage ; plusieurs workers exigent le même lease durable. Le mode stdio ne possède pas ce cycle de vie HTTP. |

Recommandation A : le Core possède déjà la brique utile ; aucun nouveau service, modèle, Temporal,
graphe, magasin vectoriel ou abonnement n'est requis. Le payload sera une commande structurée du runner
proposé, distinct de la CLI mémoire interactive. Aucun secret dans argv, input cron persistant ou stdout.
Pour un VPS sans Gateway, B réutilise le processus métier présent. Un timer systemd/cron hôte ou un cron
de conteneur peut déclencher le **même** runner en adaptation facultative ; cron classique ne rattrape
pas seul les nuits manquées. Aucun service cron supplémentaire n'est obligatoire ni déployé par cette conception.

## Principal de service et frontière humaine

Le runner proposé reçoit un `job_id`, jamais une personne ou un rôle. Une autorisation durable contient
`instance_id`, principal `service:m10-consolidation`, domaines permis, racines Git admises, version,
plafonds et révocation. Une capacité opaque authentifie ce principal ; seul son hash est conservé en base.
Le secret est lu depuis un fichier/credential protégé par l'OS, jamais depuis une identité en variable d'environnement.
L'activation et la révocation passent par une session humaine admin/owner authentifiée ; le runner relit
l'autorisation avant chaque lot et juste avant l'écriture, dans la transaction qui accepte ce lot.
Il peut lire le canon autorisé et ajouter ses rapports ; consolider les affaires exige une portée distincte.
Il ne peut modifier prompts/plans/claims humains, arbitrer une contradiction, marquer `done`, changer
permissions, expurger/supprimer le canon, publier, déployer ni déclencher un autre outil métier.
Ne pas fabriquer `IdentiteAppelante(..., "admin")`, élargir `_acteur` à tous les appels, ni réutiliser un mot de passe humain.
La CLI [`memoire_developpement_cli.py`](../../../src/opsys/memoire_developpement_cli.py), lignes 22–35 et 222–244,
garde son TTY et son authentification interactive. Le runner possède une entrée étroite indépendante.
**C01 reste une limite OS** : un agent partageant les droits sur DB/credentials peut contourner le processus.
Un fichier de secret, un contexte Python ou une chaîne de hash ne résout pas cette limite ; vérifier la
séparation effective des comptes/processus/credentials avant d'annoncer l'isolation en production.

## Rapport durable et modèle de soi

Chemins d'implémentation envisagés : runner `src/opsys/memoire_consolidation.py`, analyse déterministe
dans `departments/m10-memoire/src/m10_memoire/` ; ils **n'existent pas encore** et ne sont pas des commandes livrées.
Les rapports de développement utilisent un registre canonique append-only distinct, proposé comme
`m10-memoire/rapports_developpement`, avec contrat de type à ajouter explicitement. Pas de fichier JSON
local servant de seconde vérité ; export JSON/Markdown seulement comme dérivé reconstruisible.
Chaque version garde job/run, créneau, fuseau, révision de configuration/analyse, têtes des entrées,
commit **et empreintes réelles des fichiers** du checkout, bornes, omissions, résultats et références résolvables.
Les données d'affaires restent dans leur domaine ; aucun contact, montant ou mémoire privée n'est copié
dans le rapport de développement. Les agrégats existants d'affaires restent dans `registre_affaires`.
Réutiliser l'expurgation avant persistance et ne conserver que codes, références, hashes et courts détails
nécessaires ; pas de prompts bruts, credentials, logs libres ni copie intégrale du dépôt dans le rapport.
Le modèle de soi est une vue de mission, modules/outils/modes, portes, versions et limites : chaque élément
distingue état **déclaré**, code **observé**, preuve **disponible** et hypothèse. Un test vert ne suffit pas
à déclarer un module complet ; absence de preuve, source périmée, conflit et scan partiel restent visibles.
Les rapports n'entrent pas dans leurs propres sources de consolidation : éviter une boucle auto-alimentée.

## Transactions, reprise et arrivées tardives

Créneau proposé : 03:00 `America/Toronto`, horloge serveur ; `jour_de` métier conserve la date écrite
dans chaque source, sans conversion silencieuse de fuseau. Le runner ne dépend pas d'une horloge de modèle.
Un état opérationnel minimal en DB garde créneaux dus, curseurs, lease expirant et numéro de fencing ;
ce n'est pas une nouvelle vérité documentaire. Reprise depuis rapports/checkpoints canoniques après restauration.
Clé de rejeu : instance + domaine + créneau + version d'analyse/configuration + empreinte des sources admises.
Même clé/même charge retourne le résultat existant ; même clé/charge différente produit un conflit explicite.
À l'admission, figer les têtes et le périmètre ; une lecture concurrente doit être cohérente ou signalée obsolète.
À la validation, relire grant et fencing ; écrire rapport, checkpoint et consolidation d'un lot dans la
même transaction OPSYS. **Décision d'implémentation : SQLite fichier avec `BEGIN IMMEDIATE` seulement.**
Le CAS/rang ne sérialise pas à lui seul révocation et validation sous PostgreSQL `READ COMMITTED` ;
autoriser/révoquer/exécuter y sont refusés, les autres fonctions mémoire PostgreSQL restent distinctes.
Ne pas promettre une transaction atomique avec un fichier exporté, un autre magasin ou le reçu du cron Core.
Crash avant commit : lot rejouable sans sortie ; après commit avant reçu : retrouver la clé et ne pas doubler.
Un ancien worker dont le lease a expiré ne peut valider : fencing vérifié au point d'écriture.
Les arrivées tardives sont repérées par nouveaux rangs observés, puis groupées par ancienne `(affaire, jour)` ;
ne pas limiter la nuit à « hier ». Recalculer l'ensemble complet des sources de la période touchée et ajouter
une nouvelle version, comme la consolidation actuelle. Relation/source tardive ouvre aussi une révision d'audit.
Rattrapage paginé des créneaux dus au démarrage, avec backlog visible ; pas de suppression des périodes anciennes.

## Bornes, hors ligne et preuves de sortie

Conserver la reconstruction canonique complète et la validation de chaîne ; ne pas remplacer le canon
par une projection persistante implicite. Les caps d'analyse actuels ne bornent **pas** ce coût de reconstruction.
Plafonds initiaux : 500 fichiers, 256 000 octets/fichier, 8 000 000 octets/scan, 5 000 événements,
10 000 relations, 500 sources/constats ; temps du job 600 s et sortie cron 64 Ko, ajustables à la baisse.
Journal trop volumineux, timeout ou source absente : échec/rapport partiel avec omissions, aucun faux succès.
Hors ligne : Git local et SQLite local fonctionnent sans fournisseur ; DB distante indisponible bloque le lot,
les références externes restent inconnues. Les fichiers non suivis/exclus ne sont pas réputés capturés.
Probes réellement exécutées sur état temporaire : **36/36** tests `test_consolidation.py`,
`test_registre_durable.py`, `test_developpement.py` ; zéro échec/erreur/saut, aucun Docker ni clé fournisseur.
Elles prouvent le socle actuel : rejeu/late arrival, relecture durable/restauration, expurgation et refus CLI non interactif.
Le cron Core est inspecté statiquement ici ; **aucun nouveau job, principal de service ou parcours VPS n'est prouvé**.
Avant livraison : tester grant absent/révoqué/mauvaise portée, double worker/lease périmé, crash aux deux côtés
du commit, sauvegarde/reprise, source tardive ancienne, chaîne invalide, caps/timeout, absence réseau et fuseau.
La décision attendue lors de cette conception a été rendue : choix A, développement seulement,
implémentation et preuves actuelles dans le guide lié en tête.

PREUVE: `m10-consolidation-design-existant.xml/.log` dans les preuves de restructuration du 30 septembre ; conception seulement.
