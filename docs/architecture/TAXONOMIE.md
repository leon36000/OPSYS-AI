# Taxonomie métier partagée

Une seule liste des services d'une entreprise, dans le socle : `src/opsys/taxonomie.py`
(PLAN T0.13). M1 qualifie, M2 structure et M3 estime avec les mêmes codes. Aucun département n'en
garde une copie.

## Pourquoi

Le contrat `LeadQualifie` v1 (gelé) ne connaissait que `renovation_totale`, `extension`,
`ravalement`, `isolation_thermique` et `autre`. Aucun des quatre services réels du premier
client, Gouttières et Revêtements Synergy, n'y figurait (DEFINITION-PRODUIT §1, M1.3, M3.8, M6.1).
Le système ne pouvait pas accepter « gouttières ».

## Deux couches

| Couche | Où | Rôle |
|---|---|---|
| Catalogue de référence | `CATALOGUE_REFERENCE` | Vocabulaire : `gouttieres`, `revetement`, `soffite_fascia`, `reparation` (libellés fr-CA, mots-clés de détection). Rien n'est accepté du seul fait d'y figurer. |
| Profil d'entreprise | `$OPSYS_HOME/entreprise.yaml`, clé `services` | Déclaration de CETTE instance : codes du catalogue, ou services propres pour une autre PME (SaaS). |

Même mécanisme que `$OPSYS_HOME/paliers.yaml` : un fichier de l'instance, lu à la demande.
`taxonomie.enregistrer_services(..., par="nom")` l'écrit et journalise le changement.

```yaml
services:
  - gouttieres            # code du catalogue de référence
  - revetement
  - code: pose_pergola    # service propre : code, libelle, mots_cles (optionnel)
    libelle: Pose de pergolas
    mots_cles: [pergola]
```

En ligne de commande : `opsys services lister` (fichier, services déclarés, catalogue) et
`opsys services declarer gouttieres revetement --par nathan` (codes du catalogue, signé au journal
d'audit). Un service propre se déclare en éditant le fichier.

Règles : un code du catalogue se déclare par son seul code ; un code propre ne reprend jamais un
code du catalogue ; pas de doublon ; liste non vide.

## Fail-closed

Sans profil, ou avec un profil sans service, **aucun** service n'est accepté, pas même ceux du
catalogue : aucun service par défaut n'est inventé pour une entreprise qui ne l'a pas déclaré.
Le verdict dit quoi configurer et où (`REJ-SERVICE-NON-CONFIGURE`). Un code hors déclaration donne
`REJ-SERVICE-INCONNU` avec la liste des services déclarés ; un profil cassé donne
`REJ-PROFIL-INVALIDE`. Il n'y a jamais de repli sur `autre`.

## Contrat `LeadQualifie` v2

`departments/m01-front-office/contracts/m1-lead-qualifie.v2.yaml`, gelé. La v1 reste intacte et
reste acceptée.

- `service` (code de la taxonomie) remplace `type_travaux`.
- `schema_version: 2` est porté par le lead. **La version est explicite, jamais devinée** : un lead
  sans `schema_version` est un lead v1 ; un lead v1 qui porte `service`, ou un lead v2 qui porte
  `type_travaux`, est refusé.
- `source`, `utm`, `campagne` (optionnels) font partie du contrat.

| Département | Rôle en v2 |
|---|---|
| M1 | Émet le v2. Détecte UN service par les mots-clés du profil ; plusieurs services évoqués, ou aucun : pas de lead, l'agent demande lequel. Sans profil : refus avant toute écriture. |
| M2 | Accepte v1 et v2. Le service doit être déclaré au moment de l'ingestion ET de la readiness. Le marqueur signe la clé `service` (v2) ou `type_travaux` (v1, octets inchangés). |
| M3 | Valide `service` par la taxonomie, jamais par un énuméré local. Le barème est indexé par service : un service sans poste bloque l'estimation (« barème du service X absent : à fournir »). |

## Garde de dérive

- `opsys verifier` : profil valide s'il existe ; aucune source de département ni du socle ne recopie
  le catalogue (`taxonomie.copies_locales_du_catalogue`).
- `tests/test_taxonomie_derive.py` : le YAML v2, M1, M2 et M3 portent les mêmes clés, la même
  version et les mêmes sous-clés `utm` ; les copies de l'énuméré v1 de M1, M2 et M3 sont celles du
  fichier gelé.
- Gate BMAD de M3 (`departments/m03-estimation/docs/bmad/verif_coherence.py`, contrôle 13 ter) :
  l'architecture de M3 décrit le contrat v2 que M2 accepte et cite le catalogue du socle.

## Reste à faire

- M4 : `cedule.py` et `contrats.py` portent encore `TYPES_TRAVAUX` v1 ; M4 doit accepter le lead v2
  et le `service` de la cédule.
- M7 : `chantier_social.py` valide encore les types de travaux v1.
- Demande de chiffrage M1→M3 (`m1-demande-chiffrage.v1.yaml`) : v2 à publier.
- Règle de précédence entre services (« réparation de gouttières ») : décision du propriétaire (T2.1).
- Barèmes et estimateurs par service (T2.3, M3.8).
