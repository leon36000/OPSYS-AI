# PRD — MODULE M6 (MATERIAL CONTROL OS)

Rédigé par : PM BMAD | Statut : PROPOSÉ | Date : 2026-08-02

---

## 0. TRANCHÉ SUR LES POINTS OUVERTS DE L'ANALYSTE

1. **Seuil de reorder (7.1)** — configurable par chantier ET par matériau, fourni par l'appelant.
   Pas de valeur par défaut : en l'absence de seuil fourni pour un couple donné, M6 n'émet AUCUN
   signal pour ce couple (silence), plutôt qu'un blocage. Le reorder est une fonctionnalité
   suggestive et additive, pas un chemin critique comme le devis M3 : ne rien suggérer n'est pas
   un mensonge, contrairement à un prix inventé.
2. **Fréquence de consolidation (7.2)** — à la demande, sur soumission d'un comptage physique.
   Aucun seuil de bruit par défaut en v1 (toute variance, même minime, est enregistrée au registre
   ET remontée au digest) ; un seuil de filtrage devient un paramètre configurable de roadmap si
   la mesure en pratique montre un digest trop bruyant.
3. **Granularité du signal vers M5 (7.3)** — un signal par bon de commande réceptionné, jamais de
   consolidation côté M6. M6 reste un émetteur simple.
4. **Note d'investigation (7.4)** — incluse en v1, champ optionnel `note_investigation`, jamais
   rempli automatiquement par le module ; seul un appel humain explicite et distinct de tout calcul
   de variance peut la renseigner.
5. **Chantier vs entrepôt (7.5)** — un entrepôt central est un `chantier_id` comme un autre en v1.
   Aucun type distinct. Report en roadmap si un besoin réel de distinction apparaît.

---

## 1. PERSONAS

| Persona | Rôle | Interaction avec M6 |
|---|---|---|
| **Nathan** | Propriétaire de l'entreprise | Consulte le digest quotidien des variances et des suggestions de reorder. Ne modifie jamais un mouvement de stock. |
| **Répartiteur / admin** | Gestion des chantiers | Crée les bons de commande, déclare les réceptions et les comptages d'inventaire, consulte les accusés de réception (avec coûts) et les signaux de reorder. |
| **Technicien terrain** | Exécutant | Déclare les matériaux consommés sur une intervention (référencée par son WCT), reçoit une confirmation SANS coût. |
| **M4 (Field Ops)** | Module amont | Émet le WCT à la clôture d'une intervention ; M6 en est un consommateur explicite (`consommateurs_cibles`). |
| **M5 (FinanceCore)** | Module aval | Reçoit le signal de montant à payer par bon de commande réceptionné ; exécute seul le règlement fournisseur. |

---

## 2. PARCOURS PRINCIPAUX

### 2.1 Commande, réception, résolution de prix

**Précondition** : un répartiteur a besoin de matériaux pour un chantier.

**Déroulement** :
1. Le répartiteur soumet un `BonDeCommandeDemande` (chantier, lignes demandées).
2. À l'arrivée physique, il déclare une `ReceptionPO` (lignes reçues, éventuellement différentes
   des lignes demandées).
3. M6 résout le coût unitaire de chaque ligne : catalogue fourni → historique du registre
   (FALLBACK) → `INDETERMINE` si aucun des deux n'est exploitable.
4. M6 calcule le verdict de réception (conforme / inférieure / supérieure / mixte) et le montant
   total estimé (null si au moins une ligne est `INDETERMINE`).
5. M6 émet l'`AccuseReceptionPO` (admin, avec coûts) et, si le montant est résolu, un
   `SignalPoAPayer` en lecture seule vers M5.
6. Le stock localisé du chantier est incrémenté des quantités reçues.

**Postcondition** : le stock localisé reflète la réception ; M5 dispose (ou non) d'un signal de
montant à payer selon que le prix a pu être résolu.

### 2.2 Consommation sur intervention terrain

**Précondition** : M4 a émis un WCT pour une intervention complétée, `"M6"` figurant dans ses
`consommateurs_cibles`.

**Déroulement** :
1. Le technicien soumet un `FormulaireConsommationMateriaux` référençant le `wct_id`.
2. M6 valide structurellement le WCT reçu (sans recalculer son `hash_maillon`) et vérifie que le
   `wct_id` du formulaire y correspond.
3. M6 vérifie que le stock localisé du chantier couvre chaque ligne consommée ; une consommation
   excédant le stock disponible est rejetée explicitement.
4. Le stock localisé est décrémenté.
5. M6 émet une `ConfirmationConsommationTerrain` — quantités seulement, aucun coût.

**Postcondition** : le stock localisé reflète la consommation ; le technicien n'a vu aucun prix.

### 2.3 Inventaire et variance sans accusation

**Précondition** : un comptage physique est réalisé sur un chantier.

**Déroulement** :
1. Le répartiteur soumet un `ComptageInventaire` (chantier, matériau, quantité comptée).
2. M6 calcule le stock théorique depuis son registre (somme des réceptions moins les
   consommations pour ce couple chantier/matériau).
3. M6 compare théorique et compté : `AUCUN_ECART`, `STOCK_INFERIEUR_AU_THEORIQUE`, ou
   `STOCK_SUPERIEUR_AU_THEORIQUE` — jamais de champ de cause rempli automatiquement.
4. L'écart est inscrit au registre et remonté au digest quotidien.

**Postcondition** : l'écart est un CONSTAT chiffré et daté, imputé à un chantier, jamais à une
personne. L'investigation reste une décision humaine hors périmètre du module.

### 2.4 Suggestion de réapprovisionnement

**Précondition** : un seuil de reorder a été fourni pour un couple chantier/matériau.

**Déroulement** :
1. Après chaque mouvement de stock (réception ou consommation), M6 compare le stock localisé
   résultant au seuil fourni pour ce couple.
2. Si le stock est strictement inférieur au seuil, M6 émet un `SignalReorder` avec une quantité
   suggérée déterministe (`seuil - stock_actuel`).
3. Aucun bon de commande n'est créé, aucun paiement n'est déclenché.

**Postcondition** : le répartiteur reçoit une suggestion ; la décision de commander reste humaine.

---

## 3. PÉRIMÈTRE V1 vs ROADMAP

### 3.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Description |
|---|---|
| Validation du WCT (M4) | Structurelle, sans recalcul du hash, DOUZE clés exactes |
| Catalogue avec FALLBACK | Catalogue fourni → historique registre → `INDETERMINE` |
| Cycle PO → réception | Verdict de réception, montant estimé avec équivalence null↔INDETERMINE |
| Stock localisé | Par chantier, jamais un pool global ; incrément/décrément fail-closed |
| Variance d'inventaire | Verdict neutre, aucune cause auto-déduite (R-020) |
| Reorder suggéré | Jamais un achat automatique, silence si seuil non fourni |
| Contrats séparés par destinataire | Terrain sans coût, admin/M5 avec coût — garde AST |
| Registre append-only | Patron copié-adapté de M2/M3/M4 |
| Digest quotidien | Vers Nathan, déterministe |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 3.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| OCR / vision réelle sur factures et bordereaux | Poids modèle, GPU, infrastructure réseau (cohérent avec le report déjà ratifié M5/M6) |
| Parsing de courriel fournisseur par LLM | R-015 injection indirecte ; défense en profondeur REG-13 requise avant activation |
| Intégration bancaire / exécution de paiement réel | M6 ne paie jamais — hors périmètre par frontière, pas seulement par séquencement |

---

## 4. ÉNUMÉRÉS FERMÉS

Conformément à D-032, chaque énuméré ci-dessous porte une échappatoire `INDETERMINE` obligatoire.

### 4.1 VerdictResolutionPrix

| Valeur | Condition d'obtention |
|---|---|
| `PRIX_CATALOGUE` | Le matériau figure dans le `CatalogueMateriaux` fourni à cet appel. |
| `PRIX_HISTORIQUE_FALLBACK` | Absent du catalogue fourni ; le registre porte au moins un mouvement antérieur pour ce matériau avec un `cout_unitaire` non nul — le PLUS RÉCENT par ordre du registre est utilisé. |
| `INDETERMINE` | **Échappatoire D-032** — ni le catalogue ni l'historique n'ont de donnée exploitable pour ce matériau. La ligne concernée est bloquée : `cout_unitaire_resolu = null`. |

### 4.2 VerdictReception

| Valeur | Condition d'obtention |
|---|---|
| `CONFORME` | Chaque ligne du PO a une quantité reçue égale à la quantité demandée. |
| `RECEPTION_INFERIEURE` | Au moins une ligne reçue en quantité strictement inférieure, aucune en quantité supérieure. |
| `RECEPTION_SUPERIEURE` | Au moins une ligne reçue en quantité strictement supérieure, aucune en quantité inférieure. |
| `RECEPTION_MIXTE` | Coexistence de lignes inférieures ET supérieures sur le même PO — jamais fusionné dans un des deux verdicts précédents, un PO à lignes multiples n'est pas réductible à un seul signe d'écart. |
| `INDETERMINE` | **Échappatoire D-032** — PO introuvable, ou lignes de réception non appariables aux lignes demandées. |

### 4.3 VerdictVarianceStock

| Valeur | Condition d'obtention |
|---|---|
| `AUCUN_ECART` | Quantité comptée égale à la quantité théorique. |
| `STOCK_INFERIEUR_AU_THEORIQUE` | Quantité comptée strictement inférieure à la théorique. Constat chiffré, AUCUNE cause attribuée (R-020). |
| `STOCK_SUPERIEUR_AU_THEORIQUE` | Quantité comptée strictement supérieure à la théorique. Constat chiffré, AUCUNE cause attribuée (R-020). |
| `INDETERMINE` | **Échappatoire D-032** — aucun mouvement théorique préalable pour ce couple chantier/matériau (rien à comparer). Comparer contre zéro produirait un écart fabriqué. |

---

## 5. CONTRATS GELÉS

Conformément à D-015, ces contrats sont des pactes exécutables. Toute clé est obligatoire sauf
mention explicite.

> **Précision de portée (objection de revue scellée, Qwen3.8-Max, fondée)** : la frontière
> qui suit s'applique aux contrats ÉMIS PAR M6 (sorties), jamais aux contrats REÇUS d'un module
> amont dont M6 n'écrit pas le schéma. Aucun contrat ÉMIS par M6 ne porte de champ de date
> d'intervention, de créneau, de durée d'exécution, ou de primitive de paiement (virement, statut
> de règlement, méthode de paiement, référence bancaire) — M6 ne planifie jamais et ne paie
> jamais. Le contrat d'entrée `WctRecu` (§5.1) fait exception À LA LETTRE, jamais À L'ESPRIT : il
> porte `duree_reelle_minutes`, un champ que M4 calcule et que M6 REÇOIT tel quel sans jamais le
> décider, le modifier, ni s'en servir pour planifier quoi que ce soit — exactement comme M3 reçoit
> sans les re-juger des conditions déjà tranchées par M2. Aucun contrat de SORTIE de M6 (§5.6 à
> §5.10) ne porte de champ de durée.

### 5.1 Entrée reçue de M4 — `WctRecu` (mesuré, pas supposé)

Copie exacte des DOUZE clés de `CHAMPS_WCT` dans `m4_field_ops/outbox.py` :

```yaml
WctRecu:
  wct_id: str
  intervention_id: str
  lead_id: str
  technicien_id: str
  horodatage_completion: str
  fix_gps_completion: {latitude: float, longitude: float}
  duree_reelle_minutes: int
  ecart_signale: bool
  revue_id: str | null
  hash_maillon: str
  consommateurs_cibles: list[str]   # doit contenir "M6"
  devis_id: str | null
```

M6 valide la présence EXACTE de ces douze clés (aucune de plus, aucune de moins) et que `"M6"`
figure dans `consommateurs_cibles`. **M6 ne recalcule JAMAIS `hash_maillon`** — il ne possède pas
le registre de M4, exactement comme M3 ne recalcule jamais l'empreinte du marqueur de M2.

### 5.2 Entrée — `FormulaireConsommationMateriaux` (fourni par l'appelant, référence le WCT)

```yaml
FormulaireConsommationMateriaux:
  wct_id: str              # doit correspondre à un WctRecu structurellement valide fourni à l'appel
  intervention_id: str     # doit correspondre au WctRecu référencé
  chantier_id: str
  lignes_consommees:
    - materiau_id: str
      quantite: float       # > 0
```

### 5.3 Entrée — `CatalogueMateriaux` (fourni par l'appelant, jamais codé en dur)

```yaml
CatalogueMateriaux:
  version: str
  unite_monetaire: str
  postes:
    <materiau_id>:
      cout_unitaire: float   # > 0
      libelle: str
```

Validation fail-closed : catalogue absent, `postes` vide ou malformé → tout matériau demandé passe
directement en résolution FALLBACK/`INDETERMINE`, jamais en erreur bloquante globale (le catalogue
peut être partiel par design, comme `BaremeCouts` de M3).

### 5.4 Entrée — `BonDeCommandeDemande` et `ReceptionPO`

```yaml
BonDeCommandeDemande:
  po_id: str
  chantier_id: str
  lignes_demandees:
    - materiau_id: str
      quantite_demandee: float   # > 0
  horodatage: str                 # ISO-8601, fuseau obligatoire

ReceptionPO:
  po_id: str                      # doit correspondre à un BonDeCommandeDemande émis
  chantier_id: str                # doit correspondre au PO référencé
  lignes_recues:
    - materiau_id: str
      quantite_recue: float        # >= 0
  horodatage: str
```

### 5.5 Entrée — `ComptageInventaire` et `SeuilReorder`

```yaml
ComptageInventaire:
  chantier_id: str
  materiau_id: str
  quantite_comptee: float   # >= 0
  horodatage: str

SeuilReorder:
  chantier_id: str
  materiau_id: str
  seuil_quantite: float      # sous ce seuil, une suggestion est émise
```

### 5.6 Sortie — `AccuseReceptionPO` (destination admin — porte les coûts)

```yaml
AccuseReceptionPO:
  po_id: str
  chantier_id: str
  verdict_reception: str          # enum VerdictReception
  lignes:
    - materiau_id: str
      quantite_demandee: float
      quantite_recue: float
      ecart: float                       # quantite_recue - quantite_demandee, SIGNÉ
      verdict_resolution_prix: str        # enum VerdictResolutionPrix, PAR LIGNE
      cout_unitaire_resolu: float | null  # null SSI verdict_resolution_prix == INDETERMINE
      montant_ligne: float | null         # cout_unitaire_resolu * quantite_recue, null si le coût est null
  montant_total_estime: float | null
    # Équivalence testable : montant_total_estime est null SI ET SEULEMENT SI au
    # moins une ligne porte verdict_resolution_prix == INDETERMINE. Sommer en
    # ignorant les lignes bloquées produirait un total FAUSSEMENT complet.
  bareme_version: str | null       # version du catalogue fourni à cet appel ; null si aucun catalogue fourni
  hash_maillon: str
```

### 5.7 Sortie — `ConfirmationConsommationTerrain` (destination technicien — SANS coût)

```yaml
ConfirmationConsommationTerrain:
  intervention_id: str
  chantier_id: str
  materiaux_confirmes:
    - materiau_id: str
      quantite_declaree: float
  stock_restant:
    - materiau_id: str
      quantite: float
  hash_maillon: str
```

**Aucune clé de coût, à aucun niveau** : ni `cout_unitaire`, ni `cout`, ni `prix`, ni `montant`, ni
`devise`, ni `unite_monetaire`. Garde vérifiée par inspection ET par test d'intégration depuis le
point d'entrée public (leçon retenue : un test qui n'exerce que des fonctions isolées peut
masquer un chemin réel qui, lui, assemble le contrat différemment).

### 5.8 Sortie — `SignalReorder`, `SignalVarianceStock`, `SignalPoAPayer`

```yaml
SignalReorder:
  chantier_id: str
  materiau_id: str
  stock_actuel: float
  seuil_quantite: float
  quantite_suggeree: float   # = seuil_quantite - stock_actuel, déterministe, aucune marge inventée
  horodatage: str

SignalVarianceStock:
  chantier_id: str
  materiau_id: str
  verdict_variance: str        # enum VerdictVarianceStock
  quantite_theorique: float
  quantite_comptee: float
  ecart: float                  # quantite_comptee - quantite_theorique, SIGNÉ
  note_investigation: str | null   # jamais rempli automatiquement ; ajout humain explicite seulement
  horodatage: str
  hash_maillon: str

SignalPoAPayer:
  po_id: str
  chantier_id: str
  montant_total_estime: float
    # Ce signal N'EST JAMAIS ÉMIS si montant_total_estime serait null (prix
    # indéterminé) : M5 ne doit jamais recevoir un montant à payer indéterminé.
  bareme_version: str | null
    # Objection de revue scellée (Qwen3.8-Max, fondée) : un PO peut être intégralement
    # résolu par PRIX_HISTORIQUE_FALLBACK (aucun catalogue fourni à cet appel), auquel
    # cas montant_total_estime EST résolu (le signal est bien émis) alors qu'il n'existe
    # aucune version de catalogue à tracer — même équivalence que bareme_version dans
    # AccuseReceptionPO (§5.6) : null SI ET SEULEMENT SI aucun catalogue n'a été fourni
    # à cet appel, jamais parce que le montant serait indéterminé (ce cas n'émet aucun
    # signal, cf. ci-dessus).
  hash_maillon: str
```

**Aucun de ces trois contrats ne porte** : `statut_paiement`, `virement`, `reference_bancaire`,
`mode_paiement` — M6 émet un montant à payer, jamais un ordre ni un statut de règlement.

### 5.9 Sortie — `DigestMaterielQuotidien` (destination Nathan)

```yaml
DigestMaterielQuotidien:
  type: str                     # toujours "DIGEST_MATERIEL"
  nb_variances_stock: int
  nb_reorders_suggeres: int
  variances_significatives:
    - chantier_id: str
      materiau_id: str
      verdict_variance: str
      ecart: float
  reorders:
    - chantier_id: str
      materiau_id: str
      quantite_suggeree: float
  hash_digest: str               # sha256 déterministe du contenu du digest
```

### 5.10 Maillon du registre append-only — `MaillonMateriel`

```yaml
MaillonMateriel:
  index: int
  type_mouvement: str    # enum fermé : RECEPTION | CONSOMMATION | VARIANCE_INVENTAIRE
  chantier_id: str
  materiau_id: str
  quantite: float          # signée : positive pour une entrée (réception), négative pour une sortie (consommation)
  cout_unitaire: float | null   # null pour CONSOMMATION et pour VARIANCE_INVENTAIRE (le terrain ne fixe jamais de coût)
  hash_precedent: str      # chaîne vide pour index 0
  hash_maillon: str        # sha256 de ce maillon (inclut hash_precedent)
```

**Champs absents par design** (frontières M6) :
- Aucun prix de vente client — domaine de M3.
- Aucune date d'intervention, créneau, ou durée — domaine de M4.
- Aucune primitive de paiement (statut, virement, référence bancaire) — domaine de M5.

---

## 6. CRITÈRES D'ACCEPTATION

24 critères numérotés, chacun testable déterministiquement, chacun porté par une story unique.

| ID | Critère | Moyen de vérification | Story |
|---|---|---|---|
| CA-M6-01 | Le `WctRecu` de M4 (DOUZE clés exactes, mesurées dans `m4_field_ops.outbox.CHAMPS_WCT`) est validé structurellement ; toute clé manquante, en trop, ou `"M6"` absent de `consommateurs_cibles` produit un rejet nommé. M6 ne recalcule jamais `hash_maillon`. | Test unitaire : un cas par classe de faute, chacun isolant SA faute ; assertion qu'aucune fonction du module n'appelle un recalcul de hash sur le WCT. | S001 |
| CA-M6-02 | Un `FormulaireConsommationMateriaux` dont le `wct_id` ne correspond à aucun `WctRecu` structurellement valide fourni à l'appel est rejeté explicitement (verdict nommé, distinct du rejet de schéma générique). | Test unitaire : formulaire avec wct_id inconnu, assertion sur le verdict nommé. | S001 |
| CA-M6-03 | Toute clé interdite (`statut_paiement`, `virement`, `reference_bancaire`, `mode_paiement`, `prix_vente`, `date_execution`, `creneau`, `duree`) présente à N'IMPORTE quel niveau d'une entrée provoque un rejet EXPLICITE et DISTINCT du rejet générique de schéma. | Test unitaire : une clé interdite au sommet, une imbriquée dans une ligne de catalogue ou de PO ; assertion que le verdict nomme la clé interdite. | S001 |
| CA-M6-04 | Un matériau présent dans le `CatalogueMateriaux` fourni produit `verdict_resolution_prix = PRIX_CATALOGUE` et `cout_unitaire_resolu` égal au coût du catalogue. | Test unitaire : appel avec catalogue couvrant le matériau, assertion sur le verdict et la valeur. | S002 |
| CA-M6-05 | Un matériau absent du catalogue fourni mais présent dans l'historique du registre produit `verdict_resolution_prix = PRIX_HISTORIQUE_FALLBACK` avec le coût du mouvement le PLUS RÉCENT du registre pour ce matériau. | Test unitaire : registre avec deux mouvements de coûts différents pour le même matériau, catalogue ne le couvrant pas, assertion que le coût retourné est celui du mouvement le plus récent. | S002 |
| CA-M6-06 | Un matériau absent à la fois du catalogue et de l'historique produit `verdict_resolution_prix = INDETERMINE`, `cout_unitaire_resolu = null`, `montant_ligne = null`. | Test unitaire : catalogue et registre ne couvrant pas le matériau, assertion sur la nullité. | S002 |
| CA-M6-07 | Un PO dont toutes les lignes ont une quantité reçue égale à la quantité demandée produit `verdict_reception = CONFORME`. | Test unitaire : réception exacte, assertion sur le verdict. | S003 |
| CA-M6-08 | Un PO avec au moins une ligne reçue en quantité strictement inférieure (et aucune supérieure) produit `verdict_reception = RECEPTION_INFERIEURE`. | Test unitaire : réception partielle, assertion sur le verdict. | S003 |
| CA-M6-09 | Un PO avec au moins une ligne reçue en quantité strictement supérieure (et aucune inférieure) produit `verdict_reception = RECEPTION_SUPERIEURE`. | Test unitaire : réception en surplus, assertion sur le verdict. | S003 |
| CA-M6-10 | Un PO portant simultanément des lignes inférieures ET supérieures produit `verdict_reception = RECEPTION_MIXTE`, jamais fusionné dans les deux verdicts précédents. | Test unitaire : PO à deux lignes, une inférieure et une supérieure, assertion sur `RECEPTION_MIXTE`. | S003 |
| CA-M6-11 | `montant_total_estime` de l'accusé de réception est `null` SI ET SEULEMENT SI au moins une ligne porte `verdict_resolution_prix = INDETERMINE` ; sinon il est la somme exacte des `montant_ligne`. | Test unitaire : cas toutes lignes résolues (assertion somme exacte) et cas une ligne `INDETERMINE` (assertion nullité totale malgré les autres lignes résolues). | S003 |
| CA-M6-12 | Le stock localisé d'un chantier est incrémenté à la réception et décrémenté à la consommation ; toute opération sans `chantier_id` est rejetée. | Test unitaire : séquence réception puis consommation, assertion sur le solde ; appel sans chantier_id, assertion de rejet. | S004 |
| CA-M6-13 | Une consommation dont la quantité demandée excède le stock localisé disponible du chantier pour ce matériau est rejetée explicitement ; le stock ne devient jamais négatif silencieusement. | Test unitaire : consommation supérieure au stock disponible, assertion de rejet nommé et stock inchangé. | S004 |
| CA-M6-14 | Une comparaison entre le stock théorique (dérivé du registre) et un comptage physique égal produit `verdict_variance = AUCUN_ECART`. | Test unitaire : comptage égal au théorique, assertion sur le verdict. | S005 |
| CA-M6-15 | Un comptage strictement inférieur au théorique produit `STOCK_INFERIEUR_AU_THEORIQUE` ; un comptage strictement supérieur produit `STOCK_SUPERIEUR_AU_THEORIQUE` ; dans les deux cas `note_investigation` reste `null` tant qu'aucun ajout humain explicite n'a eu lieu, et aucune fonction de calcul ne remplit de champ de cause. | Test unitaire : deux cas d'écart, assertion sur le verdict ET sur la nullité de `note_investigation` ; inspection statique qu'aucune fonction de variance ne référence un champ de cause/faute. | S005 |
| CA-M6-16 | Un couple chantier/matériau sans mouvement théorique préalable produit `verdict_variance = INDETERMINE` plutôt qu'un écart calculé contre zéro. | Test unitaire : comptage sur un couple jamais mouvementé, assertion sur `INDETERMINE`. | S005 |
| CA-M6-17 | Un stock localisé strictement inférieur au seuil de reorder fourni pour ce couple chantier/matériau émet un `SignalReorder` avec `quantite_suggeree = seuil_quantite - stock_actuel` ; en l'absence de seuil fourni pour ce couple, aucun signal n'est émis. | Test unitaire : stock sous seuil avec seuil fourni (assertion signal et valeur) ; stock sous un seuil implicite mais AUCUN `SeuilReorder` fourni pour ce couple (assertion absence de signal). | S006 |
| CA-M6-18 | Aucune fonction du module ne relie directement un `SignalReorder` à la création d'un `BonDeCommandeDemande` ou à un paiement. | Inspection statique (AST) : aucune fonction n'appelle le constructeur de bon de commande depuis le chemin d'émission du signal de reorder. | S006 |
| CA-M6-19 | Le contrat `ConfirmationConsommationTerrain` ne porte, à AUCUN niveau, une clé parmi (`cout_unitaire`, `cout`, `prix`, `montant`, `devise`, `unite_monetaire`, `montant_total_estime`) — vérifié par inspection du schéma ET par un test traversant le point d'entrée public (pas seulement une fonction isolée). | Inspection du schéma + test d'intégration bout en bout : consommation réelle via le point d'entrée public, assertion sur les clés du contrat retourné. | S007 |
| CA-M6-20 | Aucun contrat émis par M6, quel qu'il soit, ne porte de clé parmi (`statut_paiement`, `virement`, `reference_bancaire`, `mode_paiement`) — analyse statique (AST) sur l'ensemble des littéraux de dict du module. | Analyse statique (AST) : absence des quatre clés dans tout littéral de dict retourné par une fonction publique. | S007 |
| CA-M6-21 | L'ajout d'un mouvement au registre append-only préserve la chaîne de hash (`hash_maillon` inclut `hash_precedent`) ; la validation de la chaîne complète échoue dès qu'un maillon est altéré. | Test unitaire : ajout de deux maillons successifs (assertion sur la chaîne), altération d'un maillon puis re-validation (assertion d'échec). | S008 |
| CA-M6-22 | Tout enum du module (`VerdictResolutionPrix`, `VerdictReception`, `VerdictVarianceStock`) possède une valeur `INDETERMINE` comme échappatoire obligatoire (D-032). | Inspection des définitions d'enum : assertion de présence de `INDETERMINE` dans chacun. | S009 |
| CA-M6-23 | Le module n'appelle jamais `random` sans graine, jamais d'horloge interne (`time.time`, `datetime.now`), jamais de réseau (`socket`, `urllib`, `requests`), et ne porte aucun littéral numérique de coût en dur (les coûts viennent uniquement du catalogue fourni ou de l'historique du registre). | Analyse statique (AST) : absence d'appels interdits et absence de littéral numérique en position de coût dans le code du module. | S009 |
| CA-M6-24 | Le digest quotidien vers Nathan est déterministe (mêmes maillons et mêmes arguments produisent les mêmes octets) et sépare les variances significatives des suggestions de reorder. | Test unitaire : deux appels identiques (assertion d'égalité byte-à-byte) ; assertion que les deux listes du digest sont peuplées depuis des sources distinctes. | S009 |

---

## 7. STORIES

### S001 — Validation des entrées : WCT de M4, formulaire de consommation, clés interdites

| Attribut | Valeur |
|---|---|
| **Périmètre** | Validation structurelle du `WctRecu` (DOUZE clés exactes mesurées dans `m4_field_ops.outbox.CHAMPS_WCT`, sans jamais recalculer `hash_maillon`) et du `FormulaireConsommationMateriaux` qui le référence. Détection récursive des clés interdites sur toutes les entrées du module (WCT, formulaire, catalogue, PO, réception, comptage). |
| **Critères portés** | CA-M6-01, CA-M6-02, CA-M6-03 |
| **Tier** | T2 (contrat gelé externe consommé — frontière avec M4) |
| **Dépendances** | Aucune |

### S002 — Catalogue de matériaux et résolution de prix avec FALLBACK

| Attribut | Valeur |
|---|---|
| **Périmètre** | Résolution du coût unitaire d'un matériau : catalogue fourni en priorité, puis FALLBACK vers le dernier coût connu du registre append-only, puis blocage `INDETERMINE` si aucun des deux n'est exploitable. Aucune valeur codée en dur. |
| **Critères portés** | CA-M6-04, CA-M6-05, CA-M6-06 |
| **Tier** | T1 |
| **Dépendances** | S001 |

### S003 — Cycle bon de commande → réception, variance de réception

| Attribut | Valeur |
|---|---|
| **Périmètre** | Rapprochement des lignes demandées et reçues d'un bon de commande, classification du verdict de réception (conforme / inférieure / supérieure / mixte), calcul du montant total estimé avec l'équivalence null↔INDETERMINE. |
| **Critères portés** | CA-M6-07, CA-M6-08, CA-M6-09, CA-M6-10, CA-M6-11 |
| **Tier** | T1 |
| **Dépendances** | S002 |

### S004 — Stock localisé par chantier

| Attribut | Valeur |
|---|---|
| **Périmètre** | Tenue du stock par chantier : incrément à la réception, décrément à la consommation référençant un WCT valide. Rejet fail-closed de toute opération sans `chantier_id` ou dépassant le disponible. |
| **Critères portés** | CA-M6-12, CA-M6-13 |
| **Tier** | T1 |
| **Dépendances** | S003 |

### S005 — Variance d'inventaire sans accusation

| Attribut | Valeur |
|---|---|
| **Périmètre** | Comparaison du stock théorique (dérivé du registre) et d'un comptage physique déclaré. Verdict neutre (R-020) : aucun champ de cause ou de faute jamais rempli automatiquement. Échappatoire `INDETERMINE` quand aucun mouvement théorique préalable n'existe. |
| **Critères portés** | CA-M6-14, CA-M6-15, CA-M6-16 |
| **Tier** | T1 |
| **Dépendances** | S004 |

### S006 — Réapprovisionnement suggéré, jamais exécuté

| Attribut | Valeur |
|---|---|
| **Périmètre** | Émission d'un `SignalReorder` déterministe quand le stock localisé passe sous un seuil fourni par couple chantier/matériau. Garde structurelle : aucun chemin ne relie ce signal à la création automatique d'un bon de commande ou d'un paiement. |
| **Critères portés** | CA-M6-17, CA-M6-18 |
| **Tier** | T1 |
| **Dépendances** | S004 |

### S007 — Contrats de sortie séparés par destinataire (frontière de coût)

| Attribut | Valeur |
|---|---|
| **Périmètre** | Garantie structurelle que `ConfirmationConsommationTerrain` ne porte jamais de coût, et qu'aucun contrat de M6 ne porte de primitive de paiement. Test d'intégration bout en bout depuis le point d'entrée public (pas seulement des fonctions isolées). |
| **Critères portés** | CA-M6-19, CA-M6-20 |
| **Tier** | T2 (contrats gelés émis vers deux destinataires externes distincts — terrain et M5) |
| **Dépendances** | S003, S004 |

### S008 — Registre append-only hash-chaîné du stock

| Attribut | Valeur |
|---|---|
| **Périmètre** | Registre append-only des mouvements (réception, consommation, variance d'inventaire), hash-chaîné selon le patron déjà prouvé de M2/M3/M4 (copie-adaptation, décision #109). API : ajouter, lire, valider chaîne. |
| **Critères portés** | CA-M6-21 |
| **Tier** | T1 |
| **Dépendances** | S003, S004, S005 |

### S009 — Échappatoires D-032, conformité déterministe, digest quotidien

| Attribut | Valeur |
|---|---|
| **Périmètre** | Vérification transversale que tout enum porte `INDETERMINE`. Analyse statique (AST) : aucun appel interdit (random non ensemencé, horloge, réseau), aucun littéral de coût en dur. Digest quotidien déterministe des variances et des reorders vers Nathan. |
| **Critères portés** | CA-M6-22, CA-M6-23, CA-M6-24 |
| **Tier** | T1 |
| **Dépendances** | S001, S002, S003, S004, S005, S006, S007, S008 |

---

## 8. DÉCISIONS TRANSVERSALES APPLICABLES

| Décision | Application dans M6 |
|---|---|
| **D-032** — Échappatoire obligatoire sur tout enum | `VerdictResolutionPrix.INDETERMINE`, `VerdictReception.INDETERMINE`, `VerdictVarianceStock.INDETERMINE` |
| **D-015** — Contrats gelés = pactes exécutables | 14 schémas nommés (regroupés en 10 sous-sections thématiques, §5.1 à §5.10 — objection de revue scellée, Qwen3.8-Max : « dix contrats » comptait les sous-sections, pas les schémas ; §5.4/§5.5/§5.8 en définissent chacune plusieurs), chacun validé avant tout traitement |
| **R-020** — Aucune formulation accusatoire | Contrainte FONDATRICE de M6 (« variance sans accusation », « jamais vol automatique ») — appliquée à `VerdictVarianceStock` et à toute `raison`/`note_investigation` |
| **Loi 25** — Minimisation | M6 ne collecte que les identifiants et quantités nécessaires ; aucune donnée personnelle du fournisseur au-delà de ce que le catalogue exige |
| **Loi 96** — Français d'abord | Tous les verdicts et messages sont en français |
| **Décision #109** — Jamais d'import inter-modules | Le paquet `m6_material_control` réutilise le patron des modules voisins par copie-adaptation, jamais par import |
| **R-015** — Injection indirecte via courriels fournisseurs | Neutralisée nativement en v1 (zéro LLM, zéro réseau) ; repoussée GATED/T3 avec REG-13 obligatoire si activée |

---

## 9. PARAMÈTRES CONFIGURABLES

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `catalogue_materiaux` | Contrat gelé `CatalogueMateriaux` : version, unité, postes par matériau. | **Fourni par l'appelant à chaque résolution. Aucune valeur par défaut : un catalogue par défaut serait un coût inventé.** |
| `seuils_reorder` | Contrat gelé `SeuilReorder`, par couple chantier/matériau. | **Fourni par l'appelant. Absence = silence (pas de suggestion), jamais un seuil deviné.** |

---

## 10. FRONTIÈRES RATIFIÉES (rappel)

**M6 est la source de vérité unique pour les quantités de matériaux.** Aucun autre module ne
maintient sa propre copie faisant autorité du stock. M6 ne fixe jamais de prix de vente (M3), ne
planifie jamais de date (M4), ne paie jamais (M5), et ne désigne jamais une personne responsable
d'un écart (décision humaine, hors périmètre).
