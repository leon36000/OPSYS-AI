# R25 — qualification de la mémoire PostgreSQL existante

Le 2 octobre 2026 UTC, la suite ciblée ROOT passe **82 tests, zéro échec, erreur ou skip**.
Elle inclut le vrai PostgreSQL 17.11 avec pgvector pour le store et les parcours des outils
mémoire. Les embeddings proviennent de doubles déterministes et d'un endpoint HTTP local
fictif. Ce résultat vérifie le fonctionnement de ces composants; il ne mesure pas la qualité
sémantique d'un modèle réel ni l'assimilation générale d'une entreprise.

## Problème, décision et portée

La mémoire existante, `src/opsys/memoire`, possède déjà les documents/fragments, les filtres,
la recherche française, la fusion RRF, la rétention et l'effacement journalisé. L'échec
antérieur `ENOSPC` pendant `initdb` empêchait sa vérification locale. Aucun stockage parallèle
ni modification du runtime de production n'a été ajouté.

La fixture de test accepte désormais `stockage_en_memoire=True`, booléen strict contrôlé avant
tout appel Docker. Ce mode utilise l'image déjà présente, `--pull=never`, une limite conteneur
de 512 MiB et un tmpfs de 256 MiB sur `/var/lib/postgresql/data`. Le port est publié uniquement
sur 127.0.0.1. Chaque conteneur porte un nom aléatoire et le nettoyage vise uniquement son ID
complet, avec ses volumes anonymes. Le mode par défaut conserve le comportement historique.

Image exécutée : `pgvector/pgvector:pg17`, digest local
`sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f`.
Aucun téléchargement ou build d'image. Les seules modifications du lot portent sur quatre
fichiers de tests : la fixture commune, ses tests simulés, le fixture du store et celui des
outils mémoire. Les assertions existantes du store et des outils sont conservées.

## Preuves et résultats

Campagne ROOT finale : **05:11:56 à 05:12:16 UTC**, durée JUnit **19,477 s**.
Les **1 093 empreintes sélectionnées** sont identiques avant/après. Cet ensemble surveille les
sources Python/configurations déclarées par le harnais et quelques liaisons Core explicites;
il ne constitue pas une qualification de tout le dépôt.

| Fichier de tests | Cas inclus |
|---|---:|
| Store mémoire | 26 |
| Outils mémoire départementaux | 14 |
| Client embeddings contre HTTP fictif | 11 |
| Raccord de configuration OpenClaw | 20 |
| Fixture Docker simulée et diagnostics | 11 |

Les 82 cas vérifient notamment l'idempotence du schéma et des fragments, les index HNSW/GIN,
le français insensible aux accents, les rangs/provenances RRF, les filtres, les portées des
manifestes et le département fixé par le serveur. Ils couvrent aussi la rétention, l'effacement
en cascade, le rattrapage des vecteurs, le repli textuel explicite, le refus d'envoyer des données
personnelles à un endpoint non déclaré local, le budget de sortie et les commandes mémoire.
Le jeu d'or est fictif; ses résultats ne sont pas un score de mémoire premium de production.

Ruff sur quatre fichiers et `git diff --check` passent séparément, sur les mêmes empreintes.
Les ID des conteneurs présents avant la première campagne et après la finale sont identiques.
La première campagne de 37 cas est incluse dans la finale; les comptes ne s'ajoutent pas.
Les préimages, commandes, XML, journaux et reçus sont conservés dans
[R25](../research/R25-2026-10-02/README.md).

Le préflight auxiliaire ROOT r2 a demandé un champ de reçu mal nommé; la vérification a été
corrigée et datée après la campagne, sans antidater le reçu. Le harnais de test possède sa
capture effective avant et après exécution. La correction temporelle et l'échec auxiliaire
restent archivés; aucune assertion métier n'a été assouplie.


## R31 — mesure de ranking sur pgvector réel

ROOT a exécuté les 15 tests d'oracles métriques et les 3 scénarios R31 contre PostgreSQL 17 + pgvector réel. Résultat : **18 passés, zéro échec/erreur/skip**, JUnit 5,116 s; les 1 113 empreintes sélectionnées restent identiques. Le test vérifie le SHA réel de `jeu_or_fr.json` avant son chargement et compare un jeu de qrels versionné séparément (`evaluation-v1.json`). La portée mesurée est exactement 9 questions et 12 fragments (development 6, holdout 3), non une couverture représentative d'entreprise.

| Mode | Split | Questions | Recall@5 | P@5 | MRR@10 | nDCG@10 | forbidden-hit@10 |
|---|---|---:|---:|---:|---:|---:|---:|
| Lexical | all | 9 | 0,5556 | 0,1111 | 0,5556 | 0,5556 | 0,3333 |
| Lexical | development | 6 | 0,5000 | 0,1000 | 0,5000 | 0,5000 | 0,5000 |
| Lexical | holdout | 3 | 0,6667 | 0,1333 | 0,6667 | 0,6667 | 0,0000 |
| Double déterministe | all | 9 | 1,0000 | 0,2000 | 0,9444 | 0,9590 | 1,0000 |
| Double déterministe | development | 6 | 1,0000 | 0,2000 | 0,9167 | 0,9385 | 1,0000 |
| Double déterministe | holdout | 3 | 1,0000 | 0,2000 | 1,0000 | 1,0000 | 1,0000 |

Le double est le sac de mots/trigrammes déterministe des fixtures, jamais un modèle sémantique. Son `forbidden-hit` de 1,0 signifie que chaque question a au moins une source jugée indésirable dans le top 10. Il reflète les étiquettes négatives des qrels, **pas une décision ACL ni un accès réellement interdit** : le banc classe avec les portées autorisées en bloc. Le parcours de filtre département est séparé. L'autorité d'un sujet client demeure le contrat de sécurité d'une revue distincte et n'est pas prouvée par ces tests.

Ceci est un smoke test du comportement de ranking sur 12 fragments. Ni qualité d'un modèle réel, latence p95, coût réel, stabilité sur un corpus de production ou seuil premium ne sont qualifiés. Les métriques lexicales et double, leur mode, hash du corpus et qrels sont attachés au JUnit ROOT `metriques-pg-root-r1.xml` (SHA-256 `4000422a10ce0ade7344960b5e4cdc5fe8ad0e1c3540b214193ac79d030f2824`), campagne `memoire-metriques-pg-root-r1-2026-10-02`; archive compacte R31 en préflight séparé, exécution ROOT seulement.

## Limites et suite

Le tmpfs ne qualifie ni la durabilité sur disque, ni un redémarrage, une sauvegarde, une
restauration, une charge massive ou une installation VPS. Les autres fixtures PostgreSQL
restent dans leur mode historique tant qu'elles n'ont pas été qualifiées séparément.

Le pilote CSV financier et l'autorité des tickets C02 refusent toujours PostgreSQL dans leurs
propres périmètres. R25 n'enlève pas ces refus. Il ne modifie ni les écritures comptables, ni
les contrats M10, ni les rôles de production. Il ne prouve pas un tour Gateway/LLM réel.

La suite du [plan](REPRISE-PLAN-2026-10-02.md) doit relier un corpus de procédures autorisées
au store existant : sources/version/positions, ingestion bornée, idempotence, recherche par
source, effacement et évaluations représentatives. PDF/OCR, classement massif, tenant,
confidentialité par principal et apprentissage longitudinal restent des critères distincts.
