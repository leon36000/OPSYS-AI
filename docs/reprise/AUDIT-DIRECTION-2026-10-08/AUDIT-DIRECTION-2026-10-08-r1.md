# Audit de direction et corrections — 8 octobre 2026

Daté Toronto : 2026-10-08T19:53:47.800419-04:00. Parent exact `20731e1bf679b2cd2adbd7467da0a7686d619ed1`. OPSYS-AI reste **PARTIEL**.

Le transfert léger et son historique sont conservés. La CI du parent a réellement fermé les six workflows :
39 jobs, 37 réussites et deux skips Docker opt-in. Le runner avait 4 925 tests/211 suites ; la nouvelle qualification locale compte 4 934 tests/212 suites.
Le défaut de sélection du test photo sur le parent reste déclaré ; aucun vert historique n'est réétiqueté.

## Résultat concret

Deux alertes prix M6 omises exactement au seuil de 20 % sont corrigées par une comparaison décimale exacte,
avec les types et la projection float historiques conservés. Le modèle monétaire M6 entier n'est pas migré.
La trésorerie personnelle ferme désormais son cache après un refus connu ; panne réseau, lecture tardive et
purge échouée sont qualifiées dans le processus courant. La reprise après échec de purge reste une limite.

Le garde CI appelle les cinq workflows applicables dans la même exécution et le même commit. Il exige les
quatre groupes Python, la sélection et chaque appel attendu. Un appel non applicable doit être skipped ;
un appel applicable doit réussir. Le push privé porte le nom `gates-push`, la PR/main `gates` : leurs diffs
deux/trois points ne sont pas prétendus identiques. Aucune protection live n'a été changée.

Le test photo est ajouté à la sélection Core de 199 fichiers. L'oracle météo suit les créneaux effectivement proposés,
avec 39 tests DP verts ; il ne garantit pas une revalidation automatique de l'aperçu avant application.

## Qualification et conservation

Local : 4 934 tests mobile/212 suites, TypeScript strict vert, 1 371 tests M6 et 39 tests météo,
72 tests du sélecteur, 81 tests de configuration CI, 34 tests photo Core, Ruff global vert et 227 outils/135 portées appareil.
Les rouges de défaut et de harnais restent distincts. Les comptes ciblés se recouvrent avec leurs suites,
donc aucun total artificiel n'est produit. Nouveau commit exact/CI : **en attente de publication et de runner**.

La capsule `PREUVES-AUDIT-DIRECTION-2026-10-08-r1.tar.xz` contient 295 fichiers, SHA256 `ba7fd90da3f79ea1aed628ec64621de7b432340ed5cee081c01b33a344bca7a7`.
Le registre rapproche les 18 sources avec leurs préimages et dispositions. Le manifeste photo corrigé r2
conserve le r1 fautif en auto-empreinte ; les cinq autres membres et le reçu de test étaient conformes.
Le libellé Toronto du reçu CI historique est corrigé par addendum, sans modifier son instant ni ses résultats.

## Revue contradictoire

Claude Code 2.1.295 est connecté ; modèle réel Opus 5.5 qualifié. Trois missions indépendantes ont utilisé
des copies en lecture seule, la première avec deux sous-agents. Les recommandations restent des hypothèses jusqu'à
leur confrontation : rollback canonique sur 49 tables confirmé ; rollback global des refus métier écarté car
il annulerait le nettoyage CAS et l'audit GPS voulus ; le texte M5 legacy ne remplace pas `decide_par`.
La réponse sans `deviceId` est un 403 terminé, et non une requête pendante. Les assurances N5, téléphone,
chiffrement OS et isolation mémoire restent au niveau effectivement prouvé.

| Constat | Disposition | Critère ou limite restant |
| --- | --- | --- |
| OPSYS-CI-02 | Correction locale qualifiée | CI du nouveau commit exact et nom `gates` à vérifier sur le runner. |
| OPSYS-TX-01 | Rollback des appelants canoniques confirmé | Fabriques personnalisées, liaison API et fautes PostgreSQL restent à qualifier. |
| OPSYS-TX-02 | Correction globale proposée écartée | Préserver les traces de refus et nettoyages voulus ; aucun writer réel involontaire démontré. |
| OPSYS-N5-01 | Attestation humaine déclarée | Professionnel et pièce justificative non vérifiés indépendamment ; assurance officielle non livrée. |
| OPSYS-M6-01 | Seuil de prix corrigé localement | Migration monétaire complète M6 distincte ; nouvelle CI attendue. |
| OPSYS-TST-01 | Oracle météo corrigé | 39 tests DP verts ; qualification PyVRP du runner distincte. |
| OPSYS-CI-01 | Test photo sélectionné | 199 fichiers ciblés ; exécution photo par le nouveau runner attendue. |
| OPSYS-CI-03 | Risque de couverture de contrat | Qualification producteur/SDK et filtres croisés restent une exigence distincte. |
| OPSYS-CI-04 | Raisons des skips ajoutées aux prochains logs | Les 17 raisons historiques absentes ne sont pas reconstruites. |
| OPSYS-MOB-01 | Choix OS existant confirmé | Protection du téléphone et du stockage non qualifiée par Jest. |
| OPSYS-M10-01 | Critère de séparation encore partiel | Frontière OS/stockage/permissions affaires-développement à démontrer. |
| OPSYS-CORE-02 | Risque conditionnel de configuration | TLS/topologie réelle à qualifier ; aucun SSRF public démontré. |
| OPSYS-CORE-01 | Limite de débit/latence connue | Aucun défaut de performance mesuré ; jusqu’à 161 revalidations, délai borné. |
| OPSYS-CORE-03 | Requête pendante réfutée | 403 terminé et zéro appel upstream observés ; aucun correctif nécessaire. |
| OPSYS-M5-01 | Texte legacy sans autorité | Signataire autoritaire dans le socle ; futur affichage officiel doit joindre la bonne approbation. |
| OPSYS-ID-01 | Convention v1 confirmée | Version canonique, multiples sites et compatibilité restent des critères ; aucun renommage global. |
| OPSYS-EVD-01 | Origine du compteur prouvée ; libellé rectifié | 4925/211 réellement sur runner ; instant Toronto corrigé par addendum conservant l’original. |
| ROOT-MOB-02 | Cache trésorerie fermé après refus | Purge échouée fermée dans le processus courant ; redémarrage/téléphone restent à qualifier. |
| ROOT-M4-02 | Aperçu météo uniquement | Revalidation du nouvel aperçu avant appliquer_cedule N3 non démontrée. |
| ROOT-EVD-02 | Manifeste photo rectifié | Auto-empreinte r1 incorrecte conservée ; manifeste r2 et cinq autres fichiers conformes. |

## Orchestration et suite

ROOT reste intégrateur et propriétaire Git/PR. Les trois agents Codex ont des fichiers disjoints ;
Claude reçoit des missions bornées sur snapshot et son avis est vérifié. Aucune route LiteLLM locale n'est
qualifiée ; l'absence PATH/env ne prouve rien sur PC1. Aucun secret ou endpoint n'est présumé.
Les modèles, outils, durées, contrôles et références sont conservés sans exporter les transcripts privés.

Après fermeture de cette CI exacte, reprendre T4.27-b : première classification humaine liée à sa source,
sans mutation stock/coût/statut M4. La file garde M7 → M1 → M2 → M3 → M4/M6 → M5 → M8/M9/M10 et ses critères profonds,
identifiants communs v1, Core OpenClaw, quatre profils/hors ligne, dashboard, avatars et mémoires séparées.
Les 104 preuves exclues du pack léger, le supplément complet et les conversations absentes restent inconnus.
Aucune fusion, force-push, publication publique, action client/paiement ou promesse d'exécution permanente.

Origines conservées : `../TRANSFERT-INFRA-2026-10-05/REGISTRE-REPRISE-INFRA-2026-10-06.json` et
`../PREUVES-PERTES-M6-2026-10-08/REGISTRE-PREUVES-PERTES-M6-2026-10-08-r2.json`.
