# CRM06 — contrat pur d’un original courriel

28 octobre 2026 UTC. **Composant interne qualifié localement; suivi courriel CRM toujours MANQUANT.**

## Objectif et pourquoi

Préparer le futur reçu M1 sans prendre un résumé modèle pour le message original. Les octets
restent intacts et l’identité de réception reste indépendante de leur SHA : même identité et contenu
différent doivent devenir un conflit dans le futur propriétaire SQL, jamais un nouvel identifiant.

## État, architecture et fichiers

`src/opsys/reception_courriel_contrat.py` fournit
`valider_original(arguments: dict, *, source: bytes) -> OriginalCourriel`.
Contrat fermé, pur et sans IO, dataclass figée, coordonnées copiées une seule fois **avant** validation
et hachage, mapping privé immuable. Source et coordonnées ne figurent pas dans repr/erreurs.
`tests/test_reception_courriel_contrat.py` protège les comportements; le
[plan exécuté](../../superpowers/plans/2026-10-28-courriel-original-contrat.md) fixe les interfaces.

Aucune route, table, migration, permission, tâche, clé ou opération runtime ajoutée. Aucun connecteur
n’appelle encore ce codec. Ce composant n’est ni une archive persistante ni un journal CRM.

## Données et workflow

Identité cadrée en UTF8 : instance UUID canonique, génération de source (`source_id` SHA), compte,
boîte exacte, UIDValidity, UID. Chaque champ est précédé de sa longueur en octets; domaine de hash
versionné. Message-ID déclaratif, dates et contenu restent hors identité. Le SHA source est calculé
sur les octets, jamais fourni par le demandeur. Date interne absente = None, sans date inventée.

Taille originale 1..1 048 576 octets, comme le FETCH natif; taille annoncée identique requise. Cette
égalité contrôle la cohérence de l’entrée, **pas l’honnêteté du fournisseur ou de l’appelant**. Aucun
parseur MIME ni vérification du Message-ID contre les en-têtes n’est revendiqué. UID/UIDValidity
positifs sur 32 bits, boîte bornée à 1024 unités UTF16 comme le garde natif. Unicode non normalisé.

Appelant → copie privée → contrôles fermés → identité/SHA calculés → description immuable.
Un objet `OriginalCourriel` construit directement n’est pas un jeton d’autorité; un futur propriétaire
ne doit jamais le traiter comme tel ni omettre sa validation et son autorisation vivantes.

## Intégrations, permissions et gates Nathan

Ni droits SMS/Twilio ni origine IMAP repris. Aucun envoyé, livré ou reçu M1 déclaré. Aucun rôle
employé n’obtient l’original. Le futur stockage doit chiffrer le MIME avec une clé externe dédiée,
revalider l’autorité avant lecture/rejeu/ACK et garder un audit transactionnel. Son branchement Host,
sa politique de rétention, son rattachement projet exact et toute activation réelle restent distincts.
Aucune activation, donnée réelle ou envoi autorisé par ce composant.

## Tests et limites

Préflight M10 privé M1 frais, distinct de la mémoire projet. QA native privée `crm06-codec-v4` :
**60 PASS**, ruff 0, vérificateur natif 0 (10 départements, 306 outils inchangés). Source RO,
CPU 1, mémoire 1 Gio, PIDs 96, TTL borné, homes/tmp privés, sockets UNIX/INET4/INET6 refusées.

Vecteur identité indépendant Node crypto; octets binaires conservés; isolation instance/source/boîte;
Unicode et limites; sous-classes hostiles; immutabilité; refus de troncature déclarée. Un rouge a
prouvé l’allocation UTF16 avant le bornage (pic >4 Mo pour métadonnée de 2 Mo), corrigée par longueur
vérifiée avant encodage. Revue P2 : mutation appelant pendant hachage désynchronisant identité et
coordonnées, reproduite par injection déterministe autour du hash réel, puis corrigée en une passe
par capture privée unique. Ce test ne prétend pas être un essai de charge avec threads réels.
Les échecs de lint/prérequis et rouges restent historiques. Les 60 tests ne s’additionnent pas aux
lots précédents pour calculer une couverture produit.

## Prochaines étapes et statut

PARTIAL. Propriétaire SQL chiffré, clé externe, autorité actuelle avant lecture et rejeu, savepoint
original/reçu/audit, conflit même identité/autres octets et ACK durable. Puis capture Host privée,
ACK avant progression IMAP, liaison admin au projet exact et restitution CRM. Tant que ces parcours
ne sont pas prouvés, aucun suivi automatique complet ni réception réelle n’est annoncé.

## Évolution du propriétaire SQL

Le [stockage privé](CRM06-COURRIEL-STOCKAGE.md) consomme désormais ce codec et son identité partagée.
Il reste séparé des connecteurs et des permissions Host; ce codec seul ne constitue toujours pas un reçu.
