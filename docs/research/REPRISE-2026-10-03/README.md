# Reprise du 3 octobre — index des preuves

Travail local en cours dans `OPSYS-AI-recent`. Cet index situe les qualifications
par surface; leurs nombres ne sont pas additionnés, car plusieurs campagnes se
recouvrent. Le code en cours d'intégration n'est pas une preuve d'exécution.
OPSYS-AI et ses départements restent partiels.

| Surface | Dernière qualification dans cette portée | Limites |
|---|---|---|
| M5, déclarations et rapprochement humain | [93 cas et Ruff](preuves/m5-rapprochement/VERIFICATION-ROOT.json), huit fichiers de tests complets | SQLite et données fictives; deux parcours HTTP réels. Cash CFO privé seulement, aucun paiement ou calcul de paie nette. |
| M7, saisie humaine Growth privée | [120 cas et Ruff](preuves/m7-growth-humain/VERIFICATION-ROOT.json), cinq fichiers complets | SQLite, HTTP/session/CSRF et concurrence réels; observations fictives, source non vérifiée, aucun calcul de croissance/ROI. |
| M7, programme CMO humain durable | [181 cas](preuves/m7-cmo-session-r2/VERIFICATION-ROOT.json), huit fichiers de tests complets et Ruff sur cinq fichiers modifiés | SQLite/HTTP et données Synergy fictives; versions, approbations, revue. Session/autorité revalidées en fin d’opération; sources déclarées, aucune autonomie CMO complète ou performance externe. |
| Intention cron et retrait terminal Python | [185 cas et Ruff](preuves/cron-retrait-python/VERIFICATION-ROOT.json), migration `0023` comprise | La preuve de suppression native reçue par Python est simulée dans cette campagne. |
| Client privé Core | [30 cas](preuves/cron-retrait-core/client-cleanup-r4-root-r2/VERIFICATION-ROOT.json) | Huit opérations, retrait compris; réseau doublé. |
| Convergence hôte Core | [52 cas](preuves/cron-retrait-core/gateway-cleanup-r4/VERIFICATION-ROOT.json) | Validateur, reconciler et superviseur, retrait compris; propriétaires natifs doublés. |
| Sauvegardes et secrets Core | [10 cas](preuves/cron-retrait-core/backup-secret-cleanup-r4/VERIFICATION-ROOT.json) | Table des reçus de retrait exclue de la sauvegarde Git; aucune qualification du DELETE natif. |
| Budget avant dispatch | [18 cas Core + refus de namespace privé](preuves/provider-pre-dispatch/core/VERIFICATION-ROOT.json); [110 cas Python SQLite](preuves/provider-pre-dispatch/python/JUNIT-ADDENDUM-ROOT.json) | Campagnes distinctes; cinq tests PostgreSQL exclus explicitement, compagnon Core/Python HTTP non qualifié. Aucun fournisseur réel ou stream SDK complet. |
| M1, port privé d’import des appels manqués | [205 cas, Ruff et manifestes](preuves/m1-appels-hote-durable-r2/VERIFICATION-ROOT.json), neuf fichiers complets | SQLite, appels fictifs, client MCP HTTP ASGI et régressions HTTP natives. Provenance/rejeu/rollback vérifiés; transport Core, signature fournisseur et téléphone réel non qualifiés. |
| M1, raccord Core appels manqués | [164 tests natifs](preuves/m1-core-appels-hote/VERIFICATION-ROOT.json), sept fichiers complets, format et règles de frontière | Vrai HMAC Twilio local sur clé fictive; manager/port M1 doublés. Build/exports/profilage, recovery Gateway et téléphonie réelle non qualifiés; transport interprocessus qualifié séparément ci-dessous. |
| M1, transport Core→Python HTTP | [2 scénarios natifs complets](preuves/m1-core-python-http/VERIFICATION-ROOT.json), format/lint/règles de frontière/Ruff | Vrai client MCP et vraie CLI Python, SQLite isolée; import/rejeu/retrait de profil. Fournisseur et portée hôte synthétiques; pas de Gateway complet, de build ou de téléphone réel. Régression M9 arrêtée au plancher mémoire, zéro cas qualifié. |
| M10, indexation de procédures par lot | [14 cas PostgreSQL réels](/workspace/poursuite-opsys-2026-10-02-r1/M10-INDEXATION-LOT-ROOT-r1/execution-pg-r6/VERIFICATION-ROOT.json) | Cinq versions par action, procédures internes M03 et corpus synthétique. Aucune assimilation générale d'entreprise. |

La description métier et les limites se trouvent dans le
[rapport M5 privé](../../grs/compta/M5-RAPPROCHEMENT-CFO-PRIVE-2026-10-03.md), le
[contrat opérateur cron](../../architecture/AGENTS-CRON-OPERATEUR.md), le
[raccordement hôte](../../architecture/CRON-RACCORDEMENT-HOTE-2026-10-03.md) et le
[rapport Fusion/M10](../../grs/memory/M10-FUSION-REPRISE-2026-10-03.md).

Le [contrat M1](../../grs/reception/M1-APPELS-HOTE-2026-10-03.md) distingue le port
Python qualifié du raccord Core intégré et testé sur sources. Le parcours
interprocessus est désormais qualifié séparément; le build reste non qualifié. Le namespace `voice-call:`
est réservé à l’hôte; les imports manuels historiques ne deviennent pas des preuves
de livraison fournisseur.

## Parcours Core encore non qualifiés

Les parcours CronService/SQLite, CAS natif, cycle de vie hôte et stream SDK ont des
tests écrits. Les dernières tentatives n'ont pas produit de qualification complète :
plancher mémoire insuffisant, limite du tas V8 ou arrêt par garde de RSS/réserve.
La réserve de 512 MiB est conservée. Ces arrêts ne sont ni des tests réussis ni la
preuve d'un défaut fonctionnel dans le produit. Les journaux et reçus RED restent
dans les archives [diagnostiques r1](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/diagnostics-native-2026-10-03-r1/ETAT-ROOT.json)
et [r2](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/diagnostics-native-2026-10-03-r2/ETAT-ROOT.json).
Le [diagnostic r3](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/diagnostics-native-2026-10-03-r3/ETAT-ROOT.json)
conserve aussi les essais avec le pool de threads officiel des agents sous Linux;
les arrêts de réserve/plancher n'y qualifient aucun cas.

Le retrait terminal Python et le reçu chiffré natif r4 sont intégrés localement. Le
pré-DELETE et l’ACK ont été déplacés dans les workers existants après les revues r2/r3.
Les 185 cas Python utilisent une preuve native simulée; les 52 cas de convergence
doublent les propriétaires natifs. Les onze cas de retrait SQLite écrits n’ont pas
démarré : [reçu de plancher mémoire](/workspace/poursuite-opsys-2026-10-02-r1/CRON-HOTE-PRIVE-ROOT-r1/retrait-core-r4/qualification-root-r1/retirement-cleanup-r4/VERIFICATION-ROOT.json).
Le format passe sur 44 chemins. Le statut complet de ces limites figure dans le
[raccordement hôte](../../architecture/CRON-RACCORDEMENT-HOTE-2026-10-03.md).
Aucun fournisseur réel, job de production, dépense ou déploiement VPS n’a été déclenché.

## Recherche de composants

La [comparaison M3 GitHub/GitLab](M3-BRIQUES-GITHUB-GITLAB-2026-10-03.md) couvre
vision, photogrammétrie, nuages de points et SIG. Elle ne prouve aucune précision
terrain ni adoption d'une nouvelle dépendance. La
[comparaison M1 GitHub/GitLab](M1-BRIQUES-GITHUB-GITLAB-2026-10-03.md) recommande
un adaptateur de transport vers les propriétaires message et voicemail existants,
puis un pilote Pipecat. LiveKit SIP et Asterisk répondent à des besoins distincts.
Les [pins primaires](preuves/m1-recherche/source-pins.json) conservent versions,
commits et recherche GitLab; aucun miroir GitLab n'est retenu comme upstream.

La [comparaison M10 GitHub/GitLab](M10-BRIQUES-GITHUB-GITLAB-2026-10-03.md) retient
les propriétaires PostgreSQL/pgvector et la provenance existants. Docling reste un
candidat futur pour OCR; aucun nouveau framework n’est installé. Le prochain palier
proposé est un intake de un à cinq TXT/MD internes, avant toute ingestion massive. Le [candidat r4](../../grs/memory/M10-FUSION-REPRISE-2026-10-03.md) est revu, mais n’est ni appliqué ni qualifié PostgreSQL.

La [gapmap M7 courante](../../grs/marketing/M7-GAPMAP-REPRISE-2026-10-03.md)
situe les onze fonctions marketing et les propriétaires déjà livrés. Elle retient
une tranche de saisie humaine Growth privée, désormais
[intégrée et qualifiée localement](../../grs/marketing/M7-GROWTH-SAISIE-HUMAINE-2026-10-03.md).
La gapmap reste une photographie avant cette tranche.

## État documentaire

Les passages actifs de l'audit CFO et des contrats cron ont été corrigés pour
décrire le cash privé et le raccordement écrit, tout en conservant les preuves et
limites historiques. [Contrôle documentaire ROOT](/workspace/poursuite-opsys-2026-10-02-r1/DOCS-OBSOLESCENCE-ROOT-r1/VERIFICATION-ROOT.json) :
trois documents, 66 liens locaux vérifiés, aucun lien manquant. Ce contrôle n'est
pas une qualification logicielle supplémentaire.

Le [programme CMO durable](../../grs/marketing/M7-CMO-PROGRAMME-DURABLE-2026-10-03.md) et le [contrat de budget avant dispatch](../../architecture/AGENTS-BUDGET-AVANT-DISPATCH-2026-10-03.md) décrivent les dernières tranches locales et leurs limites.
