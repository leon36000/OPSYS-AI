# R16 — Recherche de briques et consolidation du 30 septembre 2026

La réutilisation est le premier chemin à examiner. Cette passe prolonge les recherches R1–R15
de Claude, confronte les prompts retransmis au code actuel et recherche GitHub **et** GitLab.
Les sources sont fixées à des commits, avec licences, interfaces, activité et limites d'adaptation.
Les métadonnées ou README servent à orienter la lecture ; étoiles et promesses commerciales ne
prouvent pas maturité, qualité, économie ou performance.

| Volet | Rapport | Conclusion principale |
|---|---|---|
| Core, Hermes, agents, tokens et installation | [recherche-core](recherche-core.md), [Hermes détaillé](hermes-notes.md) | Garder le fork, réutiliser des propriétaires existants ; admission fournisseur avant appel et profils spécialisés |
| M1 Front Office | [recherche-m1](recherche-m1.md) | Réutiliser intake/transports puis choisir un runtime vocal, phases progressives et transferts fiables |
| M5 FinanceCore/CFO | [recherche-m5](recherche-m5.md) | Corriger la facture, compléter comptabilité/banque/obligations puis analyses CFO profondes |
| M7 Marketing/CMO | [recherche-m7](recherche-m7.md) | Usine/export existants, données réelles Google/analytics/CRM/M5 avant services sociaux supplémentaires |
| M10 Mémoire | [recherche-m10](recherche-m10.md) | Réparer les frontières, préserver les registres, isoler développement/métier, graphe relationnel et évaluations |
| Autres départements et GitLab | [recherche-transversale](recherche-transversale.md) | Librairies de contraintes/analyse/simulation et patrons inventaire ; aucune deuxième vérité métier |

## Écart décision/code confirmé lors de la consolidation

ADR-0008 prévoit les providers natifs et LiteLLM optionnel. Le code actuel
`src/opsys/openclaw.py::generer` (défaut `http://litellm:4000/v1`) et `fournisseur_departement`
(config `OPSYS_CLE_Mn`) conservent la gateway. `install/install.sh` demande une passerelle locale
sans l'installer. Les mentions « natif par défaut » dans les rapports décrivent donc la **cible**,
pas un parcours d'installation déjà autonome. Correction suivie dans le lot 1C du plan.

## Première sélection, avec un besoin précis

| Brique | Capacité recherchée | Mode recommandé et limite |
|---|---|---|
| OpenClaw existant | Runtime, canaux, mémoire, UI, outils | Fork OPSYS maintenu ; veille/correctifs ciblés, pas remplacement ni synchro automatique |
| Hermes Agent (MIT) | Contrats mémoire/context engine, skills, compaction, sous-agents | Reprise de composants après comparaison ; ces interfaces existaient déjà au SHA de recherche de Claude |
| Agent Skills, LangMem, QMD | Procédures sélectionnées, mémoire procédurale, recherche docs | Bancs ciblés ; pas permissions déduites du texte ni modèle lourd installé par défaut |
| lossless-claw (MIT) | Compaction avec références conservées | Adaptation au propriétaire contexte OPSYS ; conflit du slot unique à résoudre |
| Pipecat (BSD-2) ou LiveKit Agents (Apache-2) | Pipeline vocal et interruption | Choisir un moteur sur sandbox ; modèles LiveKit et dépendances TTS ont d'autres licences |
| faster-whisper (MIT), Tesseract (Apache-2), Docling (MIT) | STT, documents/OCR/tableaux | Modèles/poids et dépendances vérifiés séparément ; CPU/RAM/latence évalués sur VPS cible |
| Python Accounting (MIT), Ledger (BSD-3) | Partie double/invariants ou oracle comptable | Essai sur transaction/session OPSYS ; aucun second grand livre indépendant |
| Stripe/Plaid SDK, OAuth Intuit et APIs officielles | Paiements/lecture banque/sync préparée | Signature, idempotence, scopes et write humain ; pas dépendance aux credentials pour les moteurs internes |
| Postiz (AGPL), Matomo (GPL), SerpBear (MIT) | Social/analytics/positions | Services optionnels selon licence, API et coût ; ne pas transformer simulation en intégration prouvée |
| OR-Tools, InvenTree, DuckDB, NetworkX, SimPy | Cédule, patrons stock, analyse, relations, scénarios | Bibliothèques ou extraction licenciée étroite ; adaptation justifiée par parcours |

Les pépites moins connues sont évaluées sur le même critère que les projets connus. Hindsight
mérite un banc mémoire temporel isolé ; il n'est pas le canon métier. Bifrost reste une gateway
optionnelle et ne prouve pas à lui seul un plafond dur concurrent. TensorZero est archivé au
moment de la recherche. Cognee/Graphiti nécessitent une qualification de backend/licence réelle,
pas l'hypothèse d'un graphe PostgreSQL universel.

## Corrections importantes aux catalogues anciens

- Piper maintenu : GPL-3, ancien dépôt MIT archivé ; isoler service, vérifier licences des voix.
- Kokoro : licence des poids distincte de celle du pipeline français utilisant eSpeak/GPL.
- LiveKit Agents Apache-2 n'autorise pas de réutiliser tous les modèles propriétaires ailleurs.
- SDK Meta et LinkedIn : conditions spécifiques, pas adoption/fork permissif automatique.
- Chatwoot : cœur MIT et répertoires Enterprise sous licence distincte.
- Scrapy : BSD-3, pas Apache ; Ledger : BSD-3, pas GPL.
- NumPy Financial actuel : minimum Python 3.13 ; OPSYS annonce 3.11, donc tag/adaptation à choisir.
- Google Business Messages retiré ; ne pas bâtir un connecteur à l'ancienne API.
- Demandes d'avis Google : ne pas sélectionner uniquement les clients satisfaits.

## Preuves, portée et rétention

[SOURCES.json](SOURCES.json) rassemble les observations par dépôt/volet ; des miroirs ou renommages
peuvent désigner un même projet. Chaque registre spécialisé conserve plus de détails. Le fichier
[IMPORT-SOURCES.json](IMPORT-SOURCES.json) conserve l'empreinte des rapports et métadonnées originaux.
Les liens vers le code OPSYS sont relatifs ; les sources tierces sont des URLs fixées à des commits.

Cette copie contient des **rapports et métadonnées**, pas les codebases candidats, modèles ou leurs
dépendances. Les téléchargements complets et reproductions originales restent dans l'archive de
travail `/workspace/restructuration-opsys-2026-09-30` et `/workspace/audit-opsys-2026-09-30`.
Les références `archive:…` dans les rapports identifient les éléments non recopiés. L'index
[PREUVES-SHA256](audit/PREUVES-SHA256.json) permet de contrôler les preuves d'audit sauvegardées ;
la conservation hors workspace et l'ingestion M10 ne sont pas revendiquées par cette copie.

L'audit au commit `2e56c0d` conserve ses [47 constats](audit/CONSTATS-RECENTS.json) et ses
[résultats datés](audit/VERIFICATION-AUDIT.json). Les nombres de tests cités dans les rapports sont
les preuves de cet audit, sauf mention explicite d'une nouvelle commande. Aucun nouveau service,
benchmark fournisseur, connecteur production ou migration n'a été exécuté dans cette recherche.

Plan applicable : [RESTRUCTURATION](../../programme/RESTRUCTURATION-2026-09-30.md).
Bilan et vérifications du lot : [BILAN](../../programme/BILAN-RESTRUCTURATION-2026-09-30.md).
Le choix des briques ne remplace pas les preuves d'intégration et n'allège pas les approbations métier.
