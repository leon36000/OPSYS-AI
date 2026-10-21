# Audit M5 — FinanceCore

> Audit historique du 28 septembre 2026, conservé pour traçabilité. Les évolutions ultérieures
> ne sont pas inventoriées ici. Consulter le [plan de consolidation](../programme/RESTRUCTURATION-2026-09-30.md)
> et les [recherches actuelles](../research/R16-2026-09-30/README.md) pour M1/M5/M7/M10. Un statut
> ancien et un nombre de tests ne certifient pas le périmètre cible complet.


Audit statique, sans modification de code. Périmètre : `departments/m05-financecore/`. Sources
faisant foi : `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, §7/M5, §8, §9, §10, §13),
`AGENTS.md`, `docs/architecture/{ARCHITECTURE,DEPARTEMENTS,MOBILE}.md`, `docs/research/{R8-m5-m6,
INGREDIENTS}.md`, `docs/programme/PLAN.md`, le code et les tests réels de M4/M5/M6 et de
`src/opsys/`. Date : 2026-09-28.

## Résumé exécutif

- Le socle livré (7 stories BMAD, `docs/bmad/02-PRD-PM.md`) est étroit et solide : registre
  financier **plat** append-only (`MouvementFinancier`), solde/argent disponible distincts, taux
  TPS/TVQ versionnés et sourcés, registre d'approbation F0-F7 à statut par relecture, état
  financier filtré par rôle (fail-closed), conformité statique AST. **1 728 lignes de code métier
  (12 modules), 2 522 lignes de tests (169 fonctions), tous verts** (voir PREUVE).
- Ce socle **n'est pas** une reconstruction du code Forge (~14 249 lignes, ~238 routes `/compta`,
  §7/§11 de la définition produit) : ce code est inaccessible, mis de côté. M5 a été **rebâti à
  neuf** sur un PRD propre. Il n'y a donc rien de Forge à porter — voir §2b.
- Toute l'extension « CFO IA » (plan comptable, facturation, AR/AP, paie, calendrier fiscal vivant,
  prévisions, conseillers, tableau de bord) reste **à construire** : le socle actuel est un
  registre de gouvernance, pas encore un système comptable.
- Aucun écran mobile propre à M5 n'existe ; l'app mobile phase 1 (`MOBILE.md`) est l'app OpenClaw
  officielle générique — écart notable avec la richesse attendue en §9.
- `docs/programme/PLAN.md` (rédigé le même jour) demande déjà exactement la tranche verticale visée
  par cette mission (T1 : `job.completed` → facture brouillon M5.2 → approbations N3-N4). Le plan
  de phases ci-dessous s'aligne dessus plutôt que d'inventer un autre séquencement.

## 1. Inventaire M5.1–M5.20

Statuts établis par lecture directe + `pytest departments/m05-financecore/tests -q
--import-mode=importlib -p no:cacheprovider` (169 tests, tous verts, voir PREUVE).

| # | Fonction | Statut | Fichiers | Tests |
|---|---|---|---|---|
| M5.1 | Grand livre, plan comptable, écritures, verrouillage période, piste d'audit | **PARTIEL** | `contrats.py`, `registre.py`, `encodage.py`, `validation.py` | `test_registre.py`(20), `test_encodage.py`(6), `test_contrats.py`(2), `test_validation.py`(29) — registre append-only présent ; plan comptable multi-niveaux, partie double, verrouillage de période **ABSENTS** (choix v1 documenté, PRD §0/§7.2 : « v1 reste PLAT ») |
| M5.2 | Facturation, AR (âge, relances), AP (OCR factures fournisseurs, doublons) | **ABSENT** | — | seul pont existant : `departments/m06-material-control/tests/test_frontiere_finance_m5.py` (conversion Decimal M6→M5), qui prouve un format compatible, pas un flux de facturation ou d'AP |
| M5.3 | Rapprochement bancaire (Plaid, CSV, Stripe, QBO), score de confiance | **ABSENT** | — | — |
| M5.4 | Paie, retenues, cotisations, DAS, CNESST, T4/RL-1/RE préparatoires | **ABSENT** | — | `contracts/taux_fiscaux.v1.yaml` ne porte que TPS/TVQ, aucune table RRQ/AE/RQAP/impôt/CNESST |
| M5.5 | Calendrier fiscal vivant, TPS/TVQ, acomptes provisionnels, échéances | **PARTIEL** | `taux_fiscaux.py`, `taxes.py`, `contracts/taux_fiscaux.v1.yaml` | `test_taux_fiscaux.py`(14), `test_taxes.py`(8) — calcul TPS/TVQ versionné+sourcé présent ; échéancier et acomptes **ABSENTS** |
| M5.6 | Dossier CPA et fin d'année | **ABSENT** | — | — |
| M5.7 | Prévision de trésorerie 5 ans, scénarios, stress | **ABSENT** | — | reporté explicitement par le PRD (R-009 : historique insuffisant), décision à respecter |
| M5.8 | Projection carnet signé / probable | **ABSENT** | — | — |
| M5.9 | Rentabilité par chantier, service, ville, équipe | **ABSENT** | — | aucun lien `chantier_id`/`devis_id` ↔ mouvement dans le contrat actuel |
| M5.10–12 | Conseillers achats majeurs (camion, équipement, bâtiment) | **ABSENT** | — | — |
| M5.13 | Conseiller dette, financement, investissement | **ABSENT** | — | — |
| M5.14 | Stratégie d'épargne et réserves | **PARTIEL** | `soldes.py` (mécanisme `PROVISION` brut) | `test_soldes.py`(11) — soustraction des provisions du solde présente ; aucune cible ni catégorie de réserve, aucune « stratégie » |
| M5.15 | Conseiller fiscal et comptable stratégique | **ABSENT** | — | hors périmètre déterministe par choix explicite du PRD (agent RAG fiscal) |
| M5.16 | Moteur de décision CFO (25 sections) | **ABSENT (par conception)** | — | tranché PRD §0 : livrable M9, qui consommera `EtatFinancier` — ne pas dupliquer dans M5 |
| M5.17 | Garde de risque financier et pré-audit | **PARTIEL** | `conformite.py` (763 lignes) | `test_conformite.py`(19) — contrôle statique de **qualité de code** présent (taux codé en dur, import de domaine, déterminisme, anti-cause R-020) ; contrôle de risque **opérationnel** (anomalies sur mouvements réels, fraude, doublons) **ABSENT** |
| M5.18 | Base de connaissances fiscale et comptable (RAG sourcé) | **ABSENT** | — | — |
| M5.19 | Tableau de bord CFO | **ABSENT** | — | `src/opsys/console/pages.py` ne contient aucune page M5 |
| M5.20 | Intégration mémoire M10 | **PARTIEL** | `department.yaml` (`memoire: lecture/ecriture` déclarées) | aucun appel réel ; M10 lui-même `STUB` (définition produit §11) ; DA-M5-04 interdit tout import `mX_*`, donc le câblage devra passer par la couche agent/MCP, jamais le paquet Python |

**Transversal**

| Élément | Statut | Détail |
|---|---|---|
| Registre F0-F7 + preuve structurée F6/F7 | **PRÉSENT** | `approbation.py`(163 l.) ; `test_approbation.py`(28) |
| État financier filtré par rôle (fail-closed) | **PRÉSENT** | `etat_financier.py`(35 l.) ; `test_etat_financier.py`(13) |
| Taxes TPS/TVQ versionnées | **PRÉSENT** | `taux_fiscaux.py`, `taxes.py` ; `test_taux_fiscaux.py`(14), `test_taxes.py`(8) |
| Outils d'agent (5, T0×2/T1×1/T3×2) + 2 skills | **PRÉSENT** | `outils.py`(274 l.) ; `test_outils_agent.py`(15) ; `skills/tenir-le-registre-financier`, `skills/gerer-les-approbations-f0-f7` |
| Sentinelle structure + BMAD + cohérence | **PRÉSENT** | `test_module_structure.py`(4) |
| Conformité Loi 25 (classe de rétention) | **PARTIEL** | `ClasseRetention` (`FISCALE_6_ANS`/`STANDARD`) déclarée dans le contrat ; **aucune politique de purge/rétention** dans `docs/compliance/politiques/` (4 politiques listées, aucune financière) |
| Multi-entités | **ABSENT** | aucun concept d'entité légale/tenant dans le modèle |
| Adaptateurs QuickBooks/CCube/Stripe/Plaid | **ABSENT** | `pyproject.toml` : zéro dépendance finance (seulement PyYAML, mcp, + optionnels postgres/fastapi/pytest/ruff) |
| Import CSV bancaire | **ABSENT** | — |

## 2. Écarts

### a) Modèle de données

Le contrat `MouvementFinancier` (`montant, type_mouvement, horodatage, classe_retention, source`)
est un **journal de caisse plat** volontaire (PRD §0), pas un système comptable. Face à la liste
demandée par la mission :

| Entité demandée | État |
|---|---|
| Plan comptable (comptes, catégories) | ABSENT |
| Écriture de partie double (débit/crédit liés) | ABSENT — un mouvement porte un seul montant signé |
| Période comptable + verrouillage | ABSENT |
| Facture client (lignes, statut, échéance) | ABSENT |
| Paiement client (lié à une facture) | ABSENT |
| Compte à recevoir (âge, relance) | ABSENT |
| Compte à payer (lié PO/facture fournisseur M6) | ABSENT — `SignalPoAPayer` de M6 existe, rien côté M5 ne le reçoit en production |
| Dépense (catégorie, employé, reçu photo) | ABSENT |
| Taxes (TPS/TVQ) | PRÉSENT (taux + calcul) ; ABSENT : aucune écriture de taxe liée automatiquement à une facture |
| Paie brouillon | ABSENT |
| Réserves | PARTIEL — type `PROVISION` générique, sans cible ni catégorie |
| Prévisions | ABSENT |

Conséquence : toute construction M5.2+ doit **étendre en couches par-dessus** le registre existant
(nouveaux contrats, nouveaux registres dédiés sur le patron déjà réutilisé deux fois —
mouvements/approbations) sans toucher aux 18 critères déjà prouvés (P5, « ne pas reconstruire »).

### b) API et compatibilité `/compta`

Le point 7 de la mission est confirmé par grep exhaustif : **aucune trace** du code Forge
(`/compta`, ~238 routes) nulle part dans ce dépôt, hors la mention historique en §7/§11 de la
définition produit. Il n'y a donc **rien à porter** au sens strict — la matière source a disparu
avec les anciens dépôts Forge. « Documenter la compatibilité `/compta` » ne peut aujourd'hui
signifier que : concevoir une **API neuve**, gelée dans `contracts/`, cohérente avec
`MouvementFinancier`/`EtatFinancier` déjà stables, nommée clairement comme nouvelle (ex. `/api/m5/`)
et non comme une reconstitution. Statut réel de l'API M5 : **ABSENT** côté HTTP/REST (aucune route,
`src/opsys/console/` n'a aucune page M5) ; la seule forme d'accès qui existe est le protocole **MCP**
via `src/opsys/serveur_mcp.py`, qui expose déjà les 5 outils agent — donc un agent LLM peut
consommer M5 aujourd'hui, mais ni le dashboard web ni l'app mobile ne le peuvent directement.

### c) Événements

- **`job.completed` / WCT (M4)** — le déclencheur existe et est testé côté M4
  (`m4_field_ops/outbox.py`, story S008), et `CONSOMMATEURS_CIBLES` nomme explicitement `"M5"`.
  Mais `CHAMPS_WCT` ne porte **aucun montant** — seulement `devis_id`. Produire une facture
  brouillon exige donc d'aller chercher le prix chez M3 par `devis_id`, et **aucun consommateur
  côté M5 n'existe** pour ce WCT (zéro mention de M5 dans le code M4 hors la liste de
  consommateurs). Statut : **ABSENT**.
- **Coût réel depuis M6** — le pont technique existe et est **prouvé** par
  `test_frontiere_finance_m5.py` : un `SignalPoAPayer` réel, converti (`Decimal(str(x))`, jamais
  `Decimal(float)`), est accepté par le vrai `validation.valider_mouvement` de M5. Mais c'est un
  **test de frontière**, pas un **orchestrateur en production** : aucun outil agent de M5 n'appelle
  cette conversion pour créer effectivement un `DECAISSEMENT` à partir d'un signal M6. Statut :
  **PARTIEL** (frontière prouvée, câblage absent).

### d) Outils d'agent

5 outils présents et testés : `m5_etat_tresorerie` (T0), `m5_calculer_taxes_tps_tvq` (T0),
`m5_enregistrer_mouvement` (T3), `m5_creer_demande_approbation` (T1), `m5_decider_approbation`
(T3). Manquants pour couvrir M5.2+ : aucun outil de facture brouillon, aucun outil d'âge de
créances, aucun outil de paie, aucun outil de rapprochement. Le socle « mouvement + taxe +
approbation » est couvert ; tout le reste ne l'est pas.

### e) Écrans mobiles par profil (§9)

Attendu (§7/M5 + §9.3/9.5/9.6) : **Admin** — factures à approuver, paiements reçus, retards,
dépenses à valider, trésorerie, anomalies. **Employé** — photo de reçu, confirmation de fin de
travaux, **jamais d'écriture finale**. **Vendeur** — marge estimée de la soumission, statut de
paiement, relance autorisée. **Client** — facture, lien de paiement, reçu, historique,
**jamais de marge ni de coût interne**.

État réel : **aucun de ces écrans n'existe**. `docs/architecture/MOBILE.md` acte une phase 1 qui
réutilise l'app OpenClaw officielle générique (chat, approbations natives non spécialisées) ; les
écrans par profil sont phase 2, non commencée. C'est un écart de **direction produit**, pas
seulement d'implémentation : MOBILE.md phase 1 est structurellement plus modeste que ce que §9
décrit, et le point ouvert §13.9 (stack et portage de l'app) n'est toujours pas tranché — à signaler
à Nathan avant de construire le premier écran M5. Le filtrage fail-closed déjà prouvé de
`etat_financier.py` (CA-M5-12, binaire, jamais de fuite partielle) est le bon patron mécanique à
réutiliser pour garantir « jamais de marge visible au client » **avant** d'écrire cet écran.

### f) Tableau de bord CFO (M5.19)

**ABSENT.** Aucune page dans `src/opsys/console/pages.py`. Aucun KPI CFO exposé (cash libre réel,
âge des AR, prochaines échéances fiscales) hors des champs bruts de `EtatFinancier`.

### g) Portes et replis (gates)

| Porte | Repli attendu (§10) | État du repli |
|---|---|---|
| OAuth QuickBooks | Lecture seule, essai à blanc, export CSV | **rien n'existe**, ni l'adaptateur ni le repli |
| CCube | Adaptateur essai à blanc, import CSV | **rien n'existe** ; aucun SDK identifié (logiciel propriétaire QC de niche) |
| Stripe, Plaid | Bac à sable, import CSV bancaire | **rien n'existe** |
| Paie, impôts, remises, déclarations | Jamais automatique | respecté **par absence** (rien à automatiser par erreur), mais non testé faute de code |
| Validation CPA (F7) | Mention professionnelle obligatoire | mécanisme présent et testé (`_preuve_structure_verifiable`) mais **jamais exercé** par un flux métier réel |

Conclusion : les portes ne sont pas contournées, mais aucune n'a de repli **fonctionnel livré** —
le bon statut aujourd'hui est ABSENT pur pour ces intégrations, pas encore « PARTIEL — GATE
NATHAN ».

### h) E2E exigés

Sur la liste « Preuve de complétion (CFO IA) » de la définition produit, seul un point est
vérifiable aujourd'hui : **« toute action critique bloquée sans validation »** (F6/F7 + T3 sur
`enregistrer_mouvement`/`decider_approbation`, testés). Paie brouillon, calendrier fiscal vivant,
réserves/cash libre réel élargi, prévisions, simulations d'achats, rapport de décision CFO,
tableau de bord CFO, mémoire M10, sources fiscales citées : **tous ABSENTS**. Le seul test
inter-départements existant (`test_frontiere_finance_m5.py`) est un test d'intégration de
frontière (format de données), pas un E2E métier « chantier → facture → paiement ».

## 3. Briques

Candidats vérifiés (licence lue directement, `docs/research/R8-m5-m6.md` daté d'aujourd'hui +
vérifications complémentaires de cette mission pour l'OCR de factures et Stripe, absentes de R8).

**Grand livre / plan comptable (roadmap, pas la priorité immédiate)**

| Brique | Licence | Verdict |
|---|---|---|
| [python-accounting](https://github.com/ekmungai/python-accounting) (MIT, 211⭐, push 2026-08-28) | MIT | RÉFÉRENCE pour une future story « vrai grand livre » cadrée en BMAD — ne pas introduire en filigrane d'une autre tâche |
| [Beancount](https://github.com/beancount/beancount) + [Fava](https://github.com/beancount/fava) | GPL-2.0 / MIT | SIDECAR non modifié, export d'audit CPA en lecture seule uniquement ; jamais `import beancount` |
| ERPNext, Odoo Accounting | GPL-3.0 / Enterprise propriétaire | EXCLUS (cf. R8 §1) |

**OCR de factures fournisseurs (M5.2/AP) — non couvert par R8, vérifié dans cette mission**

| Brique | Licence (vérifiée aujourd'hui) | Verdict |
|---|---|---|
| [docTR](https://github.com/mindee/doctr) (Mindee) | **Apache-2.0** (`LICENSE` brut) — actif (commits à J-3/J-5, release v1.1.0 fin août 2026) | RETENU en premier : éditeur spécialisé justement dans l'extraction de documents/factures, PyTorch, sidecar Python, pas de GPU obligatoire à un volume PME |
| [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) (Baidu) | **Apache-2.0** (`LICENSE` brut) — très actif (PaddleOCR-VL 3.0, 2025-2026) | ALTERNATIVE seulement si docTR est insuffisant sur un type de facture précis ; dépendance lourde au framework PaddlePaddle (empreinte GPU/VPS plus élevée) |

Aucune des deux ne fait l'extraction de champs structurés (fournisseur, montant, taxes, date) pour
une facture QC : prévoir un post-traitement dédié. Le montant extrait par OCR reste une
**proposition** à valider humainement avant toute écriture (cohérent avec T3 déjà posé sur
`m5_enregistrer_mouvement` — le LLM ne calcule jamais un montant final).

**Rapprochement bancaire / agrégation** (déjà couvert R8, retenu tel quel)

| Brique | Licence | Verdict |
|---|---|---|
| Parseur OFX/CSV maison (~100-150 lignes stdlib) | — (code interne) | RETENU en premier : aucune dépendance, aucun compte développeur, disponible dès la phase 2 (cash libre réel) — **jamais** `ofxtools` importé directement (GPL-3.0) |
| [plaid-python](https://github.com/plaid/plaid-python) (officiel) | MIT | RETENU en second temps ; couverture Canada vérifiée (Big Six + Desjardins + Tangerine + Simplii + coopératives) ; nécessite OAuth bancaire, donc une porte Nathan |
| Flinks | Propriétaire/commercial | OPTION si Plaid insuffisant sur une caisse précise ; coût à négocier |

**QuickBooks Online / Xero**

| Brique | Licence | Verdict |
|---|---|---|
| [python-quickbooks](https://github.com/routablehq/python-quickbooks), [xero-python](https://github.com/XeroAPI/xero-python) (officiel) | MIT | RETENUS pour la synchronisation batch, lecture seule d'abord (progression déjà actée par le PRD) |
| [quickbooks-online-mcp-server](https://github.com/intuit/quickbooks-online-mcp-server) (Intuit officiel) | Apache-2.0 | OPTION mode agentique, seulement après le flux dry-run→write prouvé côté client pip |
| CCube | — | aucun SDK identifié (logiciel propriétaire QC de niche) ; à rechercher séparément le jour où la porte Nathan s'ouvre |

**Stripe** (non couvert par R8, vérifié dans cette mission)

| Brique | Licence | Verdict |
|---|---|---|
| [stripe-python](https://github.com/stripe/stripe-python) (officiel) | MIT (vérifié `LICENSE` brut) | RETENU pour encaissement/paiement en ligne, lecture seule/bac à sable d'abord (webhook signé, idempotence — cohérent P8) |

**Paie QC/Canada (M5.4) — le plus gros vide, aucune brique de calcul à adopter**

Recherche croisée du jour : aucune bibliothèque open source mature ne couvre RRQ/AE/RQAP/impôt
QC+fédéral combinés ; seuls des calculateurs web (CRA, QuickBooks) et une bibliothèque commerciale
fermée (Canadian Payroll Tax Library, Middle Earth Technologies) existent. Sources officielles à
verser en YAML versionné (patron exact de `taux_fiscaux.v1.yaml`) le jour où la story est cadrée :
- ARC — **T4032QC**, « Tables de retenues sur la paie — Québec », en vigueur le 1ᵉʳ janvier 2026.
- Revenu Québec — **TP-1015.TI**, « Table des retenues à la source d'impôt du Québec », version
  2026-01 ; **TP-1015.G**, « Guide de l'employeur », version 2026-01.
- CNESST — taux de cotisation par unité de classification, publiés annuellement (à sourcer au
  moment de la construction ; aucun taux n'est copié dans ce document sans année+source+version).

Verdict : construire un module interne `paie.py` sur le patron `taux_fiscaux.py` (déclaration
versionnée, blocage nommé si tranche absente), jamais une formule codée en dur. L'achat d'un
service de paie canadien commercial reste une option à trancher par Nathan si le calcul maison est
jugé trop risqué avant un premier client SaaS — décision hors périmètre technique.

**Prévision de trésorerie (M5.7)** — [statsforecast](https://github.com/Nixtla/statsforecast)
(Apache-2.0) retenu comme moteur, **bloqué** tant que R-009 (historique insuffisant) n'est pas
levé par une décision produit explicite — ne pas contourner.

## 4. Plan par phases

Aligné sur `docs/programme/PLAN.md` (T1), pas un nouveau séquencement. Chaque tâche est une story
BMAD potentielle : petite, testée, sur le patron des 7 stories déjà livrées.

**Phase 1 — Tranche verticale « travaux terminés → facture brouillon → validation humaine → AR →
rentabilité de chantier »** (= T1 du programme)

1. `FactureBrouillonV1` : contrat gelé additif (`chantier_id`/`devis_id`, `client_id`, `lignes`,
   `montant_avant_taxes`, taxes via `m5_calculer_taxes_tps_tvq`, `statut`
   BROUILLON|ENVOYEE|PAYEE|ANNULEE) dans un nouveau `facturation.py` — ne modifie pas les contrats
   existants (P5).
2. `creer_facture_brouillon(...)` : fonction pure, écrit sur un **troisième registre dédié**
   (patron `registre.py` déjà réutilisé deux fois) ; jamais un `ENCAISSEMENT` tant que non payée —
   test explicite de ce piège.
3. Outil agent `m5_creer_facture_brouillon` (T1, écriture interne non finale) + skill dédiée.
4. `calculer_age_creances(registre_factures, aujourd_hui)` : fonction pure, `aujourd_hui` fourni
   par l'appelant (M5 n'a pas d'horloge, DA-M5-06), tranches 0-30/31-60/61-90/90+, fail-closed si
   horodatage absent.
5. Consommateur du WCT M4 : **hors** paquet `m5_financecore` (couche agent/orchestration, jamais un
   import `mX_*`, DA-M5-04) — sur `job.completed`, va chercher le prix par `devis_id` (M3), appelle
   `m5_creer_facture_brouillon`. Test d'intégration sur le patron déjà prouvé par
   `test_frontiere_finance_m5.py`.
6. Câbler explicitement `auto_send_invoice_max_amount = 0` (§7/M5) : aucun envoi réel sans passage
   par une demande d'approbation au palier F4 (« envoi client », échelle F0-F7 déjà écrite).
7. Rentabilité de chantier minimale : rapproche `montant_facture` (M5) et coût réel reçu de M6 par
   `chantier_id`/`devis_id` ; `donnee_manquante` explicite si un des deux côtés manque — jamais une
   marge partielle présentée comme complète.
8. E2E : chantier terminé normal → facture brouillon → approbation → AR ; chantier avec écart
   matériaux → `completed_pending_review` → pas de facture avant résolution (§6/§9.7).
9. Écran mobile minimal admin (liste des factures brouillon à approuver), sur le patron des
   approbations natives déjà disponibles via l'app OpenClaw phase 1 — pas un nouvel écran forgé
   tout de suite.

**Phase 2 — Cash libre réel et calendrier fiscal (M5.5, M5.14)**

1. `calendrier_fiscal.v1.yaml` (patron `taux_fiscaux.v1.yaml`) : échéances TPS/TVQ et acomptes,
   sourcées Revenu Québec/ARC, versionnées par année.
2. `prochaines_echeances(date_reference)` : fail-closed si l'année n'est pas déclarée.
3. Cash libre réel élargi : `argent_disponible` moins DAS/paies dues moins comptes à payer connus
   (aujourd'hui : seulement moins `PROVISION`) — nouveau calcul composé dans `soldes.py`, tests de
   non-régression obligatoires sur CA-M5-05/06 existants.
4. Cible de réserve par catégorie de `PROVISION`, fournie par l'appelant (dashboard) — jamais un
   pourcentage inventé par le système.

**Phase 3 — Paie brouillon (M5.4)**

1. `paie.v1.yaml` (patron `taux_fiscaux.v1.yaml`) : RRQ/AE/RQAP/impôt QC+fédéral par tranche,
   sourcés T4032QC et TP-1015.TI/TP-1015.G version 2026-01 exacte.
2. `calculer_paie_brouillon(employe, heures, taux)` : fonction pure, retenues détaillées, **jamais**
   un `DECAISSEMENT` direct — un brouillon est T1, la paie reste « jamais automatique » (§10).
3. E2E : paie brouillon → approbation Nathan (F6, argent réel) → mouvement.

**Au-delà (GATED, hors périmètre immédiat)** : rapprochement bancaire réel (Plaid/OFX),
QuickBooks/Xero en écriture, prévision 13 semaines–24 mois (après levée de R-009), conseillers
achats majeurs (M5.10-13), tableau de bord CFO complet, RAG fiscal M5.18, OCR factures fournisseurs
en production.

## 5. Risques et points ouverts

- **Conseil réglementé.** Aucune sortie M5 ne doit se présenter comme un avis fiscal/comptable
  officiel. La mention obligatoire retenue par §13.3 (« Analyse préparatoire IA — validation
  Nathan/CPA/fiscaliste requise avant toute décision officielle ou action réelle. ») **n'est codée
  nulle part** aujourd'hui. Dès que M5.15/M5.16 existeront, cette mention doit être un test
  automatisé (présence obligatoire dans toute sortie de type analyse/recommandation), pas une
  convention documentaire.
- **F5-F7 jamais automatiques.** Aucun palier F0-F7 n'atteint `APPROUVE` sans `approbateur` nommé
  (CA-M5-10, testé) ; F6/F7 exigent en plus une preuve structurée (CA-M5-09). Point à surveiller :
  la définition produit range F5 (« modification comptable finale ») visuellement à côté de F6/F7
  dans sa prose, mais le PRD M5 a explicitement tranché (§0) que seule la preuve F6/F7 est
  renforcée — F5 se contente d'un nom d'approbateur, comme F0-F4. Décision déjà documentée et
  justifiée, pas un oubli, mais à confirmer avec Nathan avant la première écriture comptable
  finale réelle. Par ailleurs, le mécanisme n'existe qu'à l'intérieur de `m5_financecore` : rien
  n'empêche aujourd'hui un appelant qui importerait directement `Registre` d'écrire hors de
  `approbation.approuver()` — limite déjà documentée honnêtement (DA-M5-01). À durcir (garde AST
  de point d'écriture unique) dès qu'un service HTTP externe pourra atteindre ce paquet.
- **Trois échelles d'autonomie non reliées explicitement.** N0-N5 (définition produit, §5/P1),
  T0-T3 (core `opsys`, générique, tous départements, `src/opsys/politiques.py`) et F0-F7 (M5,
  métier) coexistent sans document de correspondance. En pratique
  `m5_enregistrer_mouvement`=T3 (toujours approuvé au niveau core) **et** porte en plus un palier
  F0-F7 choisi par l'appelant au niveau métier — cohérent, mais jamais expliqué comme une relation
  à deux couches. À documenter avant qu'une revue ou un audit externe (AGENTS.md : M5 revu par un
  autre fournisseur de modèle) ne s'y perde.
- **Portée SaaS de M5** (point ouvert §13.8, repris comme décision attendue de Nathan dans
  `docs/programme/PLAN.md`) toujours tranchée nulle part. Sans décision, impossible de savoir si
  M5.10-13 (conseillers achats majeurs, dette) seront un jour livrés à un client SaaS ou réservés
  au propriétaire — le code actuel ne distingue aucune notion d'instance/tenant (multi-entités
  confirmé ABSENT en §1).
- **Rétention Loi 25 vs 6 ans fiscal.** `ClasseRetention` existe dans le contrat mais aucune
  politique de purge n'est écrite dans `docs/compliance/politiques/` — à faire avant tout
  déploiement avec données réelles de clients.
- **Dette du modèle plat.** Chaque entité ajoutée par-dessus le registre actuel (facture, paie)
  accroît l'écart avec un vrai plan comptable. Si `python-accounting` est un jour activé, prévoir
  une migration explicite des registres existants, jamais une réécriture silencieuse (cohérent
  avec l'append-only déjà en place).
- **État connu à corriger.** `DEFINITION-PRODUIT.md` §7/§11 classe encore M5 `FAIT_VÉRIFIÉ` (base)
  en citant ~14 249 lignes/~238 routes `/compta` — un système qui n'existe plus dans ce dépôt.
  Recommandation pour un humain (hors périmètre de cet audit, qui ne modifie que ce fichier) :
  corriger ce statut vers l'état réel (socle v1 partiel, 1 728 lignes de code métier).

---

## PREUVE

Commande exécutée : `/opt/opsys-venv/bin/python -m pytest departments/m05-financecore/tests -q
--import-mode=importlib -p no:cacheprovider` → 169 tests collectés, **tous verts** (aucun échec,
aucune erreur). Comptage indépendant par lecture : `grep -rc "^def test_"
departments/m05-financecore/tests/*.py` = 169, cohérent avec le résultat d'exécution.

Lectures : `docs/produit/DEFINITION-PRODUIT.md` (intégral), `AGENTS.md`, `docs/architecture/
{ARCHITECTURE,DEPARTEMENTS,MOBILE}.md`, `docs/programme/PLAN.md`, `docs/decisions/` (listing +
ADR-0008), `docs/compliance/politiques/` (listing complet), `docs/research/{R8-m5-m6,
INGREDIENTS}.md` ; département M5 intégral (`department.yaml`, `README.md`, `SOUL.md`,
`docs/bmad/{01,02,03}`, `contracts/taux_fiscaux.v1.yaml`, les 12 fichiers `src/` et 12 fichiers
`tests/`) ; M3 comme référence vivante (`department.yaml`, `DEPARTEMENTS.md`) ; M4
(`outbox.py`, `etats.py`, `contrats.py`, absence de mention M5 hors liste de consommateurs) ; M6
(`contrats_sortie.py`, `materiel.py`, `test_frontiere_finance_m5.py`) ; socle `src/opsys/
{outils.py, approbations.py, politiques.py, console/}` ; `pyproject.toml`.

Recherche web (2026-09-28), licences lues sur fichier `LICENSE` brut : docTR (mindee/doctr,
Apache-2.0), PaddleOCR (PaddlePaddle/PaddleOCR, Apache-2.0), stripe-python (MIT). Sources
fiscales officielles confirmées par lecture directe : ARC T4032QC (en vigueur 2026-01-01), Revenu
Québec TP-1015.TI et TP-1015.G (version 2026-01). Recherche croisée confirmant l'absence de
bibliothèque de paie QC/Canada open source mature.

Non exécuté, hors permission de cette mission : `opsys-metier verifier`, `ruff check`, toute invocation
`pytest` autre que celle explicitement autorisée ci-dessus.
