# ADR M7-S006 — Content Factory core

> Architecte : MiMo-Pro-V2 (repli R-038 : Kimi-K3 sortie vide puis raisonnement 5925/6000 tronqué ; Qwen3.7-Max timeout >6 min — journalisé). MiMo retiré de tout rôle de revue sur S006.

**Statut** : Proposé (DESIGN_FIRST — contrat gelé, signatures = contrat d'implémentation, aucun code livré ici)
**Dépend de** : Brand Core v1 (D-015), seo-knowledge v1
**Décideurs** : équipe architecture ForgeAI

---

## 1. Schéma `content-item.v1.yaml`

**Contrat de données** : Fichier YAML immuable, versionné, sha256 épinglé dans un test consommateur (pattern D-015). Évolution = v2.

**Champs obligatoires** (types/contraintes) :

| Champ | Type | Contrainte | Justification |
|-------|------|------------|---------------|
| `id` | `str` | UUIDv4, unique | Traçabilité absolue de chaque item. |
| `version` | `str` | `"1.0.0"` | Version du schéma, gelée. |
| `brand_ref` | `str` | sha256 du fichier brand-contract.v1.yaml utilisé | Traçabilité de la source brand. |
| `seo_knowledge_ref` | `str` | sha256 du fichier seo-knowledge.v1.yaml utilisé | Traçabilité de la source SEO. |
| `surface` | `str` | Enum: `google_aio`, `perplexity`, `assistants_ia` | Cible D-013. |
| `pillar` | `str` | Enum: `seo`, `ppc`, `social` | Catégorisation métier. |
| `type` | `str` | Enum: `post_social`, `page_seo`, `fiche_gbp`, `article_blog` | Type de contenu. |
| `title` | `str` | Non vide, max 100 caractères | Titre composé par gabarit. |
| `body` | `str` | Non vide, max 5000 caractères | Corps composé par gabarit. |
| `tactics_applied` | `list[dict]` | Chaque dict: `tactique: str`, `statut: str`, `source: str` | Tactiques appliquées, avec leur statut et source de seo-knowledge. |
| `timestamp` | `str` | ISO 8601, fourni par l'appelant | Horodatage déterministe, jamais d'horloge interne. |
| `approval_status` | `str` | Enum: `PROPOSE`, `APPROVED`, `REJECTED` | Statut d'approbation, initial `PROPOSE`. |
| `approver` | `str` | Non vide si `approval_status` != `PROPOSE` | Acteur tracé, jamais d'auto-approbation. |
| `approval_timestamp` | `str` | ISO 8601, fourni par l'appelant | Horodatage de l'approbation. |

**Décisions** :
- Les tactiques avec statut `candidat_a_verifier` sont **incluses** mais marquées explicitement dans `tactics_applied` avec `statut: "candidat_a_verifier"`. Elles ne sont pas exclues car elles font partie de la connaissance SEO et leur application est tracée.
- Le `timestamp` est fourni par l'appelant (jamais d'horloge interne) pour garantir le déterminisme.
- L'`approver` est obligatoire dès que le statut n'est plus `PROPOSE` pour empêcher l'auto-approbation.

---

## 2. Placement & structure

**Arborescence** :
```
src/content/
├── __init__.py
├── factory.py          # Construction d'items
├── approval.py         # File d'approbation (0-6)
├── validation.py       # Validation contre le schéma
contracts/
└── content-item.v1.yaml  # Contrat gelé (pattern D-015)
tests/
└── content/
    ├── test_factory.py
    ├── test_approval.py
    └── test_validation.py
```

**Interfaces publiques (signatures Python)** :

```python
# src/content/factory.py
def build_content_item(
    brand: dict,
    surface: str,
    type: str,
    sujet: dict,
    timestamp: str
) -> dict:
    """Construit un item de contenu à partir des données fournies.
    Retourne un dict conforme au schéma content-item.v1.yaml.
    """

# src/content/validation.py
def validate_content_item(item: dict) -> bool:
    """Valide un item contre le schéma content-item.v1.yaml.
    Lève ValueError si invalide.
    """

# src/content/approval.py
def propose(item: dict, actor: str) -> dict:
    """Passe le statut à PROPOSE. Actor obligatoire."""

def approve(item: dict, actor: str) -> dict:
    """Passe le statut à APPROVED. Actor obligatoire."""

def reject(item: dict, actor: str) -> dict:
    """Passe le statut à REJECTED. Actor obligatoire."""

def list_items(status: str | None = None) -> list[dict]:
    """Liste les items, filtrés par statut si fourni."""

def publish(item: dict) -> None:
    """Publie l'item. Lève RuntimeError si statut != APPROVED (fail-closed)."""
```

**Justification** :
- Séparation des responsabilités : construction, validation, approbation.
- Le contrat dans `contracts/` respecte le pattern D-015.
- Les tests dans `tests/content/` couvrent chaque module.

---

## 3. Déterminisme de composition

**Règle de gabarits** : Titre et corps sont composés par substitution de variables dans des gabarits prédéfinis, sans LLM.

**Mécanisme** :
1. **Gabarits** : Fichiers YAML dans `src/content/templates/` (ex: `post_social.yaml`, `page_seo.yaml`).
2. **Variables disponibles** :
   - `brand.name`, `brand.tagline`, `brand.tone`, `brand.langue`
   - `sujet.titre`, `sujet.description`, `sujet.mots_cles`
   - `tactiques` (liste des tactiques appliquées, avec leur statut)
3. **Composition** : Pour chaque type de contenu, un gabarit définit des modèles de titre et de corps. Les variables sont substituées par simple remplacement de chaîne.
4. **Déterminisme** : Même entrée (brand, surface, type, sujet, timestamp) → même sortie. Aucune opération non déterministe (horloge, réseau, LLM).

**Exemple de gabarit** (`post_social.yaml`) :
```yaml
title_template: "{brand.name} - {sujet.titre}"
body_template: |
  {brand.tagline}
  {sujet.description}
  Tactiques appliquées : {tactiques}
```

**Justification** : Respecte la contrainte ZÉRO LLM, garantit la reproductibilité, et permet une traçabilité claire des données sources.

---

## 4. Anti-dérive

**Risque 1 : Invention de contenu hors données fournies**
- **Parade** : Validation stricte des champs `title` et `body` contre les gabarits. Tout contenu non issu d'une substitution de variable est rejeté. Test unitaire vérifie que la sortie ne contient que des variables connues.

**Risque 2 : Auto-approbation déguisée**
- **Parade** : Le champ `approver` est obligatoire et doit être différent de l'acteur ayant proposé l'item. Validation dans `approve()` : `if actor == item.get("proposer"): raise ValueError("Auto-approbation interdite")`. Le `proposer` est enregistré à la proposition.

**Risque 3 : Contrat modifié au lieu de versionné**
- **Parade** : Le fichier `contracts/content-item.v1.yaml` est gelé. Son sha256 est épinglé dans un test consommateur (`tests/content/test_contract_sha.py`). Toute modification du fichier échoue le test. Évolution = création d'un nouveau fichier v2.

**Justification** : Chaque parade est testable et empêche la dérive par conception.

---

## 5. File d'approbation « 0-6 »

**Statut initial** : `PROPOSE`
**Transitions explicites** :
- `PROPOSE` → `APPROVED` (acteur: `approver`)
- `PROPOSE` → `REJECTED` (acteur: `approver`)
- `APPROVED` → `REJECTED` (acteur: `approver`, cas de révision)
- `REJECTED` → `PROPOSE` (acteur: `proposer`, re-soumission)

**Règles** :
- JAMAIS d'auto-approbation (vérifié dans `approve()`).
- `publish()` lève `RuntimeError` si `approval_status != APPROVED` (fail-closed).
- Chaque transition enregistre l'acteur et un timestamp fourni par l'appelant.

**Justification** : Respecte la contrainte « 0-6 » avec traçabilité complète et fail-closed.

---

## 6. Validation du schéma

**Mécanisme** : Validation par PyYAML + vérification manuelle des types et contraintes (pas de jsonschema, stdlib only).

**Fonction `validate_content_item`** :
1. Charge le YAML du contrat (`content-item.v1.yaml`).
2. Vérifie la présence de tous les champs obligatoires.
3. Vérifie les types (str, list, etc.) et les contraintes (enum, longueur, format UUID, ISO 8601).
4. Lève `ValueError` avec message détaillé si invalide.

**Justification** : Respecte la contrainte stdlib, pas de dépendance externe.

---

## 7. Dépendances

- **Brand Core v1** : Fichier `brand-contract.v1.yaml` (sha256 épinglé). Champs utilisés : `name`, `tagline`, `tone`, `colors[]`, `langue`.
- **seo-knowledge v1** : Fichier `seo-knowledge.v1.yaml` (sha256 épinglé). Champs utilisés : `surfaces` (google_aio, perplexity, assistants_ia), chaque surface avec `position`, `faits[]`, `tactiques[{tactique, statut, source}]`.

**Justification** : Les sha256 sont épinglés dans des tests consommateurs pour garantir la compatibilité.

---

## 8. Livrables

1. `contracts/content-item.v1.yaml` (contrat gelé)
2. `src/content/factory.py` (construction)
3. `src/content/validation.py` (validation)
4. `src/content/approval.py` (file d'approbation)
5. `src/content/templates/` (gabarits)
6. `tests/content/` (tests unitaires et d'intégration)
7. `tests/content/test_contract_sha.py` (test du sha256 du contrat)

**Justification** : Couvre tous les aspects du module, avec tests pour garantir le déterminisme et l'anti-dérive.

---

**Cet ADR est un contrat d'implémentation. Aucun code n'est livré ici. L'implémentation devra respecter strictement ces décisions.**
