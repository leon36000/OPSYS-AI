# M10 — imports internes par lots, reprise durable

## Résultat et portée

La console administrateur admet de **un à cinq fichiers TXT/Markdown UTF-8** dans
la mémoire de procédures internes de M03. Le manifeste est enregistré dans PostgreSQL
avant les admissions. Une interruption conserve les documents déjà reçus et permet de
reprendre seulement les emplacements manquants, même avec une nouvelle instance du service.
Le produit global et le département M10 restent **PARTIELS**.

Cette tranche réutilise la console, la façade `IngestionProcedures`, le store existant,
les sources canoniques `procedure_versions.corps` et les migrations idempotentes.
Aucun nouveau moteur, copie de corps, orchestrateur ou coût LLM n'est introduit.
Le design et les alternatives sont dans [le plan adapté](M10-IMPORT-LOTS-DESIGN-2026-10-04.md).

## Parcours et contrôles

1. Ouvrir `/opsys/memoire/procedures/imports` : une clé opaque est générée dans le
   formulaire **avant** tout effet. Garder cette clé permet aussi de rejouer un POST
   dont la réponse a été perdue.
2. Fournir les titres et fichiers aux emplacements choisis, puis attester humainement
   l'absence de données personnelles/secrets. Cette attestation est **un contrôle humain,
   pas un détecteur de secrets**.
3. Tout le multipart, les limites, les titres et l'extraction des fichiers sont validés
   avant le premier DML. Le manifeste est immuable : auteur, positions, titres, SHA et
   série cible éventuelle. Une variation est refusée.
4. Chaque admission et rattachement au manifeste est atomique dans une transaction.
   Les effets sont bornés à cinq documents et s'arrêtent au premier refus ou incident.
5. L'état est consultable à `/opsys/memoire/procedures/imports/{cle}`. Reprendre via
   `POST .../{cle}/reprendre` en renvoyant le fichier exact. Un emplacement déjà reçu
   ne crée pas de deuxième version. Les positions non contiguës sont conservées.

La session administrateur est revérifiée à l'entrée, après parsing, immédiatement
avant chaque effet dans le thread de travail et avant affichage, y compris les réponses
partielles. CSRF, formulaire fermé, refus de query, limites de cinq fichiers, 1 MiB/fichier
et 5 MiB + 64 KiB de requête, erreurs expurgées et `Cache-Control: no-store` s'appliquent.
Une panne mémoire est un **503**; un conflit documentaire est un **409**; un lot absent
ou détenu par un autre auteur reste introuvable. Les noms de fichiers et corps ne sont
pas rendus dans la page d'état.

## Données et cycle de vie

`memoire.procedure_lots` et `procedure_lot_emplacements` contiennent uniquement le
manifeste; la clé de lot est stockée sous SHA-256. `procedure_lots_oublies` garde une
empreinte opaque pour bloquer son rejeu après effacement. Maximum : 64 lots vivants.
Les quotas documentaires existants restent 64 séries, huit versions par série et
64 MiB de sources. Les corps ne sont stockés qu'une fois dans le chemin canonique.

Les états `ATTENTE`, `RECU`, `INDEXE` et le nombre de versions actives sont **dérivés**
des versions/séries au moment de la lecture. L'admission ne lance ni indexation,
activation, embeddings, entraînement ni classement automatique. L'indexation et
l'activation humaine existantes gardent leur contrat.

L'oubli spécifique, l'oubli générique et la rétention doivent invalider tout manifeste
qui référence une source effectivement effacée, ainsi qu'une cible de série entièrement
effacée. Le manifeste et ses titres/SHA/références sont retirés dans la même transaction;
les autres versions indépendantes restent disponibles. Les fragments ou versions non
sélectionnés ne sont pas effacés par cet effet secondaire.

## Vérification

**Qualification ROOT r106 : 82/82 cas passent, zéro échec/erreur/skip, en 35,086 s.**
Ruff des sept fichiers Python concernés passe. Les 1 224 chemins source gelés, y compris
le SQL, sont identiques avant/après. Les gardes de 180 s et 512 MiB par groupe de
processus n'ont pas été déclenchées; aucun OOM ni survivant du groupe de test n'est relevé.
Les fixtures PostgreSQL éphémères sont réellement exécutées et fermées par leur teardown.

| Fichier de tests complet | Cas passés |
|---|---:|
| `test_memoire_ingestion.py` | 16 |
| `test_memoire_import_lots.py` | 10 |
| `test_console_memoire_ingestion.py` | 14 |
| `test_console_memoire_import_lots.py` | 17 |
| `test_console_memoire_import_lots_postgres.py` | 2 |
| `test_memoire_autorite_postgres.py` | 6 |
| `test_memoire_outils.py` | 17 |

Les tests prouvent notamment migration répétée, manifeste immuable, auteur, slots non
contigus, nouvelle instance du service, double POST, concurrence réelle, rollback SQL
après création avant rattachement, hash modifié, quota, oubli spécifique/générique,
rétention, version survivante, états dérivés et absence d'activation automatique.
Le parcours E2E console est authentifié sur la vraie application avec PostgreSQL :
premier document reçu, panne injectée au second, état partiel, reprise du seul slot 4
et identifiant du premier document inchangé. La panne est simulée, la persistance et
les transactions sont réelles. CSRF, limites, encodage/NUL, attestation et rôle retiré
pendant effet ou lecture sont aussi éprouvés.

La revue a trouvé puis corrigé trois défauts : classification `MemoireIndisponible`
comme conflit car elle hérite de `ValueError`; manifests retenus après oubli générique
ou rétention; row lock de cible pris avant l'advisory de série. La campagne rouge r105
reproduit les deux derniers sur PostgreSQL réel (79/82). Le test de verrous vérifie
qu'une création suspendue sur l'advisory laisse la ligne accessible via `NOWAIT`, puis
aboutit après libération; ce n'est pas une assertion de texte SQL.

Gitleaks ROOT r107 : **zéro alerte**, sans nouvelle règle ou exclusion. Les essais r100–r107,
leurs JUnit/logs/reçus/gels et les sources sont conservés dans
[`M10-IMPORT-LOTS-r1.tar.xz`](../../research/REPRISE-2026-10-04/preuves/M10-IMPORT-LOTS-r1.tar.xz),
avec [inventaire et empreintes](../../research/REPRISE-2026-10-04/preuves/M10-IMPORT-LOTS-r1.json).
Les copies publiées des logs expurgent les credentials des conteneurs de test déjà
fermés; le SHA des originaux et la transformation sont tracés. Aucun rouge historique
n'est remplacé par le résultat vert. Cette qualification locale ne prétend pas être
la CI native du prochain commit; celle-ci sera rattachée à son SHA après publication.

## Limites et suite

Ce parcours est **interne M03**, pas l'ingestion comptable générale d'un client ni un
outil de migration de dix ans de données. Pas de PDF/OCR, archives, formats binaires,
classification générale, ingestions arbitraires, écran mobile dédié, liste globale
historique des lots ni benchmark sur corpus réel d'entreprise dans cette tranche.
La reprise d'un fichier encore en attente exige de le renvoyer; conserver seulement
son SHA n'autorise pas à reconstruire son corps.

Aucun score d'assimilation global ni taux de « non-oubli total » n'est annoncé. Les
prochaines capacités doivent s'appuyer sur un corpus autorisé, des mappings métier,
les permissions de chaque département et des évaluations distinctes de qualité/coût.
