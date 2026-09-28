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
evenements:                   # optionnel (ADR-0009 §3) — voir « Événements » ci-dessous
  consomme: [m4.travaux_termines]   # types du catalogue src/opsys/evenements/catalogue/*.json
```

`opsys verifier` valide tous les manifestes, l'unicité des outils, les dépendances et la cohérence
des événements (types déclarés au catalogue, fonction présente pour chaque type consommé, aucune
fonction orpheline). Il tourne en CI.

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

## Taxonomie des services (PLAN T0.13)

Un département qui parle des services de l'entreprise (gouttières, revêtement, soffite/fascia,
réparation, ou ceux d'une autre PME) ne recopie jamais la liste : il valide un code avec
`opsys.taxonomie.valider_service` (profil d'entreprise `$OPSYS_HOME/entreprise.yaml`). Sans profil,
tout service est refusé avec un verdict qui dit quoi configurer. `opsys verifier` échoue si une
source recopie le catalogue. Voir [TAXONOMIE](TAXONOMIE.md).

## Événements (ADR-0009 §3, bus dans `opsys.evenements`)

Un département déclare ce qu'il publie et consomme dans `department.yaml` (`evenements:`, voir plus
haut ; les deux clés sont optionnelles). Le catalogue versionné (`opsys.evenement/v1`, un fichier
JSON Schema par type) vit dans `src/opsys/evenements/catalogue/*.json` — c'est le socle qui le
possède, pas les départements.

Les fonctions qui consomment un événement vivent dans le **même module que `outils()`**
(`module_outils` du manifeste), sous la forme :

```python
def _recevoir_travaux_termines(charge: dict) -> dict:
    ...  # fonction DÉTERMINISTE, jamais un modèle ; écrit dans les registres du département,
         # peut publier des événements de second ordre (evenements.publier) ; petit dict de résumé
    return {"traite": True}

def consommateurs() -> dict[str, Callable[[dict], dict]]:   # clé = type_evenement consommé
    return {"m4.travaux_termines": _recevoir_travaux_termines}
```

Un département qui ne consomme aucun événement n'a pas besoin de définir `consommateurs`. Le
répartiteur (`opsys.evenements.repartir`) l'appelle avec la charge déjà validée contre son schéma ;
un échec annule ses écritures (point de sauvegarde), garde le reçu en échec avec un backoff
exponentiel, et passe en quarantaine après 5 échecs — sans jamais bloquer les autres consommateurs
du même événement ni les événements suivants. `opsys verifier` vérifie que chaque type publié ou
consommé existe au catalogue, que chaque type consommé a sa fonction, et qu'aucune fonction de
`consommateurs()` n'est orpheline (absente de `evenements.consomme`).

## Politiques : autonomie des outils et modes

| Autonomie | Sens | `ombre` | `supervise` | `autonome` |
|---|---|---|---|---|
| T0 | lecture / calcul pur | exécuté | exécuté | exécuté |
| T1 | écriture interne (registre, brouillon) | approbation | exécuté | exécuté |
| T2 | action externe réversible (message client, publication de brouillon) | approbation | approbation | exécuté |
| T3 | frontière humaine : paiement, écriture financière, publication, engagement, suppression | approbation | approbation | **approbation** |

Un nouveau département démarre en `ombre`. Le propriétaire le promeut depuis le dashboard ou avec
`opsys mode <id> supervise --par <nom>`.

## Niveaux N et politique d'approbation par département (ADR-0009 §4/§5)

Chaque outil porte aussi un niveau N (`opsys.outils.Niveau`), l'échelle unique de la définition
produit (§5) : c'est en N que s'exprime la règle d'approbation (`opsys.politiques.
approbation_requise_niveau`), T reste la classification historique du socle. Un `Outil` fixe N
explicitement (`niveau=Niveau.N2`, par exemple) ou laisse la correspondance par défaut depuis T
s'appliquer (`niveau_effectif`, documentée dans `opsys/outils.py`) :

| T | N par défaut | Règle |
|---|---|---|
| T0 | N0 (lecture, lus N0–N2 : tous automatiques, le choix exact ne change rien) | automatique |
| T1 | N3 | validation humaine au départ (`ombre`) |
| T2 | N4 | le propriétaire (`ombre`, `supervise`) |
| T3 | N5 | le propriétaire **et** l'attestation du professionnel ; jamais automatique |

Un département déclare, dans `department.yaml`, quels rôles (ADR-0009 §5 : `nathan_owner`,
`admin`, `finance`, `manager`, `seller`, `employee`, `client`, `system_agent`) peuvent décider
(approuver ou refuser) une demande de niveau N3 ou N4 — bloc `approbations`, entièrement optionnel :

```yaml
approbations:              # optionnel ; n3/n4, chacun optionnel
  n3: [manager, nathan_owner]
  n4: [nathan_owner]
```

Absent, ou un niveau qu'il ne couvre pas : politique par défaut la plus restrictive, `nathan_owner`
seul (fail-closed). `opsys.approbations.decider` exige une personne active (`opsys.identite`) dont
un rôle figure dans la politique du DÉPARTEMENT DE LA DEMANDE pour son niveau N ; sinon, refus
nommé, rien exécuté, la demande reste en attente.

**N5 ne se déclare pas** : c'est une frontière fixe de l'ADR (« la signature de `nathan_owner` »,
jamais automatique, jamais déléguée à un autre rôle) — un manifeste qui tente `approbations.n5`
est rejeté au chargement. Une demande N5 exige, en plus de `nathan_owner`, une attestation
structurée du professionnel (nom, profession, référence du document joint) pour être approuvée.

## Portée d'appareil : qui peut appeler l'outil depuis un téléphone (T1.4-j)

Un outil n'est appelable par un jeton d'appareil (`employee`, `seller`, `admin`) que s'il le
déclare : `roles_appareil=frozenset({"employee", "admin"})` sur l'`Outil`, avec en commentaire la
ligne de la définition produit §9 qui le justifie. **Défaut : vide, donc fermé à tous les appareils**
(les agents gardent leur accès par le serveur MCP). T3/N5 n'est jamais projeté, quoi qu'il déclare ;
`opsys verifier` refuse un rôle qui n'est pas un rôle d'appareil et un outil T3/N5 qui en déclare un.
Règle, table et questions de relecture : [ROLES.md](ROLES.md).

## File du propriétaire (ADR-0009 §5)

`opsys.approbations.file_proprietaire` (CLI `opsys approbations file`, API `GET
/api/approbations/file` de la console) rassemble, de façon compacte, les demandes d'approbation du
socle en attente et les « attentes » que chaque département déclare lui-même — mêmes chantiers en
révision, mêmes bons de commande à approuver, mais pas encore une demande formelle du socle. Un
département optionnel expose, au même endroit que `outils()` et `consommateurs()` :

```python
def attentes() -> list[dict]:                         # optionnel, même mécanisme que consommateurs()
    return [{"type": "chantier_a_reviser", "id": "wct-123", "resume": "Écart matériaux 42 %",
             "niveau": "N4", "depuis": "2026-09-28T12:00:00+00:00", "action_proposee": "réviser"}]
```

Forme commune de chaque élément : `type`, `id`, `resume`, `niveau`, `depuis`, `action_proposee`
(plus `departement`, ajouté par `file_proprietaire`). `opsys verifier` vérifie que `attentes()`, si
présent, se charge (`opsys.departements.verifier_attentes`) ; un département dont l'appel échoue à
l'usage est journalisé et sauté, jamais bloquant pour les autres. Aucun département de production
n'implémente `attentes()` pour l'instant (PLAN T1.3-b/c) ; le mécanisme est exercé par le
département de démonstration des tests du socle (`tests/fixtures/demo_outils.py`).

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
