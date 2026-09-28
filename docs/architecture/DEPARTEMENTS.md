# Construire un département OPSYS

Un département est un organe de l'entreprise. Il octroie à ses agents les capacités dont ils ont
besoin pour exceller :
- des **outils** déterministes ;
- des **skills** (procédures) ;
- des **politiques** d'autonomie ;
- des **planifications** ;
- des **budgets** et des **KPIs**.

Référence complète et testée : `departments/m03-estimation/`.

## Arborescence

```
departments/mNN-nom/
├── department.yaml          # manifeste (source unique)
├── SOUL.md                  # identité, ce que l'agent fait / ne fait jamais
├── skills/<nom>/SKILL.md    # procédures (format Agent Skills : frontmatter name + description)
├── src/mN_nom/              # code métier déterministe + outils.py
├── tests/                   # tests du métier + tests des outils d'agent
├── contracts/, fixtures/    # contrats de données et jeux d'essai
└── docs/                    # PRD, architecture du département
```

## `department.yaml` (schéma `opsys.departement/v1`)

```yaml
schema: opsys.departement/v1
id: m03-estimation            # = nom du dossier = identifiant de l'agent OpenClaw
code: M3
nom: Estimation
mission: >-                   # un paragraphe, repris dans AGENTS.md de l'agent
  …
outils: m3_estimation.outils  # module Python qui expose outils() -> tuple[Outil, ...]
mode: ombre                   # ombre | supervise | autonome (voir Politiques)
dependances: [m02-revenue-crm]
modeles:                      # palier par usage : local | rapide | standard | fort
  defaut: standard
  extraction: rapide
skills: [estimer-un-projet]   # dossiers skills/<nom>/SKILL.md
planifications:               # livrées en pause ; activées depuis le dashboard
  - nom: digest-estimations
    cron: "0 7 * * 1-5"
    consigne: "…"
budget: {tokens_jour: 300000, tokens_mois: 4000000, alerte_pct: 80}
memoire: {lecture: [clients, chantiers], ecriture: [estimations]}
kpis:
  - {id: ecart_estime_reel_pct, description: "…"}
```

`opsys verifier` valide tous les manifestes, l'unicité des outils et les dépendances. Il tourne
en CI.

## `outils.py` : le contrat d'outil

```python
from opsys.outils import Autonomie, Outil, depuis_couple

def estimer_projet(photos, seuils, bareme, type_travaux, quantite, plancher_rentable, graine=None):
    ...  # compose les fonctions métier existantes, renvoie un dict

def outils() -> tuple[Outil, ...]:        # une fonction, pas une constante publique :
    return (                                # les gardes AST des paquets traitent les
        Outil(                              # constantes MAJUSCULES comme des énumérés métier
            nom="m3_estimer_projet",        # préfixe obligatoire mN_
            description="…",                # court et précis : envoyé au modèle à chaque tour
            parametres={...JSON Schema object, additionalProperties: False...},
            fonction=estimer_projet,        # appelée avec **arguments
            autonomie=Autonomie.T0,
        ),
    )
```

Règles :
1. **Envelopper, ne pas réécrire.** L'outil appelle les fonctions métier existantes. Le patron
   `(resultat, verdict)` se traduit par `depuis_couple`.
2. **Composer pour économiser.** Un outil « de bout en bout » (ex. `m3_estimer_projet`) remplace
   cinq allers-retours du modèle. Garder aussi les outils unitaires pour les cas particuliers.
3. **Refuser clairement.** Un refus métier lève `ValueError` ou renvoie un verdict. L'agent reçoit
   `refus_metier` et sait quoi corriger. Jamais de valeur par défaut inventée.
4. **Résultats JSON sûrs.** Les `Decimal` sont convertis en chaîne, les dates en ISO. Montants en
   CAD.
5. **Descriptions courtes.** Chaque caractère est payé à chaque tour. Le détail va dans une skill.

## Politiques : autonomie des outils et modes

| Autonomie | Sens | `ombre` | `supervise` | `autonome` |
|---|---|---|---|---|
| T0 | lecture / calcul pur | exécuté | exécuté | exécuté |
| T1 | écriture interne (registre, brouillon) | approbation | exécuté | exécuté |
| T2 | action externe réversible (message client, publication de brouillon) | approbation | approbation | exécuté |
| T3 | frontière humaine : paiement, écriture financière, publication, engagement, suppression | approbation | approbation | **approbation** |

Un nouveau département démarre en `ombre`. Le propriétaire le promeut depuis le dashboard ou avec
`opsys mode <id> supervise --par <nom>`.

## SOUL.md

Une page maximum : identité, ce que l'agent fait, ce qu'il ne fait jamais. Les capacités et les
règles communes (économie de tokens, Loi 25, approbations) sont ajoutées automatiquement à la
génération de l'espace de travail de l'agent (`opsys openclaw configurer`). Ne pas les recopier.

## Skills

Format Agent Skills (`SKILL.md` avec frontmatter `name` et `description`). Une skill décrit une
procédure : quelles données réunir, quel outil appeler, comment lire la réponse. Seules la
description et le nom sont chargés d'office ; le corps n'est lu qu'à la demande (divulgation
progressive).

## Tests exigés

- Le métier : les tests existants restent verts.
- Les outils d'agent, dans `tests/test_outils_agent.py` :
  - le manifeste se charge ;
  - chaque outil composé est exercé sur des cas réalistes (nominal, refus, blocage) ;
  - la reproductibilité est vérifiée quand il y a de l'aléatoire.
- Aucune donnée inventée dans les fixtures sans le marqueur `fictif: true`.
