# ARCHITECTURE — MODULE M6 (MATERIAL CONTROL OS)

Rédigé par : Architecte BMAD (subagent natif Claude Opus, revue dédiée) | Statut : PROPOSÉ | Date : 2026-08-02

---

## 0. CONSENSUS RATIFIÉ

Ordre d'implémentation ratifié (ADR-0003 Q2) : M7 → M1 → M2 → M4 → M3 → **M6** → M8 → M5 → M9. M3-estimation est livré (9 stories mergées) ; M4-field-ops est livré et sa sortie WCT est **mesurée**, pas supposée (voir §3.1).

Formules gelées reprises verbatim des contraintes non négociables du Brief (§2) et du PACK_CONSENSUS :

> Material Control OS : **variance sans accusation** (« jamais vol automatique ») ; **M6 ne paie jamais** ; **le terrain ne voit pas les coûts** ; **catalogue sourcé, sinon FALLBACK, jamais inventé** ; **stock localisé, jamais un pool global anonyme** ; **réapprovisionnement suggéré, jamais exécuté** ; **registre append-only hash-chaîné d'audit du stock**.

**Frontières ratifiées** (PRD §10) : **prix de vente = M3** (M6 ne le fixe jamais) ; **dates et planification = M4** (M6 ne planifie jamais) ; **paiement et facturation = M5** (M6 émet un montant à payer, jamais un règlement) ; **désignation d'un responsable d'écart = décision humaine** hors périmètre. **M6 est la source de vérité unique des quantités de matériaux** ; aucun autre module ne maintient de copie faisant autorité du stock. Contrairement à M3 qui ne porte aucune donnée financière, **M6 porte des coûts d'achat mais les cloisonne par audience** — c'est une frontière de contrat par destinataire, pas une frontière d'existence de la donnée.

**Décisions transversales applicables** :
- **D-032** — Sorties structurées, échappatoire `INDETERMINE` obligatoire sur tout enum (« un schéma sans issue force la fabrication »).
- **D-015** — Contrats gelés = pactes exécutables (14 schémas nommés, regroupés en 10 sous-sections thématiques §2.1 à §2.10).
- **R-020** — Aucune formulation accusatoire ; contrainte FONDATRICE de M6.
- **R-015** — Injection indirecte via courriels fournisseurs : neutralisée nativement en v1 (zéro LLM, zéro réseau), repoussée GATED/T3 avec REG-13 obligatoire.
- **Loi 25** — Minimisation ; **Loi 96** — Français d'abord.
- **Décision #109** — Jamais d'import inter-modules : réutilisation du patron des modules voisins par **copie-adaptation** seulement.

---

## 1. PAQUET `m6_material_control` — MODULES INTERNES

Le paquet est autonome. Il réutilise le patron prouvé de M2/M3/M4 par **copie-adaptation** de fichiers sources, jamais par import inter-modules (#109). L'identité de paquet (`__init__.py`) est indispensable : plusieurs modules du dépôt exposent des fichiers de même nom (`contrats`, `verdicts`, `registre`, `digest`, `conformite`) et, sans identité propre, `sys.modules` ferait exercer aux tests de M6 le code d'un voisin en silence (piège mesuré et documenté dans `m3_estimation/__init__.py`).

M6 porte QUATRE parcours d'écriture distincts, là où M3 et M4 n'en portent qu'un ; la découpe ci-dessous isole chaque frontière testable **et** un unique point d'écriture par type de mouvement (voir DA-M6-11).

| Fichier | Responsabilité | Justification |
|---|---|---|
| `__init__.py` | Identité de paquet ; aucun ré-export. Les quatre fonctions publiques sont importées par leur nom pleinement qualifié `m6_material_control.materiel.<fn>`. | Reproduit le patron mesuré de `m3_estimation/__init__.py` : l'identité de paquet empêche la collision `sys.modules` (#109). |
| `contrats.py` | Constantes de contrat gelées : les tuples de clés `CHAMPS_*` des 14 schémas nommés (§2), les trois énumérés fermés (`VERDICTS_RESOLUTION_PRIX`, `VERDICTS_RECEPTION`, `VERDICTS_VARIANCE_STOCK`) avec dérivation indicée des noms canoniques et `*_INDETERMINE`, les DEUX ensembles de clés interdites (§DA-M6-03), `CHAMPS_WCT_ATTENDUS` (copie épinglée des 12 clés de M4) et `CONSOMMATEURS_ATTENDU = "M6"`. | D-015 : les contrats gelés sont figés dans un fichier dédié. Mirroring exact de `m3_estimation/contrats.py` (noms de verdicts dérivés par indice, jamais réécrits en littéral, pour qu'une faute de frappe soit une erreur d'import et non un bug de chemin). |
| `verdicts.py` | Catalogue fermé des codes `REJ-*` et `construire_verdict(code, detail=…)`. | Copie-adaptation de `m4_field_ops/verdicts.py` : un verdict nommé et distinct par classe de faute (exigé par CA-M6-01/02/03). |
| `encodage.py` | `encoder_canonique(*valeurs)` (normalisation récursive typée, JSON déterministe, préfixage par longueur) et `empreinte(*valeurs)` = sha256 de la forme canonique. | Copie-adaptation de `m4_field_ops/encodage.py` : injectivité par préfixage de longueur, refus des types non sérialisables (jamais `repr()` dont l'adresse mémoire briserait la reproductibilité). Sert `hash_maillon` et `hash_digest`. |
| `frontieres.py` | Scan récursif des clés interdites GLOBALES (dict/list/tuple), normalisation de clé (minuscule, NFD sans diacritiques, espaces/tirets → underscore), verdict `REJ-FRONTIERE-VIOLEE`. | Copie-adaptation de `m4_field_ops/frontieres.py`. Porte l'ensemble #1 (§DA-M6-03) : paiement, date, prix de vente — clés d'un AUTRE domaine, interdites partout. |
| `validation.py` | Validation structurelle de toutes les entrées : `WctRecu` (12 clés exactes, `"M6"` ∈ `consommateurs_cibles`, **sans recalcul de `hash_maillon`**), `FormulaireConsommationMateriaux`, `CatalogueMateriaux`, `BonDeCommandeDemande`, `ReceptionPO`, `ComptageInventaire`, `SeuilReorder`. Ordre épinglé, première faute gagnante, frontières vérifiées EN PREMIER. | Reproduit l'ordre mesuré de `m4_field_ops.contrats.valider_entree` (frontière → structure → correspondance). Un contrat gelé sans propriétaire de validation est une promesse que personne ne tient. |
| `catalogue.py` | Résolution du coût unitaire d'un matériau : `PRIX_CATALOGUE` → `PRIX_HISTORIQUE_FALLBACK` (ordre du registre) → `INDETERMINE`. Fonction pure sur `(materiau_id, catalogue, registre)`. | Isolé pour éprouver la garde anti-invention seule (§DA-M6-10). Aucune valeur codée en dur : patron du barème-entrée de M3 (`DA-M3-09`). |
| `fournisseurs.py` (PLAN T2.5) | Registre des fournisseurs (M6.2) : identité et coordonnées SEULEMENT (`enregistrer_fournisseur`, idempotent/correctible, `lire_fournisseur`, `lister_fournisseurs`). Son propre registre nommé (`opsys.stockage.maillons(dept, "fournisseurs")`), distinct du registre de mouvements. | Corrige le trou mesuré par l'audit M6 (« `BonDeCommandeDemande` n'a aucun champ fournisseur ») : `bons_commande.creer_brouillon` exige un `fournisseur_id` déjà enregistré ici. |
| `livre_prix.py` (PLAN T2.4) | Livre de prix (M6.3) : prix FOURNIS (jamais inventés), versionnés (append-only), datés, PAR FOURNISSEUR (`enregistrer_prix`, `prix_en_vigueur`, `resoudre_prix_po`). Sélection du prix « en vigueur » par ORDRE D'ÉCRITURE, jamais par comparaison de `date_effet` (même raisonnement que DA-M6-10). Distinct de `catalogue.py` (résolution à la RÉCEPTION, inchangée). | Le prix d'une ligne de PO vient de ce livre EN VIGUEUR ou d'un verdict qui le demande (`PRIX_LIVRE`/`INDETERMINE`, jamais un prix par défaut) — lu par `bons_commande.creer_brouillon`. |
| `besoins_materiaux_recus.py` (PLAN T2.3-e) | Réception du contrat `BesoinsMateriauxM3` émis par M3 (§2.12) : validation du RÉCEPTEUR, indépendante de celle de l'émetteur (frontières, clés fermées, décimaux ASCII stricts, doublons, signal des pertes absentes), et dérivation du prévu au format interne (`lignes_prevues`, `lignes_detaillees`). Copie épinglée des clés du contrat, jamais un import (#109). | M6 ne croit pas un contrat parce que le producteur est M3 : un contrat invalide est refusé en quarantaine, jamais rangé. Module pur ; l'adaptateur `outils.py::_recevoir_besoins_materiaux` fait les entrées-sorties. |
| `besoins_prevus.py` (PLAN T1.2-b, T2.3-e) | Le prévu d'un devis, dans SON registre durable (`besoins_prevus`), distinct du registre de mouvements : prévu DÉFINITIF (devis accepté ou outil manuel, un seul par devis) et prévu PROVISOIRE (version d'estimation M3, `enregistrer_estimation`, source `estimation_m3`). `pour_devis` préfère le définitif, sinon la version d'estimation la plus récente. | Voir DA-M6-16 : le prévu reste UNE notion pour tous ses lecteurs (déclaration de matériaux, variance, PO) ; l'estimation n'en crée pas un second. |
| `bons_commande.py` (DA-M6-12 révisée, PLAN T2.5) | Moteur de PO PERSISTÉ (M6.5) : `creer_brouillon` (besoins prévus + écart de stock, prix résolu par ligne via `livre_prix.py`), `approuver` (refuse fail-closed si un prix reste `INDETERMINE`), `generer_courriel` (M6.6, texte seul), `marquer_envoye` (N4, aucune primitive d'envoi), `enregistrer_reception_po` (attache le verdict déjà calculé par `reception.py`, inchangé), `detecter_ecarts_prix` (M6.7, signal vers M5/M8). Machine à 12 statuts en table figée (`contrats.TRANSITIONS_PO`), même patron append-only que `m3_estimation.devis_durable` (aucun hash-chaînage, copie-adaptation #109). | Voir DA-M6-12 révisée ci-dessous : le type de maillon `PO_DEMANDE` n'existe toujours PAS dans l'énuméré gelé du registre de stock (§2.10) — le PO vit dans SA PROPRE collection nommée, jamais dans le registre de mouvements. |
| `reception.py` | Rapprochement lignes demandées ↔ reçues, classification `VerdictReception` (conforme / inférieure / supérieure / **mixte** / indéterminé), coût par ligne via `catalogue.py`, `montant_ligne` et `montant_total_estime` avec équivalence stricte null↔INDETERMINE. Construit `AccuseReceptionPO` et, si résolu, `SignalPoAPayer`. Logique PURE (aucune écriture). | Isolé de l'orchestrateur pour tester le verdict et l'équivalence null sans traverser une écriture de registre (leçon #166 et « tester les renderers isolément masque le chemin réel » — d'où AUSSI un test bout en bout en S007). |
| `stock.py` | Dérivation PURE du stock théorique d'un couple `(chantier_id, materiau_id)` : somme signée des `quantite` des maillons `RECEPTION` et `CONSOMMATION` jusqu'à la tête, **`VARIANCE_INVENTAIRE` exclue** (§DA-M6-09). Vérification de disponibilité pour la consommation, avec cumul des lignes d'un même matériau. Aucun cache. | « Pas d'état caché, tout dérivé du registre » — patron mesuré de `m4_field_ops.outbox.calculer_duree_reelle`/`statut_courant` qui re-dérivent à chaque appel. Un cache serait une seconde vérité divergente. |
| `variance.py` | Comparaison stock théorique (via `stock.py`) ↔ comptage déclaré, classification `VerdictVarianceStock` neutre (R-020), `INDETERMINE` si aucun mouvement préalable. Construit `SignalVarianceStock` avec `note_investigation = null` par construction. | Isolé pour prouver qu'AUCUNE fonction de calcul ne remplit un champ de cause (CA-M6-15, inspection statique). |
| `reorder.py` | Après un mouvement, comparaison du stock localisé résultant au seuil fourni ; émission `SignalReorder` avec `quantite_suggeree = seuil - stock` ; **silence** si aucun seuil fourni pour le couple. | Isolé pour éprouver la contrainte de silence ET la garde AST « aucun chemin ne relie ce signal à la création d'un PO ou à un paiement » (CA-M6-18, §DA-M6-13). |
| `contrats_sortie.py` | Assemblage des contrats de sortie PAR DESTINATAIRE et **garde terrain** : `ConfirmationConsommationTerrain` scannée contre l'ensemble de clés de coût #2 (§DA-M6-03) avant émission. | La séparation par audience est la spécificité de M6. Garde isolée ici ET éprouvée bout en bout depuis `materiel.py` en S007 (un test de fonction isolée masquerait un assemblage réel différent). |
| `registre.py` | Journal append-only hash-chaîné des `MaillonMateriel` (§2.10). API : `ajouter(mouvement)`, `ajouter_lot(mouvements)` **atomique tout-ou-rien** (§DA-M6-08), `lire()`, `hash_tete()`, `valider_chaine()`. | Copie-adaptation de `m3_estimation/registre.py` et `m4_field_ops/registre.py`, avec les champs gelés `index`/`hash_precedent`/`hash_maillon`. `ajouter_lot` est l'extension qui rend l'atomicité multi-lignes une propriété du registre, pas une convention. |
| `digest.py` | Digest quotidien déterministe vers Nathan : variances depuis les maillons `VARIANCE_INVENTAIRE`, reorders RECALCULÉS depuis le stock dérivé vs seuils fournis ; `hash_digest = empreinte(contenu canonique)`. Horodatages reproduits tels quels. | Copie-adaptation de `m3_estimation/digest.py` : « mêmes maillons + mêmes arguments → mêmes octets », sans normaliser les chaînes d'entrée (le module ne répare rien). |
| `conformite.py` | Contrôle statique AST transversal : chaque énuméré de domaine porte `INDETERMINE` ; aucun appel `random` non ensemencé / horloge / réseau ; aucun littéral numérique en contexte de coût ; **garde de non-recalcul du hash WCT** ; **garde d'écriture unique par type de mouvement** ; **garde reorder ⊘ PO/paiement**. | Copie-adaptation de `m3_estimation/conformite.py` (dont `_contexte_monetaire` détecte déjà `cout`/`montant`) fusionnée avec le patron `m4_field_ops.outbox.garde_ecriture_unique`. |
| `materiel.py` | **Orchestrateur unique**, quatre fonctions publiques : `enregistrer_reception`, `consommer_materiaux`, `soumettre_comptage`, `produire_digest_quotidien`. Chaque écriture : valider → dériver → décider → construire le contrat → **écriture atomique** → réévaluer le reorder. | Un seul orchestrateur garantit que l'ordre des étapes ne peut être altéré et qu'un type de mouvement n'a qu'un point d'écriture (§DA-M6-11), gardé par `conformite.py` — patron de `m4_field_ops.outbox.completer_intervention`. |

---

## 2. SCHÉMAS DE DONNÉES

Les 14 schémas nommés ci-dessous (regroupés en 10 sous-sections thématiques — §5.4, §5.5 et §5.8 du PRD en définissent chacune plusieurs, objection de revue scellée Qwen3.8-Max fondée : « dix contrats » comptait les sous-sections, pas les schémas) sont reproduits **fidèlement** du PRD §5 (le PRD fait foi) ; les annotations d'architecte n'ajoutent aucune clé. Aucun contrat ne porte de date d'intervention, de créneau, de durée d'exécution, ni de primitive de paiement.

### 2.1 Entrée reçue de M4 — `WctRecu` (mesuré, pas supposé)

Copie exacte des DOUZE clés de `CHAMPS_WCT` dans `m4_field_ops/outbox.py:26-30` :

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

M6 valide la présence EXACTE de ces douze clés (aucune de plus, aucune de moins) et que `"M6"` figure dans `consommateurs_cibles`. **M6 ne recalcule JAMAIS `hash_maillon`** — il ne possède pas le registre de M4, exactement comme M3 ne recalcule jamais l'empreinte du marqueur de M2.

> **Précision de portée (objection de revue scellée, Qwen3.8-Max, fondée)** : `duree_reelle_minutes` est une INFORMATION que M4 calcule et transporte, jamais une décision de M6 — M6 ne la modifie pas, ne la recalcule pas, ne l'utilise jamais pour planifier quoi que ce soit. La frontière « M6 ne planifie jamais, aucun contrat émis ne porte de durée » (PRD §5, DA-M6-03) vise les contrats ÉMIS par M6, pas ce champ reçu tel quel d'un module amont dont M6 ne possède pas le schéma.

> **Mesure directe (issue #166 évitée)** : `CONSOMMATEURS_CIBLES = ("M6", "M5", "M2", "M7", "M8", "M10")` — `"M6"` est bien présent (`outbox.py:24`). Le WCT ne porte AUCUN champ de matériaux : le « formulaire matériaux » est un artefact SÉPARÉ (§2.2) que M6 définit et reçoit, référençant le `wct_id`. `devis_id` est émis **`None` en dur** par M4 (`outbox.py:205`, commentaire « M3 n'existe pas en v1 » désormais périmé mais non recâblé dans la source mesurée) : M6 traite donc `devis_id` comme structurellement `str | null` et n'exige **jamais** une valeur non nulle — supposer un `devis_id` renseigné reproduirait exactement le contrat fantôme #166.

### 2.2 Entrée — `FormulaireConsommationMateriaux` (fourni par l'appelant, référence le WCT)

```yaml
FormulaireConsommationMateriaux:
  wct_id: str              # doit correspondre à un WctRecu structurellement valide fourni à l'appel
  intervention_id: str     # doit correspondre au WctRecu référencé
  chantier_id: str
  lignes_consommees:
    - materiau_id: str
      quantite: float       # > 0
```

### 2.3 Entrée — `CatalogueMateriaux` (fourni par l'appelant, jamais codé en dur)

```yaml
CatalogueMateriaux:
  version: str
  unite_monetaire: str
  postes:
    <materiau_id>:
      cout_unitaire: float   # > 0
      libelle: str
```

Validation fail-closed : catalogue absent, `postes` vide ou malformé → tout matériau demandé passe directement en résolution FALLBACK/`INDETERMINE`, jamais en erreur bloquante globale (le catalogue peut être partiel par design, comme `BaremeCouts` de M3).

### 2.4 Entrée — `BonDeCommandeDemande` et `ReceptionPO`

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

### 2.5 Entrée — `ComptageInventaire` et `SeuilReorder`

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

### 2.6 Sortie — `AccuseReceptionPO` (destination admin — porte les coûts)

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

### 2.7 Sortie — `ConfirmationConsommationTerrain` (destination technicien — SANS coût)

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

**Aucune clé de coût, à aucun niveau** : ni `cout_unitaire`, ni `cout`, ni `prix`, ni `montant`, ni `devise`, ni `unite_monetaire`, ni `montant_total_estime`. Garde vérifiée par inspection du schéma ET par test d'intégration depuis le point d'entrée public `materiel.consommer_materiaux` (un test qui n'exerce que des fonctions isolées peut masquer un chemin réel qui assemble le contrat différemment — leçon retenue en S007).

### 2.8 Sortie — `SignalReorder`, `SignalVarianceStock`, `SignalPoAPayer`

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
    # résolu par PRIX_HISTORIQUE_FALLBACK (aucun catalogue fourni à cet appel) — le
    # montant EST résolu (le signal est bien émis) alors qu'aucune version de catalogue
    # n'existe à tracer. Même équivalence que bareme_version dans AccuseReceptionPO
    # (§2.6) : null SI ET SEULEMENT SI aucun catalogue n'a été fourni à cet appel,
    # jamais parce que le montant serait indéterminé (ce cas n'émet aucun signal).
  hash_maillon: str
```

**Aucun de ces trois contrats ne porte** : `statut_paiement`, `virement`, `reference_bancaire`, `mode_paiement` — M6 émet un montant à payer, jamais un ordre ni un statut de règlement.

### 2.9 Sortie — `DigestMaterielQuotidien` (destination Nathan)

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

> Note d'architecte (sans modifier le contrat) : en v1, `variances_significatives` == **toutes** les variances de la fenêtre — aucun seuil de bruit n'existe (PRD §0.2). Le seuil de filtrage est un paramètre de roadmap, activable sans réécriture grâce au registre append-only.

### 2.10 Maillon du registre append-only — `MaillonMateriel`

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

**Champs absents par design** (frontières M6) : aucun prix de vente client (M3) ; aucune date d'intervention, créneau, ou durée (M4) ; aucune primitive de paiement (M5). **Convention `hash_precedent`** : le contrat gelé impose **chaîne vide** à `index 0` — reproduit tel quel (les voisins divergent — M3 utilise 64 zéros, M4 utilise `None` — mais le pacte M6 fait foi et n'est pas réaligné ici).

> **Limite de traçabilité, déclarée** : le schéma gelé ne porte ni `wct_id` ni `intervention_id` dans le maillon `CONSOMMATION`. Le lien intervention→mouvement vit dans `ConfirmationConsommationTerrain` (qui porte `intervention_id`), jamais dans le registre. Croiser un maillon avec son WCT depuis le seul registre est donc **hors périmètre v1** (ajout de clé = roadmap, sans réécriture grâce à l'append-only). Le signaler ici évite qu'une revue le prenne pour un oubli.

### 2.11 Énumérés fermés (copie mot pour mot du PRD §4)

Chaque énuméré porte `INDETERMINE` comme échappatoire D-032 obligatoire (garde AST, `conformite.py`).

#### `VerdictResolutionPrix`

| Valeur | Condition d'obtention |
|---|---|
| `PRIX_CATALOGUE` | Le matériau figure dans le `CatalogueMateriaux` fourni à cet appel. |
| `PRIX_HISTORIQUE_FALLBACK` | Absent du catalogue fourni ; le registre porte au moins un mouvement antérieur pour ce matériau avec un `cout_unitaire` non nul — le PLUS RÉCENT **par ordre du registre** est utilisé. |
| `INDETERMINE` | **Échappatoire D-032** — ni le catalogue ni l'historique n'ont de donnée exploitable. La ligne est bloquée : `cout_unitaire_resolu = null`. |

#### `VerdictReception`

| Valeur | Condition d'obtention |
|---|---|
| `CONFORME` | Chaque ligne du PO a une quantité reçue égale à la quantité demandée. |
| `RECEPTION_INFERIEURE` | Au moins une ligne strictement inférieure, aucune supérieure. |
| `RECEPTION_SUPERIEURE` | Au moins une ligne strictement supérieure, aucune inférieure. |
| `RECEPTION_MIXTE` | Coexistence de lignes inférieures ET supérieures — jamais fusionné dans un des deux verdicts précédents. |
| `INDETERMINE` | **Échappatoire D-032** — PO introuvable, ou lignes non appariables aux lignes demandées. |

#### `VerdictVarianceStock`

| Valeur | Condition d'obtention |
|---|---|
| `AUCUN_ECART` | Quantité comptée égale à la quantité théorique. |
| `STOCK_INFERIEUR_AU_THEORIQUE` | Comptée strictement inférieure. Constat chiffré, AUCUNE cause attribuée (R-020). |
| `STOCK_SUPERIEUR_AU_THEORIQUE` | Comptée strictement supérieure. Constat chiffré, AUCUNE cause attribuée (R-020). |
| `INDETERMINE` | **Échappatoire D-032** — aucun mouvement théorique préalable pour ce couple (rien à comparer ; comparer contre zéro fabriquerait un écart). |

### 2.12 Entrée reçue de M3 — `BesoinsMateriauxM3` (PLAN T2.3-e)

Le contrat est DÉFINI par son émetteur (M3, `03-ARCHITECTURE.md` de M3 §2.9, qui en est propriétaire) :
huit clés au premier niveau (`devis_id`, `lead_id`, `estimation_id`, `rang_registre`, `bareme_version`,
`niveau_confiance`, `lignes`, `facteurs_perte_absents`) ; par ligne, `materiau`, `quantite_estimee`
et `unite` requis, `sku` et `facteur_perte` optionnels. M6 en porte une COPIE ÉPINGLÉE
(`besoins_materiaux_recus.py`, jamais un import, #109), que le gate de cohérence de M3 confronte à
l'architecture, à la source de l'émetteur et au schéma du catalogue du bus (`m3.besoins_materiaux`).

M6 reçoit des quantités NETTES, en texte décimal, et un facteur de perte OPTIONNEL par ligne. **M6 ne
reçoit aucun prix ni coût de M3** : il a son propre livre de prix (§1, `livre_prix.py`). Le validateur
refuse à toute profondeur les clés de prix, de coût, de marge et l'intervalle de coût de l'estimation,
avant même la structure ; un `facteur_perte` absent est déclaré par M3 dans `facteurs_perte_absents`,
et M6 vérifie que cette liste est exactement celle des lignes sans facteur — une absence n'est jamais
tue, jamais remplacée par zéro.

L'identifiant d'un matériau pour M6 est le `sku` quand M3 le connaît, sinon la désignation de M3 : l'une
des deux valeurs reçues, jamais une valeur devinée. Deux lignes de même identité sont refusées (agréger
en silence inventerait une quantité). M6 ne tient pas de catalogue persisté : il ne peut pas vérifier
qu'un `sku` reçu existe (limite déclarée ; l'enrichissement du catalogue est M6.1).

---

## 3. INTERFACES ET CONTRATS

### 3.1 Ce que M6 reçoit de M4 (mesuré)

Deux artefacts distincts, jamais fusionnés : le **`WctRecu`** (12 clés, §2.1) et le **`FormulaireConsommationMateriaux`** qui le référence par `wct_id` (§2.2). M6 valide le WCT **structurellement** : 12 clés exactes, `"M6"` ∈ `consommateurs_cibles`, sans recalculer `hash_maillon`. **Limite déclarée** : M6 ne possède pas le registre de M4 ; la vérification cryptographique de bout en bout appartient à la couche d'intégration qui détient les deux arbres — M4 procède exactement ainsi vis-à-vis de son amont, M6 ne prétend pas mieux. Un formulaire dont le `wct_id` ne correspond à aucun `WctRecu` valide fourni à l'appel est rejeté par un verdict **nommé**, distinct du rejet de schéma générique (CA-M6-02).

### 3.2 Ce que M6 reçoit de l'appelant (répartiteur/admin)

`CatalogueMateriaux`, `BonDeCommandeDemande`, `ReceptionPO`, `ComptageInventaire`, `SeuilReorder` — toutes fournies, jamais devinées. Le `BonDeCommandeDemande` est passé **à l'appel de réception** (M6 ne persiste pas les PO, §DA-M6-12).

### 3.3 Ce que M6 émet vers l'admin

`AccuseReceptionPO` (avec coûts et verdict de réception, §2.6).

### 3.4 Ce que M6 émet vers le terrain

`ConfirmationConsommationTerrain` — quantités seulement, **aucun coût** (§2.7), garde `contrats_sortie.py` + test bout en bout.

### 3.5 Ce que M6 émet vers M5

`SignalPoAPayer` en lecture seule — un signal par PO réceptionné, **jamais** si le montant serait `INDETERMINE`. M5 décide et exécute seul le règlement, exactement comme M4 émet un WCT vers M5 sans facturer lui-même.

### 3.6 Ce que M6 émet vers l'admin/répartiteur

`SignalReorder` (suggestion, jamais un achat) et `SignalVarianceStock` (constat neutre).

### 3.7 Ce que M6 émet vers Nathan

`DigestMaterielQuotidien` quotidien, déterministe, hash-chaîné (§2.9).

### 3.8 État interne faisant autorité

Le registre append-only de `MaillonMateriel` (§2.10) est la **source de vérité unique des quantités**. Le stock théorique en est une **dérivation pure** (§DA-M6-09), jamais un compteur maintenu à part.

### 3.9 Ce que M6 reçoit de M3 — les besoins d'une estimation

Sur le bus, `m3.besoins_materiaux` (§2.12), avant le devis et avant son acceptation. M6 valide, range le
prévu PROVISOIRE du devis dans son registre des besoins prévus (DA-M6-16), et ne fait rien d'autre :
**aucun bon de commande n'est créé, aucun stock n'est réservé, aucun mouvement n'est écrit**. Un PO reste
un brouillon calculé à la demande (`m6_creer_po_brouillon`), soumis à approbation (DA-M6-12 révisée). Un
contrat invalide lève une erreur : le répartiteur réessaie puis le met en quarantaine (ADR-0009 §3).

---

## 4. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-M6-01 — Déterminisme total (zéro horloge, zéro aléa non ensemencé, zéro réseau)

**Décision** : Aucun module de M6 n'appelle `time.time`, `datetime.now`/`today`/`utcnow`, `random` sans graine, `uuid`, `secrets`, `os.urandom`, ni aucune primitive réseau (`socket`, `urllib`, `requests`, `http.client`). Tout horodatage provient des contrats d'entrée, reproduit tel quel.

**Justification** : Reproductibilité bit-à-bit exigée en CI (CA-M6-23, CA-M6-24). Garde par `conformite.py`, copie-adaptation de `m3_estimation/conformite.py` dont l'analyse AST couvre déjà ces quatre familles.

### DA-M6-02 — Fail-closed sur le stock

**Décision** : Toute opération sans `chantier_id` est rejetée. Une consommation dont la quantité (cumulée par matériau au sein du formulaire) excède le stock localisé disponible est rejetée par un verdict nommé ; le stock ne devient **jamais** négatif silencieusement (CA-M6-12, CA-M6-13).

**Justification** : Un stock négatif silencieux serait une donnée fabriquée, invérifiable en aval. Le fail-closed est l'homologue de la garde anti-précision-inventée de M3.

### DA-M6-03 — Deux frontières de clés : par domaine (globale) ET par destinataire (terrain)

**Décision** : M6 maintient **DEUX** ensembles de clés interdites, appliqués à des portées différentes.
- **Ensemble #1 — frontière de domaine, scannée récursivement sur TOUTES les entrées ET toutes les sorties** (`frontieres.py`) : `statut_paiement`, `virement`, `reference_bancaire`, `mode_paiement`, `prix_vente`, `date_execution`, `creneau`, `duree`. Ce sont des clés d'un AUTRE domaine (M5, M3, M4) : M6 ne les porte nulle part.
- **Ensemble #2 — frontière de destinataire, scannée sur le SEUL `ConfirmationConsommationTerrain`** (`contrats_sortie.py`) : `cout_unitaire`, `cout`, `prix`, `montant`, `devise`, `unite_monetaire`, `montant_total_estime`. Ces coûts EXISTENT légitimement ailleurs dans M6 (`AccuseReceptionPO`, `SignalPoAPayer`, `MaillonMateriel`) mais ne doivent jamais atteindre le technicien.

Toute clé de l'ensemble #1 présente à n'importe quel niveau provoque un rejet **explicite et distinct** du rejet de schéma générique (CA-M6-03). Toute clé de l'ensemble #2 dans le contrat terrain est un défaut de garde (CA-M6-19).

**Justification** : C'est LA spécificité de M6 face à M3. M3 ne porte aucune finance et interdit donc les coûts partout ; M6 porte des coûts d'achat mais les **cloisonne par audience** (brief §2.3). Un ensemble unique et global interdirait à `AccuseReceptionPO` de porter ses propres coûts — faux. Séparer les deux ensembles rend chaque frontière prouvable seule et évite un test vert pour la mauvaise raison.

### DA-M6-04 — Échappatoire `INDETERMINE` obligatoire sur les trois enums (D-032)

**Décision** : `VerdictResolutionPrix`, `VerdictReception`, `VerdictVarianceStock` portent chacun `INDETERMINE`. Quand la donnée ne permet aucune classification, M6 choisit `INDETERMINE` plutôt qu'une valeur optimiste (prix à zéro, écart contre zéro, réception forcée dans un signe).

**Justification** : D-032. Garde AST dans `conformite.py` (patron mesuré : `m3_estimation/conformite.py` vérifie la présence de l'échappatoire dans chaque énuméré de domaine).

### DA-M6-05 — Copie-adaptation, jamais d'import inter-modules (#109), avec gate de non-dérive du WCT

**Décision** : `encodage.py`, `registre.py`, `frontieres.py`, `verdicts.py`, `conformite.py`, `digest.py` sont des **copies-adaptations** des fichiers homonymes de M2/M3/M4, jamais des imports. `CHAMPS_WCT_ATTENDUS` (les 12 clés) et `CONSOMMATEURS_ATTENDU = "M6"` sont **copiés-épinglés** dans `contrats.py`, confrontés en CI à la source `m4_field_ops.outbox.CHAMPS_WCT` / `CONSOMMATEURS_CIBLES` par un **gate de non-dérive**.

**Justification** : #109 protège le CODE DE PRODUCTION du couplage ; un GATE, lui, DOIT confronter un consommateur à son producteur — s'en priver a laissé passer un contrat fantôme pendant tout un cadrage (issue #166, principe DA-M3-10). Le gate est fail-closed : source absente ou constante renommée font ROUGIR, jamais passer en silence.

### DA-M6-06 — Le `hash_maillon` du WCT n'est JAMAIS recalculé

**Décision** : Aucune fonction de M6 ne passe le WCT (ni ses champs) à `empreinte()`/`encoder_canonique()` dans un but de recalcul de son `hash_maillon`. Garde AST dédiée dans `conformite.py`.

**Justification** : M6 ne possède pas le registre de M4 — il n'a pas les entrées du calcul (parallèle exact de M3 vis-à-vis du marqueur de M2, DA-M3-11). Le non-recalcul n'est pas une facilité, c'est une **impossibilité** ; la garde la rend éprouvable (CA-M6-01).

### DA-M6-07 — Verdicts non accusatoires, `note_investigation` jamais auto-remplie (R-020)

**Décision** : Un écart est un CONSTAT chiffré. Aucune fonction de calcul de `variance.py` ne référence ni ne remplit un champ de « cause » ou de « faute ». `note_investigation` naît `null` et ne peut être renseignée que par un appel humain explicite, distinct de tout calcul de variance.

**Justification** : R-020, contrainte fondatrice (« jamais vol automatique »). Un module qui affirme plus que ses données ne permettent produit un dommage réputationnel et humain. Inspection statique en CA-M6-15.

### DA-M6-08 — Atomicité tout-ou-rien des opérations multi-lignes

**Décision** : Une `ReceptionPO` et un `FormulaireConsommationMateriaux` multi-lignes sont traités **tout-ou-rien**. L'orchestrateur valide TOUTES les lignes et dérive l'état résultant de TOUTES contre un **unique instantané** du stock dérivé, AVANT toute écriture ; si une seule ligne échoue, ZÉRO maillon n'est écrit et un verdict de rejet nommé est retourné. L'écriture effective passe par `registre.ajouter_lot(mouvements)`, primitive **atomique** (valide tout, chaîne tout, recalcule l'empreinte globale une fois ; échec = rien d'ajouté). Deux lignes d'un même matériau sont contrôlées contre le **tirage cumulé**, jamais chacune contre le stock plein.

Précisions par parcours :
- **Consommation** : une ligne dont la quantité (cumulée par matériau) dépasse le disponible, ou ≤ 0, fait rejeter l'opération ENTIÈRE.
- **Réception** : le rejet tout-ou-rien porte sur la **validité structurelle** du couple PO↔réception (po_id/chantier_id appariables). Un prix `INDETERMINE` par ligne ne bloque **pas** l'entrée physique en stock — il annule seulement `montant_ligne`/`montant_total_estime` et supprime le `SignalPoAPayer`. Une réception est toujours additive : elle ne peut jamais échouer sur « stock insuffisant ».

**Justification** : Le maillon composite de M4 est écrit en « exactement UN appel à ajouter » (`outbox.py:208-211`) — atomique par construction. Une application partielle laisserait le registre dans un état qu'aucune entrée unique n'a produit, donc **inauditable**, et corromprait la dérivation pure du stock (DA-M6-09) ; le `stock_restant` renvoyé au technicien refléterait alors un sous-ensemble arbitraire des lignes. « Valider toutes les clés avant la 1re écriture, sinon fichier à moitié corrigé et vert » — leçon `applicateur-refuse-en-bloc` appliquée aux mouvements.

### DA-M6-09 — Stock théorique = dérivation pure du registre, sans cache, variance exclue

**Décision** : Le stock théorique d'un couple `(chantier_id, materiau_id)` à la tête du registre est la **somme signée des `quantite`** des maillons `RECEPTION` (positifs) et `CONSOMMATION` (négatifs) pour ce couple. Les maillons `VARIANCE_INVENTAIRE` sont **exclus** de cette somme. Aucun cache : la dérivation est recalculée à chaque appel (`stock.py`).

**Justification** : « Pas d'état caché, tout dérivé du registre » — patron mesuré de M4 (`calculer_duree_reelle`, `statut_courant` re-dérivent à chaque appel). Un cache serait une seconde vérité divergente. **Exclusion de la variance** : le PRD définit le théorique comme « somme des réceptions moins les consommations » (§2.3) — une variance est un **constat**, pas une correction du livre. L'inclure ferait « corriger » silencieusement le stock, et le comptage suivant afficherait faussement `AUCUN_ECART`. **Conséquence assumée et honnête** : après une perte physique, le théorique reste supérieur au réel et chaque inventaire re-signale `STOCK_INFERIEUR` — jusqu'à une écriture d'ajustement décidée par un humain (hors périmètre v1, R-020). Le `quantite` d'un maillon `VARIANCE_INVENTAIRE` enregistre l'écart signé (richesse d'audit) mais n'entre jamais dans la dérivation. Coût O(n) par requête accepté : la correction prime sur la performance en v1 ; un index est une optimisation de roadmap si la mesure l'exige.

### DA-M6-10 — Dernier prix connu par ORDRE du registre, jamais par horodatage comparé

**Décision** : Le FALLBACK retient le `cout_unitaire` du maillon `RECEPTION` de `materiau_id` ayant l'`index` le **plus élevé** (le dernier ajouté) parmi ceux à `cout_unitaire` non nul — jamais par comparaison d'un champ horodatage. Le scan est **global inter-chantiers** : le prix est une propriété du matériau/fournisseur, pas du lieu. La résolution s'effectue AVANT l'écriture de la réception en cours (pour qu'une ligne ne se résolve jamais sur elle-même). Une égalité d'horodatage est sans effet, puisque l'horodatage n'est jamais l'axe de tri.

**Justification** : Le PRD l'exige (« le PLUS RÉCENT par ordre du registre », §4.1). L'`horodatage` est une chaîne libre fournie par l'appelant : deux réceptions peuvent porter des horodatages égaux ou dans le désordre, et M6 n'a **aucune horloge** pour arbitrer — trier dessus introduirait un ordre non déterministe et falsifiable. L'ordre d'écriture est l'unique autorité déterministe (mesuré : `m4_field_ops/outbox.py:92-95` — « l'ordre du registre est l'ordre d'écriture » ; `m3_estimation/registre.py` — `rang = len(maillons)`). Seuls les maillons `RECEPTION` portent un `cout_unitaire` non nul (§2.10), donc le scan les vise naturellement.

### DA-M6-11 — Un point d'écriture unique par TYPE de mouvement, orchestrateur unique

**Décision** : `materiel.py` est l'**unique** orchestrateur, avec quatre fonctions publiques :
- `enregistrer_reception(bon_demande, reception, catalogue, registre, seuils=…)` → écrit N maillons `RECEPTION`, renvoie `AccuseReceptionPO` (+ éventuel `SignalPoAPayer`, + éventuels `SignalReorder`).
- `consommer_materiaux(wct, formulaire, registre, seuils=…)` → écrit N maillons `CONSOMMATION`, renvoie `ConfirmationConsommationTerrain` (+ éventuels `SignalReorder`).
- `soumettre_comptage(comptage, registre)` → écrit 1 maillon `VARIANCE_INVENTAIRE`, renvoie `SignalVarianceStock`.
- `produire_digest_quotidien(registre, seuils, fenetre…)` → lecture seule, renvoie `DigestMaterielQuotidien`.

Chaque **valeur de `type_mouvement`** (`"RECEPTION"`, `"CONSOMMATION"`, `"VARIANCE_INVENTAIRE"`) ne peut apparaître dans un maillon passé à `ajouter`/`ajouter_lot` que **dans sa fonction orchestratrice désignée** — garde AST `garde_ecriture_stock` dans `conformite.py`. Le reorder n'est PAS un cinquième point d'écriture : c'est un **effet de bord en lecture** évalué après une réception et après une consommation (jamais après un comptage, puisqu'une variance ne modifie pas le théorique — DA-M6-09).

**Justification** : Reproduit la discipline mesurée de `m4_field_ops.outbox` — `completer_intervention` est LE seul chemin d'écriture vers `terminee`, gardé par `garde_ecriture_unique` (AST vérifiant qu'aucun autre site n'écrit la clé sensible et que la fonction n'appelle `ajouter` qu'une fois). M6 généralise le patron à trois types de mouvement : un point par type rend impossible qu'un chemin détourné écrive une consommation hors de la fonction gardée.

### DA-M6-12 — RÉVISÉE (PLAN T2.5) — PO persisté, machine à 12 statuts

**Décision précédente (abrogée)** : *« M6 ne persiste PAS les `BonDeCommandeDemande`. Le bon est
une ENTRÉE de l'appel `enregistrer_reception`... »* — reproduite en fin de section pour mémoire.

**Nouvelle décision** : M6 persiste le PO comme un document à cycle de vie propre, DISTINCT du
registre de mouvements de stock, avec la machine à **12 statuts NOMMÉS par
DEFINITION-PRODUIT.md §7 M6.5** (l.508, mot pour mot) : `draft`, `pending_admin_review`,
`approved`, `email_ready`, `sent_to_supplier`, `supplier_confirmed`, `partially_received`,
`received`, `cancelled`, `disputed`, `invoiced`, `closed`. Le PO vit comme une suite
d'événements append-only dans son propre registre nommé
(`opsys.stockage.maillons("m06-material-control", "bons_commande")`, ADR-0009) — **même patron
que `m3_estimation.devis_durable`** (copie-adaptation, #109) : un maillon `po_cree` puis un
maillon `transition_po` par transition, jamais hash-chaîné (comme `devis_durable.py`/
`facturation.py`, qui n'en portent pas non plus — la garantie append-only vit dans
`opsys.stockage` lui-même). Les transitions légales sont une **table figée**
(`contrats.TRANSITIONS_PO`, dict de `frozenset`, `bons_commande.transition_autorisee`), testée
exhaustivement (12×12, `test_bons_commande.py`). Nouveaux modules : `fournisseurs.py` (M6.2,
identité/coordonnées seulement, PLAN T2.5 point 2) et `bons_commande.py` (M6.5, PLAN T2.5
points 1/3/4) ; `livre_prix.py` (M6.3, PLAN T2.4) fournit la résolution de prix par ligne, lue par
`bons_commande.creer_brouillon`.

**Raison du changement (pourquoi DA-M6-12 était fausse)** : DA-M6-12 contredisait
DEFINITION-PRODUIT.md §7 M6.5 dès sa rédaction — une machine à 12 statuts NOMMÉS ne peut pas
exister sur un objet reconstruit à chaque appel sans jamais être gardé entre deux appels ; « M6
ne persiste pas les PO » et « le PO a 12 statuts » sont incompatibles, l'un des deux doit céder.
L'audit (`docs/departements/M6-audit.md` §3.1, §5 Phase 0/1) confirme : DA-M6-12 datait d'avant
que la persistance de l'instance existe (ADR-0009, T1.0, livré depuis) et était motivée
UNIQUEMENT par cette absence — le motif a disparu, pas la décision. Un PO n'est de toute façon
**pas un mouvement de stock** (l'énuméré gelé `type_mouvement`, §2.10, RESTE inchangé : aucun
type `PO_DEMANDE` n'y est ajouté, la garde `garde_ecriture_stock` de `conformite.py` continue de
ne porter que sur RECEPTION/CONSOMMATION/VARIANCE_INVENTAIRE/RETOUR/PERTE/BRIS) — c'est un
document distinct, avec sa propre collection nommée, exactement comme `devis_durable.py` (M3)
n'est pas le registre `estimations` de `registre.py`.

**Ce qui NE change PAS** : `reception.py` (`traiter_reception`) et
`materiel.enregistrer_reception` restent **inchangés, réutilisés tels quels** (audit M6 §5 Phase 1
tâche 9) — l'orchestrateur RECEPTION continue de recevoir un `BonDeCommandeDemande` structurel à
chaque appel (§2.4, inchangé) ; c'est `outils.receptionner_commande`, seule, qui — en plus, quand
`bon_demande.po_id` référence un PO persisté — vérifie la correspondance
(`bons_commande.bon_demande_correspond`), refuse une réception hors statut recevable
(`bons_commande.peut_recevoir`, avant toute écriture de stock), PUIS attache le verdict déjà
calculé (jamais recalculé) au PO : `partially_received` (RECEPTION_INFERIEURE/MIXTE) ou `received`
(CONFORME/RECEPTION_SUPERIEURE) — INDETERMINE ne transitionne rien, symétrique de l'ancien
comportement (zéro écriture). Un `bon_demande` sans PO persisté correspondant continue de
fonctionner EXACTEMENT comme avant (P5, « toute nouvelle route est additive ») : aucune régression
sur les 293 tests existants avant cette tranche.

**Envoi au fournisseur (N4)** : `bons_commande.marquer_envoye` (email_ready -> sent_to_supplier)
ne porte AUCUNE primitive d'envoi réel (toujours aucun réseau, DA-M6-01 inchangée) — le verrou est
le socle (`opsys.approbations`, `department.yaml` bloc `approbations.n4`, ADR-0009 §5), jamais une
vérification interne à la fonction (même patron que `m5_financecore.facturation.envoyer_facture`).
Le repli manuel documenté (point ouvert §13.10 du produit, confirmé par l'audit M6 §6) est le
corps de courriel texte généré par `bons_commande.generer_courriel` (M6.6), à copier-coller tant
que M1 n'envoie pas réellement.

**Limite déclarée (inchangée dans son esprit)** : M6 valide la structure et la correspondance au
PO persisté, pas la provenance première du PO lui-même (un appelant du socle pourrait, en
théorie, forger un maillon `po_cree` hors des outils publics) — même frontière d'intégrité que M3
face à son barème (DA-M3-05) ; les outils publics (`m6_creer_po_brouillon` et suivants) restent le
seul chemin normal.

<details>
<summary>Ancienne décision (abrogée par ce qui précède, conservée pour l'historique)</summary>

**Décision** : M6 ne persiste PAS les `BonDeCommandeDemande`. Le bon est une ENTRÉE de l'appel
`enregistrer_reception`, fournie par l'appelant en même temps que la `ReceptionPO`. M6 valide la
correspondance structurelle (`po_id`, `chantier_id`) et reconcilie les lignes ; une
non-correspondance produit `VerdictReception.INDETERMINE` et **zéro** écriture de stock.

**Justification (périmée)** : L'énuméré gelé `type_mouvement` (§2.10) ne comporte pas de type
`PO_DEMANDE` — stocker les PO exigerait d'inventer un type hors contrat. Cohérent avec « tout est
fourni par l'appelant, pas d'état caché » : M3 reçoit son `LeadQualifie`+marqueur à chaque appel
sans les stocker ; M6 reçoit de même son bon à chaque réception. **Limite déclarée** : M6 valide
la structure, pas la provenance du bon (un appelant pourrait fournir un bon fabriqué) — même
frontière d'intégrité que M3 face à son barème (DA-M3-05) ; la couche appelante est responsable de
la persistance des PO ouverts.

</details>

### DA-M6-13 — Le reorder ne crée jamais de PO ni de paiement ; pas de montant `INDETERMINE` vers M5

**Décision** : Aucune fonction sur le chemin d'émission d'un `SignalReorder` n'appelle un constructeur de `BonDeCommandeDemande` ni un chemin de paiement — garde AST (CA-M6-18). Le `SignalPoAPayer` n'est **jamais** construit si `montant_total_estime` serait `null`.

**Justification** : Le reorder est une **suggestion** (brief §2.6) ; un achat automatique franchirait une frontière T3. M5 ne doit jamais recevoir un montant à payer indéterminé (§2.8). Gardes structurelles plutôt que conventions, pour être éprouvables.

### DA-M6-14 — Digest déterministe à deux sources distinctes

**Décision** : `produire_digest_quotidien` est une fonction pure de `(registre, seuils, fenêtre)`. `variances_significatives` est peuplée depuis les maillons `VARIANCE_INVENTAIRE` du registre ; `reorders` est **recalculée** depuis le stock dérivé vs les seuils fournis (les `SignalReorder` ne sont pas des maillons — ils ne figurent pas dans l'énuméré `type_mouvement`). `hash_digest = empreinte(contenu canonique)`. Les horodatages sont reproduits **tels quels**, sans normalisation.

**Justification** : « Mêmes maillons + mêmes arguments → mêmes octets » (CA-M6-24), patron mesuré de `m3_estimation/digest.py`. Les deux listes proviennent de **sources distinctes** (registre vs recalcul stock/seuils), ce que CA-M6-24 exige. Ne pas normaliser les horodatages : le module ne répare jamais une entrée (leçon explicite du docstring de `m3_estimation/digest.py`).

### DA-M6-15 — Frontière GATED/T3

**Décision** : Restent hors v1, en GATED/T3 : (a) OCR/vision réelle sur factures et bordereaux (poids modèle, GPU, réseau) ; (b) tout parsing de courriel fournisseur par LLM (R-015, défense en profondeur REG-13 obligatoire avant activation) ; (c) toute intégration bancaire ou exécution de paiement réel (frontière, pas seulement séquencement — M6 ne paie jamais).

**Justification** : Incompatible avec le mode ombre v1 (stdlib + PyYAML, zéro réseau, zéro LLM, zéro horloge). La logique déterministe suffit à prouver toutes les gardes en CI.

### DA-M6-16 — Le prévu d'une estimation est PROVISOIRE, dans le registre du prévu existant

**Décision** : les besoins reçus de M3 (§2.12) sont rangés dans le registre `besoins_prevus` qui existe déjà
(celui que la déclaration de matériaux, la variance de chantier et le brouillon de PO lisent), comme prévu
PROVISOIRE reconnaissable à `source == "estimation_m3"` — jamais dans un second registre. Le prévu
DÉFINITIF reste celui du devis accepté ou de l'outil manuel. Trois règles : (1) une estimation ne bloque
jamais le prévu définitif : le refus « déjà enregistré » ignore les maillons provisoires ; (2) `pour_devis`
préfère le définitif, sinon la version d'estimation la plus récente : tous les lecteurs passent par lui ;
(3) les versions d'un même devis s'ajoutent sans rien réécrire : même `estimation_id` = déjà reçue
(no-op), `rang_registre` non supérieur au dernier = version périmée arrivée en retard (ignorée).

**Justification** : sans (1), l'estimation arrivée la première ferait refuser le devis accepté, qui
perdrait son `chantier_id` ; sans (2), il y aurait deux vérités du prévu ; sans (3), une réestimation
serait perdue ou un rejeu doublerait le prévu. Le prévu provisoire n'a jamais de `chantier_id` (M3 ne le
connaît pas à l'estimation, rien n'est deviné) : il n'impose donc aucune contrainte de chantier à la
déclaration, et un PO exige un chantier (`REJ-PO-CHANTIER-INCONNU`). M6 conserve le facteur de perte
reçu sans l'appliquer : la quantité du prévu reste la quantité NETTE de M3, et majorer une quantité à
commander est une décision d'achat.

---

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve | Critères | Tier |
|---|---|---|---|
| **S001** — Validation des entrées (WCT M4, formulaire, clés interdites) | Le `WctRecu` (12 clés mesurées, `"M6"` ∈ `consommateurs_cibles`, hash JAMAIS recalculé) est validé ; un `wct_id` inconnu et chaque clé interdite de l'ensemble #1 produisent un verdict **nommé et distinct** du rejet de schéma générique. | CA-M6-01, 02, 03 | T2 |
| **S002** — Catalogue et résolution de prix FALLBACK | Catalogue → historique (par ordre du registre) → `INDETERMINE` (`cout_unitaire_resolu = null`), aucune valeur codée en dur ; le coût FALLBACK est celui du mouvement le plus récent. | CA-M6-04, 05, 06 | T1 |
| **S003** — Cycle PO → réception, variance de réception | Verdicts `CONFORME`/`INFERIEURE`/`SUPERIEURE`/`MIXTE` non fusionnés ; `montant_total_estime` null **SSI** au moins une ligne `INDETERMINE`. | CA-M6-07, 08, 09, 10, 11 | T1 |
| **S004** — Stock localisé par chantier | Incrément à la réception, décrément à la consommation ; rejet fail-closed sans `chantier_id` et si la quantité dépasse le disponible ; stock jamais négatif. | CA-M6-12, 13 | T1 |
| **S005** — Variance d'inventaire sans accusation | `AUCUN_ECART`/`STOCK_INFERIEUR`/`STOCK_SUPERIEUR`/`INDETERMINE` (aucun mouvement préalable) ; `note_investigation` reste `null` et aucune fonction ne remplit un champ de cause. | CA-M6-14, 15, 16 | T1 |
| **S006** — Réapprovisionnement suggéré, jamais exécuté | `SignalReorder` avec `quantite_suggeree = seuil - stock` sous seuil fourni ; **silence** si aucun seuil ; aucun chemin ne relie le signal à un PO ou un paiement (AST). | CA-M6-17, 18 | T1 |
| **S007** — Contrats de sortie séparés par destinataire | `ConfirmationConsommationTerrain` sans aucune clé de coût (ensemble #2), vérifié bout en bout depuis le point d'entrée public ; aucun contrat émis ne porte de primitive de paiement (ensemble #1, AST). | CA-M6-19, 20 | T2 |
| **S008** — Registre append-only hash-chaîné | La chaîne (`hash_maillon` inclut `hash_precedent`) est préservée à l'ajout et toute altération est détectée à la re-validation. | CA-M6-21 | T1 |
| **S009** — Échappatoires D-032, conformité déterministe, digest | Chaque enum porte `INDETERMINE` ; aucun appel `random` non ensemencé / horloge / réseau, aucun littéral de coût en dur (AST) ; digest byte-identique sur deux appels, deux listes de sources distinctes. | CA-M6-22, 23, 24 | T1 |

---

## 6. PARAMÈTRES CONFIGURABLES

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `catalogue_materiaux` | Contrat gelé `CatalogueMateriaux` (§2.3) : version, unité monétaire, postes par matériau. | **Fourni par l'appelant à chaque résolution. Aucune valeur par défaut : un catalogue par défaut serait un coût inventé.** |
| `seuils_reorder` | Contrat gelé `SeuilReorder` (§2.5), par couple chantier/matériau. | **Fourni par l'appelant. Absence = silence (pas de suggestion), jamais un seuil deviné.** |
| `ancre_tete_registre` | Empreinte de tête à épingler hors du registre pour détecter une réécriture complète de chaîne. | Facultatif ; fourni par la couche d'intégration (le registre expose `hash_tete()` mais ne peut appliquer une ancre située hors de son instance). |

> Aucun seuil de bruit de comptage en v1 (PRD §0.2) : toute variance, même minime, est enregistrée et remontée. Le seuil de filtrage est un paramètre de roadmap, activable sans réécriture.

---

## 7. PÉRIMÈTRE V1 vs GATED/T3

### 7.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Fichier(s) responsable(s) |
|---|---|
| Validation WCT (12 clés, sans recalcul de hash) + formulaire + clés interdites | `validation.py`, `frontieres.py`, `contrats.py` |
| Résolution de prix catalogue → FALLBACK → `INDETERMINE` | `catalogue.py` |
| Cycle PO → réception, verdict + montant (équivalence null↔INDETERMINE) | `bons_commande.py`, `reception.py` |
| Stock localisé, dérivation pure, fail-closed | `stock.py`, `materiel.py` |
| Variance d'inventaire neutre (R-020) | `variance.py` |
| Reorder suggéré (silence si sans seuil), garde ⊘ PO/paiement | `reorder.py`, `conformite.py` |
| Contrats séparés par destinataire (terrain sans coût) | `contrats_sortie.py` |
| Registre append-only hash-chaîné + `ajouter_lot` atomique | `registre.py`, `encodage.py` |
| Digest quotidien déterministe | `digest.py` |
| Conformité statique (D-032, déterminisme, écriture unique, non-recalcul hash) | `conformite.py` |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 7.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| OCR / vision réelle sur factures et bordereaux | Poids modèle, GPU, infrastructure réseau (report déjà ratifié M5/M6). |
| Parsing de courriel fournisseur par LLM | R-015 injection indirecte ; défense en profondeur REG-13 requise avant activation. |
| Intégration bancaire / exécution de paiement réel | M6 ne paie jamais — hors périmètre par frontière, pas seulement par séquencement. |
| Écriture d'ajustement du livre après variance | Correction du stock théorique = décision humaine ; hors v1 (DA-M6-09). |
| Cross-référence maillon `CONSOMMATION` ↔ `wct_id` dans le registre | Le schéma gelé n'y porte pas la clé ; ajout append-only sans réécriture, en roadmap (§2.10). |

---

## 8. RISQUES MESURÉS DANS LE CODE LU (vigilance requise en implémentation et en revue)

1. `m4_field_ops/outbox.py:205` émet `devis_id: None` en dur, commentaire « M3 n'existe pas en v1 » — M4 mesuré n'est PAS recâblé sur M3 pourtant livré. Toute story M6 qui exigerait un `devis_id` non nul serait un contrat fantôme (parallèle #166). M6 traite `devis_id` comme `str | null`, valeur nulle attendue en pratique tant que M4 n'est pas corrigé séparément.
2. Divergence de convention `hash_precedent` entre voisins (`m3_estimation/registre.py` = 64 zéros ; `m4_field_ops/registre.py` = `None` ; contrat gelé M6 = chaîne vide, §2.10). Le registre M6 doit suivre le **contrat gelé** (chaîne vide à index 0), pas copier aveuglément un voisin — sinon `valider_chaine` échouera contre le schéma.
3. La garde de coût terrain (ensemble #2, DA-M6-03) recoupe des clés (`cout`, `montant`) que `AccuseReceptionPO`/`MaillonMateriel` portent légitimement : la garde doit viser le **seul** `ConfirmationConsommationTerrain`, jamais un scan global — sinon elle rejetterait des sorties correctes (test vert/rouge pour la mauvaise raison).
