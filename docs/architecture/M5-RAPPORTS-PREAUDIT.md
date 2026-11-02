# M5 FinanceCore : rapports financiers en brouillon, budget déclaré et pré-audit déterministe (M5-RAPPORTS-1, M5-PRE-AUDIT)

Branche `claude/m5-rapports-preaudit`, base `ea631e4bc` (registre MCP révision 22, tête alembic 0086). Source d'exigences : l'analyse
d'écart des anciens prompts de Nathan (`docs/reprise/PROMPTS-NATHAN-ANCIENS/ANALYSE-M5.md`, lignes R8, R10, P5 et backlog
M5-RAPPORTS-1 / M5-PRE-AUDIT). **Aucune migration** : le seul registre nouveau (`budgets_declares`) est une chaîne de hachage
append-only sur `stockage.maillons`, comme le grand livre et les plans de facturation (portable SQLite / PostgreSQL, aucune garde
« SQLite seulement »).

Tout ce document est **préparatoire** : À valider auprès d'un comptable (CPA) / professionnel qualifié. **Aucun CPA n'a validé
quoi que ce soit ici.**

## Règle d'or

Aucun chiffre ne vient d'un modèle ni d'un calcul de tête ; rien ne se corrige, rien ne se clôt, rien ne s'écrit.

- Les rapports sont tirés du **grand livre en partie double** (écritures DÉFINITIVES seulement, comme la balance de vérification),
  additionnées en `Decimal` exact. Le seul arrondi existant est le pourcentage (deux décimales, ROUND_HALF_UP) et il est dit.
  Un brouillon n'est **jamais** additionné : il est compté à part (`completude.brouillons_non_comptabilises`) et le rapport le dit.
- Chaque rapport porte `statut: BROUILLON` et la mention « Brouillon préparatoire — à valider auprès d'un comptable (CPA) », en plus
  des deux mentions habituelles de M5. **Aucune clôture de période, aucune écriture finale, aucun état « officiel ».**
- Une donnée que seule la direction connaît (budget, comptes de coûts directs, seuils du pré-audit) est **déclarée** par elle. Absente,
  la ligne du rapport (ou la règle) est « non calculable / non évaluée » et **dit ce qu'il faut déclarer** ; jamais zéro, jamais une
  valeur par défaut. Le fail-closed est prouvé par un test pour chacune.
- Un compte du grand livre que le plan courant ne connaît pas fait **refuser** le rapport (`REJ-RAPPORT-COMPTE-HORS-PLAN`) : le
  classer au hasard serait faux. Un registre altéré (grand livre, budget) le fait refuser aussi.
- Chaque rapport **cite ses sources** : les registres qu'il a lus, avec leur taille et la **tête de leur chaîne** (`sources`, aussi dans
  les entrées du reçu). Une écriture de plus change la tête citée, donc l'empreinte du reçu : le reçu dit sur QUELLES données il porte.
- Chaque rapport rend un **reçu rejouable** (`recu-calcul.v1`, le même format que le moteur de calcul) : entrées normalisées (les
  mouvements par compte), empreintes, résultat. `m5_rejouer_rapport_financier` vérifie les empreintes puis REFAIT le calcul depuis
  les entrées. Un reçu compact (sans entrées, quand elles dépassent le budget d'une réponse) reste vérifiable ; il se rejoue en
  rappelant l'outil sur les mêmes registres (même empreinte).

## Ce qui est livré

| Outil | Niveau | Geste |
|---|---|---|
| `m5_etat_des_resultats` | T0 | Produits, charges, résultat **avant impôts** (le plan ne porte aucun compte d'impôt sur le résultat) d'une période. Marge brute seulement si `configuration.rapports.comptes_couts_directs` est déclarée |
| `m5_bilan_brouillon` | T0 | Actif, passif, capitaux propres à une date, **résultat cumulé non clos** (le grand livre n'a aucune écriture de clôture d'exercice) et la preuve actif = passif + capitaux + résultat (sinon `equilibre: false` et l'écart est nommé) |
| `m5_etablir_budget` | T1 / **N3 humain** | Déclare le budget : lignes `{compte de produits ou de charges, mois AAAA-MM, montant au cent}`. Une version complète remplace la précédente (motif obligatoire, le passé reste lisible) ; le même contenu ne crée rien |
| `m5_lire_budget` | T0 | Le budget actif, ses versions, ses lignes (paginées) |
| `m5_budget_contre_reel` | T0 | Budget déclaré contre réel, mois par mois et compte par compte (écart, favorable / défavorable). Sans budget : `REJ-BUDGET-A-DECLARER` |
| `m5_rentabilite_par_axe` | T0 | Marge réelle regroupée par **service** ou par **ville** (voir plus bas) |
| `m5_rapport_mensuel_direction` | T0 | Six sections (résultats et variation, bilan, budget, rentabilité par service, par ville, pré-audit), chacune avec FAITS, HYPOTHÈSES, DONNÉES MANQUANTES et le reçu de son rapport |
| `m5_controler_preaudit` | T0 | Le contrôleur déterministe : dix règles, une liste de constats (règle, gravité, raison, sources, action proposée **jamais exécutée**) |
| `m5_constater_preaudit` | T1 / **N2** | Publie au bus `m5.preaudit_constate` (les seuls comptes) pour M8 ; déclenché par le planificateur durable |
| `m5_rejouer_rapport_financier` | T0 | Vérifie et rejoue un reçu de rapport ou de contrôle |

Portée d'appareil **fermée** pour les dix (aucun rôle d'appareil, refusé dans le code). Aucun module nouveau ne nomme le registre des
mouvements : la garde AST `conformite.verifier_aucun_decaissement` les couvre en mode strict.

Modules : `rapports_financiers.py`, `budgets.py`, `controleur_preaudit.py`, `constat_preaudit.py` (purs : aucun import `opsys`, aucune
horloge, aucune entrée-sortie, aucun flottant — vérifié par un test sur l'AST), `verdicts_rapports.py` (catalogue fermé de refus,
à part de `validation.py`, épinglé par empreinte pour la paie), `outils_rapports.py` (adaptateur : lit les registres, normalise,
appelle les noyaux purs).

## Le budget : déclaré, jamais supposé

Les réglages de direction (CFG-1) ne portent que des valeurs scalaires ; un budget est une table (compte × mois). Il vit donc dans
son propre registre append-only `budgets_declares`, comme les plans de facturation : une version complète par déclaration, hachée,
avec la personne qui l'a approuvée (N3, propriétaire ou finance) et le motif. Un compte inconnu, désactivé ou de bilan, un mois
illisible, un montant négatif / à plus de deux décimales / démesuré, un couple compte-mois en double : refus nommé, rien d'écrit.
Une chaîne altérée à la main bloque toute lecture et toute écriture.

## La rentabilité par service et par ville

**Ce qui existe dans les sources.** `m4.travaux_termines` porte `ville` et `service` (un lead v1 porte `type_travaux` à la place : le catalogue interdit de déduire l'un de l'autre, M5 ne garde donc que `service`) ; M5
recevait l'événement mais **ne gardait pas** ces deux champs. `wct_recus.construire` les garde désormais, **tels quels** (texte,
80 caractères au plus, absents s'ils sont absents : un ancien maillon se lit « dimension inconnue »). Le grand livre ne porte aucune
dimension : la rentabilité par axe n'est **pas** une marge comptable, c'est la rentabilité par chantier de M5 (matériaux de M6,
main-d'œuvre de M4) regroupée.

**Ce qui est regroupé.** La dernière rentabilité tracée par chantier (jamais une trace de la voie console), à **coût complet** et à
**prix définitif** (tous les jalons émis). Un coût partiel ou un prix provisoire est **exclu et compté** (`exclus_cout_partiel`,
`exclus_prix_provisoire`) ; un chantier sans la dimension est compté à part (`sans_dimension`). La dimension absente de tous les
chantiers, ou aucun chantier à coût complet : `NON_CALCULABLE`, « manque X », jamais un zéro ni une ville devinée. La valeur est
regroupée telle qu'écrite (« Lévis » et « levis » sont deux groupes : M5 ne normalise pas une ville).

**Ce qui reste vrai en production.** Le coût complet certifié M4→M5 n'est pas routé (décision 2 de l'analyse) : tant qu'il ne l'est
pas, les chantiers sont à coût partiel et la rentabilité par axe dit « non calculable ». Le module est correct ; sa valeur réelle
dépend de ce routage et de la déclaration du taux horaire. « Équipe » n'est pas livré (aucune dimension d'équipe dans les sources).

## Le pré-audit : dix règles, un contrôleur, rien d'exécuté

Contrôleur pur (`controleur_preaudit.controler`) sur un dossier normalisé que l'adaptateur lit des registres existants : grand livre,
factures clientes, comptes à payer, opérations comptables (pièces liées, dépenses d'employés, notes de crédit), numérotation, taux
fiscaux versionnés (via `grand_livre.rapprocher`). Lecture seule. Chaque constat : `cle` stable (hachage de la règle et des sources),
`regle`, `gravite`, `raison`, `sources` (registre et identifiant opaque), `action_proposee`, `outil_suggere` (un outil EXISTANT du sas,
jamais appelé), `action_executee: false`.

| Règle | Gravité | Voit | Seuil déclaré ? |
|---|---|---|---|
| `FACTURE_SANS_PAIEMENT` | moyenne | facture ENVOYÉE dont l'échéance PROPRE est strictement dépassée ; sans échéance lisible : règle PARTIELLE, dite | non |
| `PAIEMENT_SANS_FACTURE` | haute | encaissement des comptes clients (ou règlement des comptes fournisseurs) sans facture payée / vivante derrière | non |
| `DEPENSE_SANS_RECU` | moyenne | facture fournisseur, dépense d'employé ou écriture de charge saisie à la main sans pièce justificative liée | non |
| `TAXE_INCOHERENTE` | haute | TPS/TVQ (à percevoir et sur intrants) du grand livre contre le moteur fiscal versionné ; **aucun taux écrit ici** | non |
| `DOUBLON_PROBABLE` | haute | même fournisseur, même montant avant taxes, dates proches ; écritures manuelles identiques le même jour | `m5.jours_fenetre_doublon` (sans elle : PARTIELLE, même jour seulement) |
| `TRANSACTION_HORS_NORME` | faible | pièce dont le montant atteint le seuil (« à confirmer », pas une erreur) | `m5.seuil_transaction_hors_norme_cad` (sans lui : NON ÉVALUÉE) |
| `FACTURE_MODIFIEE` | haute | facture corrigée ou annulée dont l'écriture ne correspond plus à la pièce courante (non contre-passée) | non |
| `CHANGEMENT_COMPTE_INHABITUEL` | moyenne | un fournisseur dont les n dernières factures allaient au même compte de charge change de compte | `m5.historique_changement_compte` (sans lui : NON ÉVALUÉE) |
| `PISTE_AUDIT_INCOMPLETE` | haute | chaîne d'un registre qui ne se rejoue pas, anomalie du grand livre, numéro de facture manquant ou en double | non |
| `DOCUMENT_MANQUANT` | moyenne | facture émise / payée ou facture fournisseur sans écriture (ni brouillon), écriture dont la pièce vérifiée est introuvable, pièce illisible | non |

**Fail-closed.** Une règle dont le seuil déclaré est absent est `NON_EVALUEE` : son compte vaut `null` (jamais zéro), elle dit quoi
déclarer (réglage et clé). Un grand livre altéré rend non évaluées les règles qui en dépendent (`PAIEMENT_SANS_FACTURE`,
`TAXE_INCOHERENTE`, `TRANSACTION_HORS_NORME`, `FACTURE_MODIFIEE`, `DOCUMENT_MANQUANT`) et la chaîne devient un constat
`PISTE_AUDIT_INCOMPLETE` : jamais « aucun constat ». Les trois seuils se déclarent par l'écran « Réglages de direction » (bloc
`reglages:` du manifeste, adoption N3 par le propriétaire, retour arrière en un geste) ou, à défaut, par `configuration.preaudit` ; **aucune
valeur n'est proposée ni écrite au manifeste livré** (`configuration: {preaudit: {}}`).

**Interprétations écrites (à valider par le CPA).** « Changement de compte inhabituel » vise le compte de **charge** d'un fournisseur ;
le changement de coordonnées **bancaires** d'un fournisseur n'est pas évaluable (M5 n'en garde aucune). Un constat est une question
posée à une personne, pas un verdict de fraude ni d'erreur. Une facture fournisseur annulée dont l'écriture n'est pas contre-passée
sort deux constats (`FACTURE_MODIFIEE` et `TAXE_INCOHERENTE`, ses taxes sur intrants n'ayant plus de facture vivante) ; la contre-passation
validée les lève (un écart de taxe à net nul est filtré : `grand_livre.rapprocher` le range parmi ses écarts avec 0,00 $, le contrôle ne
le répète pas).

## Le constat planifié vers M8

Sur le modèle de la vague 7 (`M5-CASH-LIBRE-PLANIFIE.md`, `M2-VICTOR.md`) :

- **Déclaration** : bloc `constats_planifies` du manifeste de M5 (`preaudit`, outil `m5_constater_preaudit`, mesure
  `m8_constats_preaudit`, appels `aujourd_hui` = jour local du créneau, `horodatage` = instant du créneau). Exécuteur
  `m5.constat.preaudit`, famille « constats », **N2, inactif par défaut**, cadence dérivée du catalogue de M8 (fenêtre 86 400 s / 2
  passages = 12 h, jamais recopiée).
- **Ombre** : le journal dit « aurait » et rien n'est calculé ni publié.
- **Idempotence par créneau** : l'instant du constat entre dans l'identifiant de l'événement (`m5-preaudit-<jour>-<version>-<marque
  de l'instant>`) ; deux déclenchements du même créneau, un même horodatage rejoué : un seul événement. Un retour à une version
  antérieure des données (A, B, A) publie un événement distinct (l'instant les sépare).
- **L'événement** `m5.preaudit_constate` (catalogue fermé, `additionalProperties: false`, toutes propriétés requises) ne porte que des
  **comptes** : par règle (`null` si non évaluée), total (`null` si aucune règle évaluée), par gravité, noms des règles non évaluées
  et partielles. Aucune facture, aucun fournisseur, aucun client, aucune écriture, aucun montant, aucune raison en texte.
- **Les cinq garanties** (livré, idempotent par clé de contenu, panne puis reprise, charge hors catalogue refusée, rien de personnel)
  sont rejouées pour cet événement dans `tests/test_entrepot_m8_garanties.py` (source `preaudit`, 5 tests de plus).
- **Catalogue M8 : 58 → 59 mesures**, extension additive : `m8_constats_preaudit` (domaine finance, `moins_est_mieux`, agrégat,
  fenêtre 24 h). Une règle non évaluée ou partielle rend la **couverture partielle** (« 7 règles sur 10 »), aucune règle évaluée la
  rend non calculable. Le fait est rangé tel quel (`operations_recues`, type `preaudit_constate`, clé de contenu
  `date_reference, version_donnees, constate_le`, le plus récent publié fait foi).

## Preuves

{{PREUVES}}

## Limites (sans euphémisme)

- **Aucune validation d'un CPA.** Le plan comptable, les regroupements, les libellés, l'interprétation des dix règles et la structure
  des états sont un point de départ. Rien ici n'est un état financier officiel ni un avis comptable ou fiscal.
- **SQLite seulement.** Le registre `budgets_declares` n'emploie que des primitives déjà qualifiées pour PostgreSQL, mais rien n'a
  tourné dessus : aucune épreuve PostgreSQL pour ce chantier.
- Les états sont tirés du grand livre **tel qu'il est tenu** : tant que les brouillons ne sont pas validés (N4) et que le cycle
  comptable n'est pas passé, les chiffres sont incomplets (le rapport le dit, il ne le répare pas). Le grand livre n'est pas un
  logiciel comptable certifié ; QuickBooks reste le livre officiel tant que Nathan n'en décide pas autrement (question 1 de l'analyse).
- **Pas de flux de trésorerie, pas d'amortissement, pas de provisions, pas d'impôt sur le résultat, pas de clôture d'exercice.** Le
  bilan montre le résultat cumulé depuis le début du registre ; l'exercice fiscal n'est pas modélisé (`mois_fin_exercice` n'est pas lu).
- **Le budget est une déclaration** : sa pertinence n'est pas jugée. Aucun budget n'existe tant que Nathan n'en déclare un.
- **La rentabilité par service / ville dépend du routage du coût complet** (M4→M5, décision 2) ; sans lui elle dit « non calculable ».
  Aucune dimension d'équipe. Les chantiers reçus avant ce chantier n'ont pas gardé `ville` ni `service`.
- Le pré-audit ne voit que ce que M5 garde : pas de coordonnées bancaires de fournisseur, pas de relevé bancaire importé hors des
  rapprochements préparés, pas de risque Loi 25, pas d'« auditeur » des autres agents. Un constat n'est pas résolu par le contrôleur ;
  la résolution passe par les outils du sas.
- Le constat planifié est **inactif par défaut** ; il n'a jamais tourné sur la boucle réelle du serveur pendant des jours (horloge
  injectée seulement). Comme pour le cash libre, M8 date le constat du début du jour UTC : la fraîcheur du soir suit la même limite.
- Aucun rendu PDF (non demandé) ; aucune sortie vers QuickBooks, courriel, ni envoi.

## Activation (propriétaire)

1. Déclarer le budget (m5_etablir_budget, N3) et, avec le CPA, la liste des comptes de coûts directs (`configuration.rapports`).
2. Adopter, depuis « Réglages de direction », les trois seuils du pré-audit (rien n'est proposé : ce sont des décisions).
3. Console Connecteurs : passer `m5.constat.preaudit` en `ombre`, lire le journal « aurait », puis `actif`.
4. Faire passer le cycle comptable (`m5_executer_cycle_comptable`) et valider les brouillons : sans écritures, les états sont vides et le
   pré-audit signale des documents manquants.
