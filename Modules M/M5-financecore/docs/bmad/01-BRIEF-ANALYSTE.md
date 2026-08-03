# BRIEF ANALYSTE — MODULE M5 (FINANCECORE)

Huitième module de l'ordre ratifié ADR-0003 (M7→M1→M2→M4→M3→M6→M8→**M5**→M9). Fiche source :
`GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`, page 7 (tableau des modules + fiche condensée) ;
`PACK_CONSENSUS_GRS_v2.md`, ligne 42 ; frontières nettes inter-modules, page 9 ; service
transversal Approval Engine (D-010), page 4 ; REG-10 (mention professionnelle fiscale),
`docs/canon/REGLES.md`.

## 1. BESOIN MÉTIER

Nathan a besoin d'une source de vérité financière unique — comptes, mouvements, soldes — qui ne
confond jamais un solde brut avec l'argent réellement disponible, qui ne laisse jamais un taux
fiscal non sourcé se glisser dans un calcul, et qui ne permet structurellement à AUCUNE action
(mouvement d'argent réel, position fiscale) de se marquer approuvée sans le bon humain au bon
palier. La fiche source nomme explicitement deux paliers durs : **F6 = Nathan+MFA** (argent réel)
et **F7 = Nathan+CPA** (fiscal — mention professionnelle obligatoire, REG-10). Sans M5, chaque
autre module (M2 revenus, M4 coûts terrain, M6 matériaux) produit des faits financiers dans son
propre registre, mais personne ne les consolide en un état financier honnête — et rien n'empêche
aujourd'hui qu'un chiffre fiscal soit cité sans source ni version.

M5 n'est PAS un CFO qui décide (l'interprétation, l'arbitrage et la stratégie restent M9, plus
tard dans l'ordre — frontière nette explicite page 9 du plan) : c'est la couche qui enregistre les
faits financiers, calcule l'argent réellement disponible, et fait respecter structurellement les
paliers d'approbation F0-F7 — avant qu'un cerveau stratégique (M9) ou un humain ne s'en serve.

**Risque nommé et déjà mitigé par l'ordre de construction** : R-009 du registre de risques
(« M5 construit trop tôt = projections sur du vide ») a motivé le placement de M5 en position 8,
APRÈS M2/M3/M4/M6/M7/M8 — six modules qui, à ce jour, ont chacun un registre réel avec des faits
réels à consolider. M5 v1 n'a donc plus à choisir entre construire sur du vide ou attendre : les
sources amont existent déjà. Le risque résiduel (séries encore courtes pour un forecast 5 ans) est
traité en §6/§7, pas ignoré.

## 2. CONTRAINTES NON NÉGOCIABLES

### 2.1 Solde ≠ argent disponible — distinction structurelle, jamais un simple renommage

La fiche source est explicite : « solde différent d'argent disponible ». Un solde de compte est un
fait brut (somme des mouvements enregistrés) ; l'argent disponible est ce qui reste après
réservations connues (ex. provisions fiscales, engagements déjà approuvés mais non décaissés).
Ces deux valeurs doivent être deux champs distincts et calculés séparément dans tout contrat de
sortie — jamais un seul nombre réutilisé sous deux noms.

### 2.2 Taux fiscaux versionnés et sourcés, sinon blocage — jamais un nombre deviné

« Taux fiscaux versionnés SOURCÉS sinon blocage » (fiche source) : même patron que le price book
de M6 (« sourcé sinon FALLBACK ») et le dictionnaire de métriques de M7/M8 (metrics-as-code) —
un taux fiscal est une donnée déclarée, versionnée, avec sa source, jamais une constante codée en
dur dans le code Python. Une fonction qui a besoin d'un taux non déclaré ou non versionné DOIT
bloquer par un verdict nommé, jamais approximer ou reprendre le dernier taux connu sans le
signaler.

### 2.3 Fiscalité = RAG, jamais fine-tunée — et hors périmètre Python déterministe de M5 v1

« Fiscalité = RAG jamais fine-tunée » : toute réponse fiscale narrative doit citer ses sources
(cohérent avec D-029 RAG hybride+rerank et D-031 rédaction PII, fondations déjà ratifiées) et ne
doit JAMAIS provenir d'un modèle mémorisant des taux dans ses poids. **Ce brief ne dimensionne pas
ce système RAG** : comme pour M8 (« le LLM ne calcule jamais un chiffre »), la couche fiscale
conversationnelle est un AGENT hors périmètre des stories déterministes de ce module — M5 v1
fournit les taux sourcés et versionnés QUE ce futur agent citerait, il ne construit pas l'agent
lui-même.

### 2.4 F0-F7 — paliers d'approbation, F6/F7 structurellement infranchissables sans le bon humain

Le plan mandate une échelle F0-F7 pour toute décision financière, avec deux paliers nommés :
**F6 = argent réel, approbateur Nathan + MFA** ; **F7 = position fiscale, approbateur Nathan +
CPA (mention professionnelle obligatoire, REG-10)**. Ce N'EST PAS une convention documentaire :
une action au palier F6 ou F7 ne peut JAMAIS atteindre un état « approuvé » dans les données sans
qu'un champ approbateur ET un champ preuve (MFA / mention CPA) soient renseignés — vérifié
mécaniquement (patron `conformite.py` transversal, comme M3/M6/M8), pas seulement documenté.
**Hors périmètre v1** : la VÉRIFICATION cryptographique réelle d'un jeton MFA ou d'une signature
CPA (systèmes externes, T3/infra) — v1 prouve que la STRUCTURE DE DONNÉES et la machine à états
rendent l'état « approuvé » inatteignable sans ces champs, pas l'intégration à un vrai fournisseur
MFA.

### 2.5 Service transversal Approval Engine (D-010) — mesuré, pas encore construit

Le plan (page 4) classe le futur moteur d'approbation F0-F7/GATED_CPA de M5 comme un service
UNIFIÉ du core (D-010), au même titre que l'autorisation fine (ReBAC/OpenFGA). **Fait mesuré, pas
supposé** : `core/src/authz/` existe déjà (moteur `DomainAuthz` — `peut_lire`/`peut_ecrire`/
`peut_administrer`/`peut_voir_couts`, livré en Phase 0/P0-5) mais AUCUN module de domaine ne
l'importe à ce jour (`grep` vérifié sur `Modules M/`) ; un Approval Engine dédié multi-domaine
(file unique F0-F7/0-6/seuils M3/etc.) n'existe PAS encore comme service partagé. M5 v1 suit donc
le même patron que M1-M4/M6-M8 : une machine à états F0-F7 LOCALE, auto-suffisante, prouvée par
ses propres tests — la migration vers un Approval Engine central est un ADR distinct, futur, pas
un prérequis de ce cadrage (cohérent avec D-010 : « chaque module garde ses règles métier ; le
core fournit la mécanique » plus tard).

### 2.6 Rétention fiscale 6 ans vs minimisation Loi 25 — tension déjà tranchée « par classe »

Fondation technique déjà ratifiée (page 9 du plan) : rétention fiscale de 6 ans (Revenu Québec)
coexiste avec la minimisation Loi 25 en classant les données par CLASSE (une donnée fiscale
retenue 6 ans n'est pas soumise à la même politique de minimisation qu'une donnée conversationnelle
M1). M5 v1 doit structurer ses registres pour que cette classification soit explicite dès la
conception (champ de classe de rétention sur tout mouvement financier), pas ajoutée après coup.

### 2.7 L'employé ne voit jamais les coûts — même verrou que M2/M6/M8, transposé aux finances

Patron déjà établi trois fois (M2, M6, M8) : un rôle terrain n'a jamais accès aux données de
marge/coût. Transposé ici avec plus de force encore (M5 EST la source des coûts réels) : aucune
sortie de M5 destinée à un rôle non-financier ne contient de solde, de mouvement individuel, ni de
taux — mécanique par autorisation du contrat de sortie, jamais une convention de nommage espérée.

### 2.8 Adapters : read-only → dry-run → write gated — v1 ne dépasse jamais le read-only/dry-run

« Adapters read-only → dry-run → write gated » (fiche source) : toute intégration avec un système
externe réel (banque, paie, logiciel comptable) suit un palier progressif explicite. **v1 ne
construit aucun adapter réel** — v1 prouve les contrats et la mécanique interne sur des mouvements
fournis par l'appelant (patron déjà établi pour tous les modules précédents : M4 n'a pas de vraie
API météo/GPS en v1, M6 n'a pas de vrai fournisseur EDI). Un adapter réel, même read-only, est une
story GATED explicite et nommée en roadmap — jamais une intégration silencieuse.

## 3. FRONTIÈRES DU MODULE

### 3.1 Ce que M5 fait (v1)

- Enregistre des mouvements financiers dans un registre append-only hash-chaîné (patron déjà
  mesuré M2/M4/M6/M8).
- Calcule un solde ET un argent disponible distincts à partir de l'historique des mouvements.
- Déclare et versionne des taux fiscaux sourcés ; bloque tout calcul qui en réclame un non déclaré.
- Fait respecter une machine à états F0-F7 où F6/F7 sont structurellement inatteignables sans les
  champs approbateur + preuve requis.
- Classe chaque mouvement par classe de rétention (fiscale 6 ans vs autre).
- Produit un état financier déterministe et reproductible (référence à un `etat_id`, patron
  `snapshot_id`/`roi_engine.py`), filtré par rôle (aucun coût pour un rôle terrain).
- Applique une conformité statique transversale (patron `conformite.py` M3/M6/M8) : aucun taux
  codé en dur, aucun palier F6/F7 franchissable sans les deux champs requis, aucune fonction de M5
  n'écrit dans le registre d'un autre module.

### 3.2 Ce que M5 ne fait JAMAIS (v1)

- Ne construit aucun adapter réel vers une banque, un système de paie ou un logiciel comptable
  (read-only/dry-run/write gated — tous des stories GATED futures, pas v1).
- Ne construit pas l'agent RAG fiscal conversationnel (hors périmètre déterministe, comme le LLM
  narrateur de M8).
- Ne vérifie pas cryptographiquement un jeton MFA ni une signature CPA réelle — seule la
  STRUCTURE qui rend l'état « approuvé » inatteignable sans ces champs est prouvée en v1.
- Ne construit pas le forecast 5 ans (données historiques encore trop courtes pour être honnêtes —
  R-009 ; un forecast fondé sur un historique insuffisant serait une projection sur du vide,
  exactement le risque nommé).
- Ne construit pas le « CFO Decision Report » à 25 points de la fiche source dans son ensemble —
  M9 (interprétation/arbitrage/stratégie, frontière nette page 9) en est le candidat naturel
  consommateur ; question ouverte pour le PM en §7.1.
- Ne couvre pas les 20 sous-départements de la fiche source en une seule vague — même discipline
  que M7 (41 briques, 4 vagues) : v1 couvre le socle commun (registre, soldes, taux, F0-F7,
  conformité), pas chaque sous-département.
- Ne décide et ne recommande rien — M5 enregistre et calcule, M9 interprète et arbitre.

## 4. CONTRAT D'ENTRÉE — CE QUI EST MESURÉ, PAS SUPPOSÉ

- **Mouvement financier** : forme exacte à trancher en architecture ; contient au minimum un
  montant, un type (débit/crédit ou équivalent), un horodatage, une classe de rétention, et une
  référence à sa source (quel module/quelle action l'a généré — ex. un `devis_id` M3, une
  intervention M4). Patron d'horodatage et de hash-chaînage identique à
  `m6_material_control/registre.py` (déjà mesuré, pas réinventé).
- **Taux fiscal** : déclaré, versionné (patron metrics-as-code M7/M8 : fichier `*.yaml` sous
  `Modules M/M5-financecore/metrics/` ou équivalent fiscal, à trancher en architecture), avec sa
  source citée en texte. Aucun taux numérique codé en dur dans le Python — vérifié mécaniquement
  (patron `conformite.py::LITTERAL_COUT_INTERDIT` de M3/M6/M8, étendu aux taux).
- **Demande d'approbation F0-F7** : palier demandé, action concernée, et — SEULEMENT pour F6/F7 —
  identité de l'approbateur et preuve (MFA/CPA). Patron déjà mesuré : machine à états M2 (4
  statuts)/M4 (7 statuts intervention) — F0-F7 est une nouvelle échelle à 8 paliers, pas une
  réutilisation directe d'une échelle existante.

## 5. CONTRAT DE SORTIE — ESQUISSE (le PRD et l'architecture trancheront la forme gelée)

Un état financier M5 porte au minimum : solde ET argent disponible (deux champs distincts, §2.1),
la liste des mouvements ayant contribué (ou une référence au registre), les taux fiscaux utilisés
(avec leur version), et un identifiant déterministe couvrant l'ensemble (patron `snapshot_id`). Une
demande d'approbation F0-F7 porte au minimum : palier, état (`en_attente`/`approuve`/`refuse`), et
— non-nullable UNIQUEMENT si palier ∈ {F6, F7} — approbateur et preuve. Une vue filtrée par rôle
est une PROJECTION de ce même contrat, jamais une source de données parallèle (même règle que M8
§2.6).

## 6. MODE OMBRE ET MODE GATED

### 6.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib + PyYAML)

- Registre append-only hash-chaîné des mouvements financiers (copie-adaptation du patron déjà
  quatre fois mesuré).
- Calcul solde vs argent disponible à partir de l'historique.
- Déclaration et validation de taux fiscaux versionnés+sourcés ; blocage nommé si absent.
- Machine à états F0-F7 avec garde structurelle F6/F7 (approbateur+preuve non-nullables à ces
  paliers).
- Classification par classe de rétention sur chaque mouvement.
- État financier déterministe filtré par rôle.
- Conformité statique transversale (patron M3/M6/M8), étendue au garde-fou taux-codé-en-dur et à
  la garde F6/F7.

### 6.2 Repoussé GATED/T3

- **Adapters réels** (banque, paie, comptable) : read-only d'abord, dry-run ensuite, write en
  dernier — chacun une story GATED explicite et nommée, jamais une v1.
- **Agent RAG fiscal conversationnel** : hors périmètre déterministe, comme le LLM narrateur M8 ;
  dépend de D-029/D-031 déjà fondés mais construits ailleurs.
- **Forecast 5 ans** : différé jusqu'à un historique jugé suffisant (R-009) — v1 ne fabrique pas de
  projection sur un historique court ; un futur mécanisme de seuil `n` minimal (patron XmR M8)
  est le candidat naturel, pas un chiffre optimiste par défaut.
- **CFO Decision Report (25 points) complet** : candidat M9, à trancher en PRD (§7.1).
- **Vérification cryptographique réelle MFA/CPA** : intégration à un vrai fournisseur d'identité
  (Zitadel, P0-9b) — infra hors périmètre de ce module de domaine.
- **Intégration à un Approval Engine central du core** : le core n'a pas encore ce service unifié
  (§2.5) — migration future, ADR distinct.
- **Les 20 sous-départements dans leur richesse complète** : v1 = socle commun seulement.

## 7. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

### 7.1 Qui produit le « CFO Decision Report » — M5 ou M9 ?

La fiche source attribue ce livrable à M5, mais la frontière nette page 9 dit « M9 =
interprétation, arbitrage, stratégie ». Proposition : M5 v1 produit l'ÉTAT FINANCIER (primitive
factuelle, §5) ; le « CFO Decision Report » à 25 points, qui interprète et priorise, est un
livrable M9 qui CONSOMME l'état financier M5 — même relation que M7.11/M8 pour le MMM (M8 est
propriétaire architectural, M7.11 consomme). À confirmer explicitement dans le PRD, pas supposé
silencieusement.

### 7.2 Forme exacte du mouvement financier et de sa classe de rétention

Un dict simple `{montant, type, horodatage, classe_retention, source}` suffit-il en v1, ou faut-il
déjà une hiérarchie de comptes (plan comptable) ? Proposition : v1 reste plat (un seul type de
compte implicite), un plan comptable multi-niveaux est une extension de roadmap — cohérent avec la
discipline « socle d'abord » appliquée à M3/M4/M6/M8.

### 7.3 Échelle F0-F7 : les 8 paliers sont-ils tous distincts en v1, ou seuls F6/F7 sont-ils spéciaux ?

Proposition : v1 modélise les 8 paliers comme un énuméré fermé ordonné (F0..F7, échappatoire D-032
si un palier est indéterminé), mais SEULS F6 et F7 portent la contrainte structurelle
approbateur+preuve non-nullable — F0-F5 sont des paliers d'auto-approbation ou d'approbation
simple, à préciser en architecture par analogie avec les seuils d'approbation déjà mesurés (M3).

### 7.4 Taux fiscaux : fichier déclaratif dédié ou réutilisation de `metrics/*.yaml` ?

Proposition : fichier dédié (ex. `Modules M/M5-financecore/contracts/taux_fiscaux.v1.yaml`) plutôt
que `metrics/*.yaml` — un taux fiscal n'est pas une métrique au sens M7/M8 (pas de
`source_donnees`/`frequence` de collecte, mais une source légale/réglementaire et une période de
validité). Schéma à geler en architecture.

### 7.5 Comment M5 obtient les faits des modules déjà livrés (M2 revenus, M4 coûts terrain, M6 matériaux)

Même question que pour M8 (§7.5 de son brief), même réponse proposée : M5 ne doit PAS importer
`m2_revenue_crm`, `m4_field_ops`, `m6_material_control` (violation de #109 et de la frontière
d'enregistrement propre à M5). M5 reçoit un mouvement déjà construit par l'appelant ; la
construction à partir du registre réel d'un autre module est un service d'intégration distinct,
hors périmètre de M5 lui-même.
