# M10 — préparation PostgreSQL du runner CI

## Défaut et cause

Le job natif [111523766752](https://github.com/leon36000/OPSYS-AI/actions/runs/37232080654/job/111523766752)
du commit `76e949b9540269b4d1f9639a557255d55301622c` échoue dans
`test_http_postgresql_persiste_sur_le_stockage_canonique` :
`No such image: pgvector/pgvector:pg17`.
Les logs natifs identifient cette cause, distincte des annotations génériques
« exit code 1 ». Le lint M10 réussit avant l'échec.

Le test utilise désormais le stockage PostgreSQL éphémère en RAM.
Sa fixture impose `--pull=never` : aucun téléchargement implicite pendant la
création d'un conteneur de test. Notre cache local contient l'image ; le runner
GitHub neuf ne la contient pas. Une campagne locale verte ne prouvait donc
pas la préparation de ce runner.

## Correctif borné

Une étape de `.github/workflows/ci.yml`, réservée à la matrice `m10-memoire`,
prépare l'image avant pytest. Elle lit `IMAGE_PGVECTOR` dans la fixture canonique
avec `runpy.run_path`, puis exécute `docker pull` avec délai de 900 secondes et
`check=True`. Un téléchargement impossible échoue explicitement.

La fixture, son image actuelle et tous ses tests restent identiques : stockage
tmpfs borné à 256 Mio, mémoire conteneur 512 Mio, mot de passe temporaire,
port publié sur loopback, nettoyage limité au conteneur possédé. Aucun retry,
skip, mock de PostgreSQL ou changement du code produit n'est ajouté. Le tag
préexistant reste mutable ; ce correctif ne prétend pas qualifier une nouvelle
version ni épingler la provenance de son image.

## Vérification et portée

Le bloc YAML réel est analysé puis exécuté contre une CLI Docker fictive en
RAM : la commande cible l'image de la fixture et propage son échec. Ce contrôle
diagnostique ne télécharge rien et ne modifie pas le cache partagé. `actionlint`
analyse le workflow. Les suites M10, fixture PostgreSQL et contrat de CI sont
exécutées séparément de cette simulation ; leur résultat final et leurs
sources gelées sont consignés dans les preuves associées à cette tranche.

La CI native du nouveau commit reste à observer après publication. Les anciens
relevés « en cours » restent des instantanés historiques ; l'échec constaté est
conservé, sans les réécrire. M10 et OPSYS-AI restent **PARTIEL**.

ROOT r164 réussit **1 020/1 020 sur 35 fichiers complets**, sans échec, erreur
ou test ignoré, en **45,315 s JUnit** (49,251 s campagne). Les 33 fichiers M10
et les deux fichiers socle cités sont inclus dans ce compte. Le parcours HTTP
PostgreSQL utilise le vrai moteur, avec l'image déjà présente localement.
Cette campagne ne reproduit pas un téléchargement à cache vide.
Ruff, `actionlint`, le diagnostic du bloc CI et le vérificateur métier
réussissent ; 1 250 sources surveillées restent inchangées et aucune hausse
OOM n'est relevée. Aucun test permanent qui répète le YAML n'est ajouté.

[Capsule de preuves](../../research/REPRISE-2026-10-04/preuves/M10-CI-POSTGRESQL-r1.tar.xz)
et [inventaire](../../research/REPRISE-2026-10-04/preuves/M10-CI-POSTGRESQL-r1.json) :
logs natifs de l'échec, relevés datés des heads26/27, sources gelées,
préimages et contrôles ROOT. Le contrôle des secrets porte sur les quatre
chemins texte de la publication, sans nouvelle exclusion.
