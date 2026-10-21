# Corrections des anomalies reproduites — 21 octobre 2026

La demande de Nathan est de vérifier chaque problème avant correction, avec trois sous-agents et
Claude Code CLI Opus 5.5, puis de tester les changements. Le parent est
`ebbddc09c4afb938535c374b710144a3c2dd9e2e` ; le produit audité était `f0b89ccf86d6f6e50eb134de3257af91860e8091`.
Les preuves historiques restent inchangées. Les tests ci-dessous sont de nouvelles régressions,
avec des données fictives, pas la réécriture d'un ancien verdict ni un rejeu d'une intention inconnue.

## Validation et correction par problème

| Anomalie confirmée | Régression avant correction | Comportement corrigé et contrôle |
|---|---|---|
| Rétention supprimant des dossiers étrangers | Nouvelle suite sur l'ancien script : 6 échecs, 1 contrôle réussi | Seuls les dossiers identifiés comme sauvegardes OPSYS éligibles sont purgés ; noms, manifestes, fichiers, liens et identité sont vérifiés. Erreurs de purge signalées. |
| Transaction SQL visant une autre base ignorée | Assertion de refus échoue avant correctif | Refus explicite avant savepoint ; les transactions imbriquées sur la même base restent valides. |
| Coût complet malgré une unité du tarif inconnue | Nouvelle suite M5 : absence/incompatibilité de l'unité reproduite | Coût partiel et marge absente ; M6 peut recevoir une unité explicitement confirmée par l'outil existant, sans modifier ni deviner les anciennes entrées. |
| Prix futur changeant un coût historique | Nouveau test d'un WCT passé avant/après ajout du tarif futur | Les prix postérieurs à la date civile du WCT sont exclus ; priorité append-only conservée entre révisions éligibles. Date ou zone absente : partiel. |
| Audio externe déclaré local | Sept configurations externes acceptées à tort ; contrôle du consentement distant conservé | Déclaration locale limitée à la boucle locale ; localhost est fixé sur 127.0.0.1, et les proxys d'environnement sont ignorés pour les adresses de boucle locale. HTTPS et consentement distinct restent requis pour un endpoint externe. |
| File mobile de A envoyée à B | RPC réel construit vers B avec note/UUID de A, SQLite fermé puis rouvert | Destination exacte persistée et revalidée avant envoi, incluse dans les CAS et récupérations de fichiers ; rotation de jeton sur A compatible. Anciennes destinations inconnues conservées en quarantaine visible. |
| Refus PostgreSQL perdant déclaré réussi | Deux scénarios perdants échouent réellement en READ COMMITTED, deux contrôles passent | Toute décision perdante vérifie le nombre de lignes réservées avant réponse, journal ou ticket. Quatre scénarios concurrents passent sur PostgreSQL 16.15 réel. |

Claude Code a réellement utilisé `claude-opus-5-5`, effort high, pour la sauvegarde, en 433,3 s,
sans dépassement de délai. Son coût annoncé de 1,3518018 USD est calculé au tarif catalogue,
pas une facture certifiée. Root a ensuite reproduit et corrigé une course supplémentaire :
un fichier étranger apparu après identification ne doit pas entrer dans l'ensemble de suppression.
Le nom courant est exclu et les suppressions restent relatives aux descripteurs ouverts.

## Vérifications exécutées

Les nombres sont des populations de tests qui peuvent se recouper ; ils ne doivent pas être additionnés.

- M5 complet : 2 553 tests réussis ; M6 complet : 1 484 réussis.
- Stockage/approbations concernés : 382 réussis, dont six scénarios PostgreSQL réels.
- Mobile complet : 238 suites, 5 637 tests réussis ; TypeScript mobile réussi.
- Root : 169 tests Python sur les corrections combinées, avec dépendances Python corrigées et
  scénarios PostgreSQL réels ; 16 tests mobiles sur destination/propriétaire relus après intégration.
- Sauvegarde/restauration ciblées après la correction Root : 86 réussis, 2 ignorés qui exigent Docker réel.
- STT/connecteur : 46 réussis ; M7 lecture de performance : 33 réussis.
- Markdown : 395 tests du graphe rapide et 22 du graphe unit ; UI de sécurité/MCP/Markdown : 135 réussis.
  `node scripts/run-tsgo.mjs -p tsconfig.ui.json` réussit. L'invocation générique de l'ancien
  compilateur sur `ui/tsconfig.json` a épuisé 4 Gio : échec d'outillage conservé, pas verdict produit.
- Dépendances Python réellement corrigées : 437 tests ciblés réussis, un contrôle CI exécuté à part
  réussi ; construction roue/sdist avec setuptools 83 réussie. La campagne M3 large a atteint sa
  borne de 180 s ; elle n'est pas déclarée complète.
- Ruff des 23 fichiers Python touchés, `bash -n deploy/backup.sh`, cohérence des 10 départements /
  255 outils et `git diff --check` réussissent.

Les commandes ciblées reproductibles incluent :

```sh
python -m pytest departments/m05-financecore/tests/test_cout_reel_tarifs_historiques.py
python -m pytest departments/m06-material-control/tests/test_livre_prix_unite_confirmee.py
python -m pytest tests/test_stockage.py tests/test_approbations_journal.py
python -m pytest departments/m01-front-office/tests/test_stt_frontiere_locale.py
python -m pytest tests/test_deploy_backup_retention.py
cd mobile
NODE_OPTIONS=--experimental-sqlite node node_modules/jest/bin/jest.js --runInBand --runTestsByPath src/outbox/destinationDurable.test.ts src/outbox/proprietaire.test.ts
```

Les tests PostgreSQL standard utilisent Docker. La validation locale a remplacé uniquement la création
éphémère du conteneur par des bases temporaires sur un cluster PostgreSQL utilisateur privé,
accessible exclusivement par socket Unix ; SQL et décisions réels conservés. Le cluster et les bases
créés pour cette validation sont connus arrêtés/supprimés, sans intervention sur un service tiers.

## Dépendances et incident de fixture CI

Les mises à jour exactes sont documentées dans [INGREDIENTS](../research/INGREDIENTS.md#correctifs-ciblés-de-sécurité-du-21-octobre-2026).
Le graphe Core ne change que huit versions liées aux correctifs ; l'audit des dépendances de production
passe de huit avis à zéro. Python ne change que Pillow, certifi et setuptools ; les onze avis distincts
signalés sur leurs anciennes versions ne sont plus signalés sur les nouvelles. Roues, intégrités et
licences vérifiées ; aucun script d'installation tiers implicite, aucun renouvellement global.
Le contrôle de parsing Markdown sur 200 009 octets est observé à environ 2 092 ms avant et 110 ms après,
avec sortie conservée ; observation locale unique, pas un engagement de performance.

Le rouge M7 de la CI précédente vient d'une fixture qui contrôlait seulement deux dates SQL sur quatre.
Le test est reproduit rouge puis corrigé en fixant toutes les dates de sa chronologie fictive ;
aucun algorithme de marge ou ROI n'a été modifié pour le faire réussir.

## Limites conservées

Les tests ne prouvent pas un téléphone natif, l'acceptation par une Gateway réelle, le service STT
externe réel, une sauvegarde Docker de production, ni le renderer OCR Linux x86_64 depuis cet hôte ARM.
L'identité mobile est l'URL exacte, sans rapprochement d'alias ni identifiant immuable du serveur.
Les entrées historiques de prix sans unité restent partielles. Le terme coût historique valorise
au tarif éligible, sans certifier le coût d'acquisition du lot réellement consommé.
L'export ingestion-PDF conserve sa divergence NumPy préexistante pour éviter une mise à jour adjacente.
Les 16 UNKNOWN historiques et les interruptions 291/430/433 restent conservés séparément.

Ces corrections locales ne constituent pas un audit exhaustif ni une certification globale du produit.
La CI applicable au nouveau commit doit être évaluée séparément. Aucune fusion, modification de
protection, action de production ou dépense réelle n'est effectuée par ces corrections.

## Suivi de la première CI des corrections

La CI 39569713415 de `da774d08` a révélé une fixture incomplète dans la verticale durable :
trois saisies de prix n'indiquaient pas leur unité. M5 refusait donc correctement de produire
une marge complète. La reproduction locale échoue avant ajout explicite de `unite="pi"` ;
les trois variantes de marge, le rollback et la reprise de deux affaires passent ensuite
(5 tests). Les assertions et le calcul financier restent identiques. Root a aussi exécuté
le propriétaire complet de qualification Core→HTTP : une affaire SQLite fictive,
40 phases de profil, mémoire, isolation et restauration, sans échec ni skip.

Les six diagnostics TypeScript M9 déjà connus sont reproduits puis corrigés par un retour
explicite sur le chemin terminal et une capture locale du membre unique du lot. Identité
du message et du reçu, ordinal zéro, consommation unique et absence de suspension avant
copie restent contrôlés. Les trois étapes TYPES PROD (Core, UI, extensions) passent, et
Root vérifie indépendamment le typage Core et les 31 régressions des deux suites M9.
Le nouveau lot creux de test est fictif : le producteur réel fournit un tableau dense gelé ;
ce test ne prouve pas un nouveau défaut runtime atteignable. Le lint ciblé conserve un
diagnostic préexistant `prefer-promise-reject-errors` ; aucune règle ni identité de rejet
n'est modifiée pour le masquer. Le format des trois fichiers passe.

Les mesures de la CI montrent un appel de mutation M3 de 1 540,40 secondes, sur
1 758,27 secondes de pytest dans le lot concerné. Ce script exécute quinze suites internes
(référence, douze mutants, deux redondances). Une optimisation conditionnelle est étudiée,
sans suppression de garde ni gain de durée revendiqué avant mesure. La série d'audit
ordinale reste close ; les intentions historiques inconnues ne sont pas rejouées.
