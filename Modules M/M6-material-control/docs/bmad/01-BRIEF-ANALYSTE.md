# BRIEF ANALYSTE — MODULE M6 (MATERIAL CONTROL OS)

Rédigé par : Analyste BMAD | Statut : PROPOSÉ | Date : 2026-08-02

## 1. BESOIN MÉTIER

M6 est le seul module autorisé à porter le coût d'ACHAT des matériaux (catalogue fournisseur,
bons de commande) — une frontière distincte du prix de VENTE au client (domaine exclusif de M3)
et de la finance globale de l'entreprise (domaine exclusif de M5). Son mandat est de suivre le
cycle complet catalogue → bon de commande (PO) → réception → stock localisé par chantier, de
détecter les écarts (variance de réception, variance d'inventaire) sans jamais les interpréter
comme une faute, et de suggérer un réapprovisionnement sans jamais l'exécuter ni le payer. Les
bénéficiaires directs sont le répartiteur (qui commande et consulte le stock par chantier),
Nathan (qui consulte le digest quotidien des variances et suggestions de reorder), M5 (qui reçoit
le signal de montant à payer pour déclencher le règlement fournisseur), et le technicien terrain
(qui déclare les matériaux consommés sur une intervention et reçoit une confirmation SANS jamais
voir de coût). M6 ne planifie jamais d'intervention (rôle de M4), ne fixe jamais le prix facturé
au client (rôle de M3), ne facture ni ne paie jamais (rôle de M5), et ne devine jamais une faute
humaine à partir d'un écart chiffré.

## 2. CONTRAINTES NON NÉGOCIABLES

### 2.1 Variance sans accusation (R-020)

Un écart de matériau — qu'il survienne à la réception d'un bon de commande ou lors d'un inventaire
physique — est un CONSTAT chiffré, jamais une accusation. Le PACK_CONSENSUS est explicite :
« jamais vol automatique ». M6 ne produit aucun verdict de faute, aucune inculpation, aucune
présomption de malversation. Chaque écart porte un verdict neutre (conforme, écart en deçà, écart
au-delà, indéterminé) et une ampleur mesurée ; l'investigation de la cause reste une décision et
une action humaines, hors périmètre du module. Cette contrainte est la même famille de garde que
l'anti-précision-inventée de M3 (D-032) : un module qui affirme plus que ce que ses données
permettent de conclure produit un dommage — ici réputationnel et humain plutôt que commercial.

### 2.2 M6 ne paie jamais

M6 ne détient et n'exécute aucune primitive de paiement : aucun virement, aucune référence
bancaire, aucun statut de règlement (payé/non payé), aucune méthode de paiement. M6 calcule un
montant estimé à partir du catalogue fourni et émet un signal en lecture seule vers M5 ; c'est M5
qui décide et exécute le règlement fournisseur, exactement comme M4 émet un WCT vers M5 pour la
facturation client sans jamais facturer lui-même. M6 ne sait jamais, et ne cherche jamais à
savoir, si un paiement a effectivement eu lieu.

### 2.3 L'employé terrain ne voit pas les coûts

Le technicien qui déclare les matériaux consommés sur une intervention reçoit une confirmation
portant des QUANTITÉS et jamais un prix unitaire, un montant, ou une devise. Le coût existe dans
le module (le catalogue en a besoin pour le PO et pour l'accusé destiné à l'admin), mais il est
structurellement absent de tout contrat de sortie adressé au terrain. C'est une frontière de
contrat par destinataire, pas une frontière d'existence de la donnée — à la différence de M3 qui
ne porte aucune donnée financière du tout, M6 porte des coûts d'achat mais les cloisonne par
audience.

### 2.4 Catalogue sourcé, sinon FALLBACK, jamais inventé

Le catalogue de matériaux (price book) est une entrée fournie par l'appelant, au même titre que le
barème de M3 : M6 ne porte aucun prix codé en dur. Quand le catalogue fourni ne couvre pas le
matériau demandé, M6 recherche le dernier coût unitaire connu pour ce matériau dans son PROPRE
registre append-only (un fallback mesuré et traçable, jamais une extrapolation). Si ni le
catalogue ni l'historique n'ont de donnée exploitable, le bon de commande est bloqué avec un
verdict explicite — jamais un coût à zéro, jamais une moyenne devinée.

### 2.5 Stock localisé, jamais un pool global anonyme

Le stock est toujours rattaché à un chantier (ou à un entrepôt identifié comme tel). Aucune
opération de réception, de consommation, ou de variance ne s'applique à un pool global : la
localisation est une clé obligatoire de toute écriture de stock. C'est ce qui rend un écart
imputable à un lieu précis sans jamais nommer une personne.

### 2.6 Réapprovisionnement suggéré, jamais exécuté

Quand le stock localisé d'un chantier tombe sous un seuil configurable, M6 émet un signal de
suggestion de réapprovisionnement vers le répartiteur/admin. Ce signal n'engendre jamais
automatiquement un bon de commande, et encore moins un paiement : la décision de commander reste
humaine.

### 2.7 Registre append-only d'audit du stock

M6 maintient un registre append-only hash-chaîné de tous les mouvements (réception, consommation,
variance constatée) — le même patron prouvé que M2, M3 et M4, jamais réimporté, toujours
copié-adapté (décision #109). C'est la source de vérité unique pour les quantités de matériaux
(aucun autre module ne maintient sa propre copie faisant autorité).

## 3. FRONTIÈRES DU MODULE

### 3.1 Ce que M6 fait

- Reçoit le WCT (Work Completion Trigger) émis par M4 à la clôture d'une intervention — M6 figure
  explicitement dans `consommateurs_cibles` du WCT réel (mesuré dans `m4_field_ops/outbox.py`).
- Valide structurellement le WCT reçu, sans jamais recalculer son `hash_maillon` (M6 ne possède
  pas le registre de M4 — la même limite déclarée que M3 vis-à-vis de M2).
- Maintient un catalogue de matériaux fourni par l'appelant, avec résolution de prix par FALLBACK
  historique.
- Gère le cycle bon de commande → réception → stock localisé par chantier.
- Détecte et enregistre les écarts (réception, inventaire) avec un verdict neutre, jamais
  accusatoire.
- Émet un signal de suggestion de réapprovisionnement, jamais un achat automatique.
- Sépare structurellement ses contrats de sortie par destinataire (terrain sans coût, admin/M5
  avec coût).
- Maintient le registre append-only d'audit du stock.

### 3.2 Ce que M6 ne fait JAMAIS

- **Prix de vente** — M6 ne fixe jamais le prix facturé au client. C'est le domaine exclusif de
  M3.
- **Dates et planification** — M6 ne planifie jamais d'intervention, ne propose jamais de
  créneau. C'est le domaine exclusif de M4.
- **Paiement et facturation** — M6 ne génère jamais de facture, n'exécute jamais de paiement, ne
  détient aucune primitive bancaire. C'est le domaine exclusif de M5.
- **Accusation** — M6 ne désigne jamais une personne responsable d'un écart. Aucun champ de
  « cause » n'est jamais rempli automatiquement.
- **Achat automatique** — le signal de reorder est une suggestion ; aucun bon de commande n'est
  émis ni payé sans décision humaine.
- **Inférence visuelle ou OCR réel** — la lecture de factures/bordereaux par vision par ordinateur
  est repoussée en GATED/T3 ; la saisie v1 est manuelle ou assistée (cohérent avec le report déjà
  ratifié de l'OCR M5/M6 dans le plan maître).
- **Parsing de courriels fournisseurs par LLM** — le risque d'injection indirecte (R-015, ratifié
  comme touchant M6 via les courriels fournisseurs) est neutralisé nativement en v1 : mode ombre
  pur, zéro réseau, zéro LLM. Ce canal reste GATED/T3, avec défense en profondeur (REG-13)
  obligatoire s'il est activé plus tard.

## 4. CONTRAT D'ENTRÉE — CE QUI EST MESURÉ, PAS SUPPOSÉ

Le WCT réellement émis par M4 (`m4_field_ops/outbox.py`, constante `CHAMPS_WCT`) porte DOUZE
clés : `wct_id`, `intervention_id`, `lead_id`, `technicien_id`, `horodatage_completion`,
`fix_gps_completion`, `duree_reelle_minutes`, `ecart_signale`, `revue_id`, `hash_maillon`,
`consommateurs_cibles`, `devis_id`. Il NE PORTE AUCUN champ de matériaux — le « formulaire
matériaux » évoqué au plan maître comme déclenché à la clôture des travaux n'est PAS une clé du
WCT lui-même : c'est un artefact séparé que M6 définit et reçoit indépendamment, référençant le
`wct_id` pour prouver qu'une intervention réelle et complétée en est l'origine. Cette distinction
évite l'erreur mesurée sur M3 (issue #166) : un cadrage qui aurait supposé un champ matériaux DANS
le WCT aurait décrit un contrat fantôme.

M6 valide donc DEUX entrées distinctes en provenance de M4 : le WCT lui-même (structurellement,
sans recalcul de son hash — M6 ne possède pas le registre de M4) et le formulaire de consommation
de matériaux qui le référence. Un formulaire dont le `wct_id` ne correspond à aucun WCT
structurellement valide est rejeté.

Le catalogue de matériaux, les bons de commande, et les réceptions sont des entrées séparées,
fournies par l'appelant (répartiteur/admin), jamais devinées.

## 5. CONTRAT DE SORTIE — ESQUISSE (le PRD et l'architecture trancheront la forme gelée)

- Un accusé de réception de PO, à destination admin, portant coûts et verdict de variance de
  réception.
- Une confirmation de consommation, à destination du technicien terrain, ne portant JAMAIS de
  coût.
- Un maillon d'audit de stock append-only, à destination M5/admin, portant les coûts complets.
- Un signal de suggestion de réapprovisionnement, à destination admin.
- Un signal de montant à payer, en lecture seule, à destination M5.
- Un digest quotidien déterministe des variances et suggestions, à destination de Nathan.

> **Avertissement de portée** : ces esquisses sont des PROPOSITIONS d'analyste, antérieures au
> gel. Le pacte qui fera foi est celui scellé au PRD et à l'architecture ; toute divergence entre
> ce brief et ces deux documents se tranche en faveur des seconds.

## 6. MODE OMBRE ET MODE GATED

### 6.1 En périmètre v1 (mode ombre, prouvable en CI Python)

- Validation structurelle du WCT (M4) et du formulaire de consommation qui le référence.
- Catalogue de matériaux avec résolution de prix par FALLBACK historique traçable.
- Cycle bon de commande → réception → variance de réception, verdict neutre.
- Stock localisé par chantier, décrémenté à la consommation.
- Variance d'inventaire (théorique vs compté), verdict neutre, aucune cause auto-déduite.
- Signal de suggestion de réapprovisionnement (jamais d'achat automatique).
- Séparation structurelle des contrats de sortie par destinataire (garde AST : aucun coût dans le
  contrat terrain).
- Registre append-only hash-chaîné d'audit du stock.
- Digest quotidien déterministe vers Nathan.

### 6.2 Repoussé GATED/T3

- Lecture automatique de factures/bordereaux par OCR ou vision par ordinateur.
- Tout parsing de courriel fournisseur par un LLM (R-015, défense en profondeur REG-13 requise
  avant activation).
- Toute intégration bancaire ou d'exécution de paiement réel.

## 7. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

### 7.1 Seuil de réapprovisionnement

L'analyste propose un seuil de reorder configurable PAR chantier ET par matériau (pas un seuil
global unique), fourni par l'appelant au même titre que le catalogue. Le PM tranchera sur la
possibilité d'un seuil par défaut en son absence, ou sur un blocage explicite faute de seuil
fourni (cohérence avec la garde anti-invention déjà établie ailleurs).

### 7.2 Fréquence de consolidation des variances d'inventaire

L'analyste propose que la variance d'inventaire soit calculée à la demande (sur soumission d'un
comptage physique), pas sur une horloge interne (M6 n'a pas d'horloge, comme tous les modules
voisins). Le PM tranchera sur la possibilité d'un seuil d'ampleur en dessous duquel une variance
n'est pas remontée au digest (bruit de comptage).

### 7.3 Granularité du signal de montant à payer vers M5

L'analyste propose un signal par bon de commande réceptionné (pas de consolidation). Le PM
tranchera sur la possibilité d'une consolidation périodique côté M5 plutôt que côté M6 (M6 reste
un émetteur simple, jamais un agrégateur financier).

### 7.4 Note d'investigation humaine sur une variance

L'analyste propose un champ optionnel `note_investigation` rempli manuellement par un humain après
coup, jamais déduit par le module. Le PM tranchera sur son inclusion en v1 ou son report (le
registre append-only permettant de toute façon un ajout ultérieur sans réécriture).

### 7.5 Portée du chantier vs entrepôt central

L'analyste propose de traiter un entrepôt central comme un `chantier_id` particulier (pas une
notion distincte), pour garder un seul mécanisme de localisation. Le PM tranchera sur la nécessité
d'un type distinct en v1 ou son report en roadmap.
