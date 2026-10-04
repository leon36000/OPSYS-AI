# M7.4a — Lecture privée des observations Growth déclarées

Actualisation du 3 octobre : ce document conserve le contrat et les preuves de la
tranche R19. La [saisie humaine V2](../../../docs/grs/marketing/M7-GROWTH-SAISIE-HUMAINE-2026-10-03.md)
étend maintenant la console avec deux POST privés et une provenance serveur.
L'auteur des observations V1 reste inconnu; leur source n'est pas vérifiée.

Statut produit : **PARTIEL**, code intégré localement par ROOT R6 le 1er octobre 2026 à **18:01:32 UTC** sur sept chemins. La campagne ROOT est close à **18:03:51 UTC**. La documentation R19 décrit ces sources et preuves locales; M7 demeure PARTIEL.

Cette tranche consulte les observations déjà enregistrées dans les maillons `m07-marketing/growth`. Elle réutilise le stockage, le codec et la console OPSYS, sans nouvelle dépendance ni outil MCP. Une valeur persistée demeure une déclaration : aucune saisie humaine n’est prouvée, l’auteur et sa provenance sont inconnus, et la référence de preuve n’est pas vérifiée.

## Parcours et accès

La console expose `GET /marketing/growth` et `GET /api/marketing/growth`, sous le préfixe de console configuré. Sans filtre, la page présente le formulaire de consultation sans lire le registre. L’API exige `debut` et `fin`. Le formulaire ne crée ni observation ni plan; aucune route de mutation Growth n’est ajoutée.

Une personne doit être actuellement active avec `nathan_owner` ou `admin`. La console contrôle cette identité avant la lecture puis dans une nouvelle transaction avant la réponse. Une identité inactive est refusée (401), un rôle insuffisant aussi (403). Le lecteur métier n’authentifie pas l’appelant lui-même : l’autorisation de cette surface est portée par la console. Les réponses portent `Cache-Control: no-store` et `Pragma: no-cache`; les champs de déclaration sont échappés dans le HTML.

## Filtre, comptes et pagination

| Paramètre | Contrat |
|---|---|
| `debut`, `fin` | Dates civiles canoniques `AAAA-MM-JJ`; `debut ≤ fin`; au plus **366 jours inclusifs**. |
| Inclusion | Toute la période de l’observation doit être dans le filtre fermé `[debut, fin]`; un chevauchement est exclu. |
| `decalage` | Entier de 0 à 1 000; défaut 0. |
| `limite` | Entier de 1 à 100; défaut 25. |
| Requête console | Paramètre inconnu ou répété, date ou pagination invalide : HTTP 400. |

Le résultat garde l’ordre des observations dans les maillons et expose `total_observations`, `total_periode`, `hors_periode`, la page et `suivant`. Ces comptes portent sur les observations enregistrées, pas sur l’activité réelle de l’entreprise. « Aucune observation enregistrée » ne signifie pas zéro activité.

Chaque requête relit le registre et borne son préfixe au rang maximal observé. **La pagination est fraîche, sans instantané multipages** : un ajout entre deux appels peut modifier les comptes et les pages. La borne de rang d’un appel ne fige pas les appels suivants.

## Bornes et refus

Les limites portent sur **tout le registre Growth**, plans ignorés compris, avant le décodage des charges :

| Limite | Unité exacte |
|---|---|
| Nombre de maillons | 1 000 maximum. |
| Taille d’un maillon | 32 Ki caractères = 32 768 caractères de texte JSON. |
| Taille totale | 1 Mi caractères = 1 048 576 caractères de texte JSON. |

Ces tailles sont en **caractères, pas en octets**. Les agrégats SQL parcourent le registre : les plafonds bornent les charges décodées, pas le temps du moteur SQL. Les statistiques SQL précèdent le décodage; le transfert est borné par `SUBSTR`, le nombre de textes et leurs longueurs sont revérifiés. Un changement de nombre pendant la lecture, un dépassement ou une corruption refuse la réponse (HTTP 409), sans réponse partielle ni append.

Les observations exigent une forme exacte, des champs textuels non vides bornés, une valeur numérique finie, une confiance déclarée finie entre 0 et 1, des dates cohérentes, une empreinte de charge conforme et un `observation_id` unique. **Cette validation précède le filtre : une observation corrompue hors période ferme aussi la lecture.** Les erreurs de décodage prises en charge sont converties en refus nommé; une observation simplement retypée `plan_growth_30j` ne doit pas être masquée.

Les plans historiques `plan_growth_30j` sont ignorés seulement si leurs clés top-level sont exactement `type`, `horizon_debut`, `recommandations`, `donnees_manquantes`, `limites`. Leur contenu sémantique n’est pas qualifié par ce lecteur. Une empreinte d’observation détecte une altération non rehashée; elle n’authentifie pas l’auteur, la source externe ou une chaîne inviolable face à un opérateur privilégié.

## Vérité des données et limites

Chaque observation conserve valeur, unité, période, plateforme, campagne, source, référence textuelle de preuve et confiance déclarée. Le lecteur ajoute `statut_source: DECLAREE_NON_VERIFIEE`, `auteur: null` et `verification_externe: null`. Aucun accès réseau ou CAS ne vérifie la référence; elle n’est pas un reçu externe ni une pièce authentifiée. La fraîcheur de la pagination ne prouve pas celle de la source.

Cette consultation ne prouve aucune saisie humaine, définition commune de métrique, baseline, budget, capacité ou résultat du plan. Elle ne calcule aucune croissance, causalité, projection ou ROI, ne génère aucun plan/recommandation et ne publie rien. Les écritures et plans historiques de `growth.py`, les faits M2/M3/M5 de performance campagne et la console CMO restent des capacités distinctes.

La lecture de code et les tests locaux ne qualifient ni un navigateur réel, une surface mobile Growth, un VPS, une connexion analytics/CRM externe ou une concurrence PostgreSQL. Aucun de ces parcours n’est revendiqué par ce document.

## Sources et preuves ROOT closes

Sources intégrées : [lecteur](../src/m7_marketing/growth_lecture.py), [registre/écritures existants](../src/m7_marketing/growth.py), [routeur console](../../../src/opsys/console/marketing_growth_ui.py), [montage](../../../src/opsys/console/application.py) et [navigation marketing](../../../src/opsys/console/frontoffice_marketing.py). Les [tests du lecteur](../tests/test_growth_lecture.py) et [tests console](../../../tests/test_console_growth.py) sont exécutés dans les preuves closes ci-dessous; leur présence seule ne qualifierait pas un parcours.

Les six rouges ROOT d’étiquettes codec null/Decimal (500), puis les deux rouges d’observation retypée en faux plan (200 masqué), sont des reproductions historiques distinctes de la campagne intégrée close ci-dessous. Les corrections R6 convertissent les erreurs de décodage en refus nommé et vérifient la forme historique top-level avant exclusion. Ces rouges restent distincts de la passe ciblée ROOT R6 de **59 cas (28 lecteur + 31 console)**, verte sur le candidat. Les mêmes 59 cas sont inclus dans la campagne ROOT intégrée ci-dessous; ils ne s’y ajoutent pas.

La campagne intégrée ROOT du 1er octobre 2026, de **18:01:32 à 18:03:51 UTC**, passe **1 436 cas**, sans échec, erreur ni skip, en **137,133 s JUnit** : **1 066 M7**, **279 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier MCP SQLite**. Les **59 cas Growth (28 lecteur + 31 console)** sont inclus dans ces groupes, sans addition. Deux cas PostgreSQL sont désélectionnés par `-k not postgresql`; ce ne sont pas des skips. Les **1 070 chemins sources sélectionnés** sont identiques avant/après; cet ensemble n’est pas une fermeture de tout le dépôt. Ruff sur sept fichiers et le catalogue (**10 départements, 207 outils, 116 déclarés aux appareils**) passent dans des commandes distinctes. Les qualifications R18 et antérieures gardent leurs arbres; leurs comptes ne s’ajoutent pas à 1 436.

Preuves ROOT closes : [résultat](../../../docs/research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-resultat-json-39d3b4870b.gz) · [JUnit](../../../docs/research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-xml-c8db58b5f3.gz) · [journal](../../../docs/research/R20-2026-10-01/preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-log-8c7e9f181c.gz) · [promotion R6](../../../docs/research/R20-2026-10-01/preuves/r19-m74a-integration-root-r6--resultat-json-1909dc8172.gz) · [Ruff](../../../docs/research/R20-2026-10-01/preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-resultat-json-3fb7557c96.gz) · [catalogue](../../../docs/research/R20-2026-10-01/preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-resultat-json-032e699528.gz) · [lecture indépendante](../../../docs/research/R20-2026-10-01/preuves/r19-m74a-cloture-independante-r1--rapport-json-190e148f67.gz). Ces preuves sont conservées dans les archives R20, sans modifier le R19 scellé du 30 septembre.

Témoins historiques ROOT : [rouge codec R5](../../../docs/research/R20-2026-10-01/preuves/r19-proofs--red-codec-r5-resultat-json-7b6fe0e1d8.gz) · [rouge faux plan R6](../../../docs/research/R20-2026-10-01/preuves/r19-proofs--red-pseudo-plan-r6-resultat-json-8bb2446302.gz) · [ciblé vert R6](../../../docs/research/R20-2026-10-01/preuves/r19-proofs--green-composition-r6-resultat-json-f5907d0df1.gz). Les résultats auteur/QA antérieurs restent historiques sur leurs propres sources et ne prouvent pas le lecteur ROOT final.

État global : [bilan](../../../docs/programme/BILAN-RESTRUCTURATION-2026-09-30.md), [programme](../../../docs/programme/RESTRUCTURATION-2026-09-30.md), [matrice M7](../../../docs/grs/marketing/M7-MATRICE-CAPACITES-2026-09-30.md) et [audit daté](../../../docs/grs/marketing/M7-AUDIT-INITIAL.md). Les preuves M7.3a R18 y restent datées et ne s’additionnent pas à R19.
