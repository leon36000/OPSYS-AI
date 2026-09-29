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
| M4 | Accepte v1 et v2 comme M2 (`contrats.py`, `cedule.py`). L'inscription porte `type_travaux` (v1, maillon inchangé) ou `service` et `schema_version` (v2). Voir « Nature des travaux dans M4 » plus bas. |
| M7 | `chantier_social.py` accepte un chantier v1 (`type_travaux`, énuméré du contrat gelé sans `autre`) ou v2 (`schema_version: 2` et `service` : titre tiré du libellé du service déclaré). |

## Nature des travaux dans M4 (PLAN T0.13-b)

Règle unique : **v1 → `type_travaux`, v2 → `service`, jamais l'un déduit de l'autre.** La version est celle
du lead, lue à l'inscription ; une intervention porte exactement l'une des deux clés
(`etats.travaux_de`, seul endroit où la règle est écrite).

| Où | v1 | v2 |
|---|---|---|
| Inscription (maillon) | `type_travaux` (inchangé, octet pour octet) | `service` et `schema_version: 2` |
| `m4_lister_interventions` | `type_travaux` | `service` (l'app mobile accepte exactement l'une des deux) |
| Cédule simple (`m4_planifier_intervention`) | `type_travaux` dans l'assignation | `service` dans l'assignation |
| Cédule par tournées | `durees_par_type_travaux`, `competences_par_type_travaux` | `durees_par_service`, `competences_par_service` |
| WCT et événement `m4.travaux_termines` | `type_travaux` | `service` (clé additive du catalogue) |

- Les tables de la cédule par tournées ne sont exigées que pour la version présente dans le lot : un lot
  mixte exige les deux jeux, et chaque intervention lit la table de SA version (un service propre peut porter
  le code d'un type v1, aucune n'est prise pour l'autre). Les deux tables par type restent requises par le
  schéma de l'outil (`{}` pour un lot sans lead v1).
- Le WCT ne porte jamais les deux clés (`outbox.verifier_invariants_outbox` le refuse). Ses treize clés
  requises ne changent pas ; `service` s'ajoute au catalogue du socle et à `CHAMPS_WCT_OPTIONNELS` de M4 et
  de M6 (qui refuse toute clé inconnue). M10 n'en extrait que les douze clés de son contrat.
- M7 lit `type_travaux` (lead v1) ou `service` (lead v2) dans `m4.travaux_termines` (PLAN T1.5-d) : la demande
  d'avis dit `type_travaux` pour un v1 et le libellé du service déclaré (`taxonomie.valider_service`) pour un v2 ;
  un service non déclaré donne un texte générique et un avertissement au brouillon, jamais le code brut. Un WCT
  qui porte les deux clés est refusé. Le brouillon de contenu public garde `type_travaux` et `service` tels
  quels, sans texte qui en dépende.

## Zone desservie (PLAN T2.1-a)

Le même profil (`$OPSYS_HOME/entreprise.yaml`) porte `zone_desservie` : la liste des villes où l'entreprise
intervient. `opsys.taxonomie.charger_zone_desservie` la lit ; sans zone, aucune ville n'est reconnue et le verdict
`REJ-ZONE-NON-CONFIGUREE` dit où la déclarer. M1 la lit pour un message de canal : l'agent ne la fournit pas. Un profil
mal formé (liste vide, ville en double) est refusé, jamais lu comme absent ; `opsys verifier` le signale.

## Fenêtre de conversation (PLAN T2.1-b)

Le même profil porte `fenetre_conversation_minutes` : la durée, en minutes entières (de 1 à 10080), pendant laquelle M1
rassemble les messages d'un même client pour qualifier une demande écrite en plusieurs messages.
`opsys.taxonomie.charger_fenetre_conversation` la lit. **Aucune durée n'est inventée** : absente, elle donne le verdict
`REJ-FENETRE-NON-CONFIGUREE` (qui dit où la déclarer), et M1 qualifie message par message comme avant. Une valeur mal
formée est refusée (`REJ-PROFIL-INVALIDE`), jamais lue comme absente ; `opsys verifier` la signale. Détail des règles :
[M1-canaux](../departements/M1-canaux.md) §8.

## Questions obligatoires par service et poids du score (PLAN T4.4)

Le même profil porte ce que M1 demande au client pour qualifier un lead, et comment il le note. **Rien de cela n'est
dans le code** : le propriétaire l'écrit (GATE NATHAN), et `opsys.taxonomie` le lit et l'écrit comme la zone et la
fenêtre (`enregistrer_*(…, par="nom")` signe au journal d'audit).

```yaml
questions_qualification:        # par code de service ; l'ordre écrit est l'ordre posé
  gouttieres:
    - code: longueur            # stable, unique dans le service
      question: "Quelle est la longueur approximative à remplacer, en pieds ou en mètres?"   # une ligne, 300 car. au plus
      mots_cles: [pied, mètre]  # les termes qui montrent que le client a répondu (mots entiers, pluriel admis)
    - code: photo_facade
      question: "Pouvez-vous nous envoyer une photo de la façade concernée?"
      photos: true              # demande de photos : sans mots_cles, et fermée tant que la politique n'est pas validée
poids_score_lead:               # un entier de 0 à 1000 pour CHAQUE critère ; 0 écarte un critère
  urgence: 30
  completude: 50
  zone: 20
```

| Situation | Verdict |
|---|---|
| Aucune question déclarée (clé absente ou vide) | `REJ-QUESTIONS-NON-CONFIGUREES`, qui dit où les écrire. Aucune liste par défaut. |
| Des questions déclarées, mais aucune pour ce service | Le même code, qui nomme le service (`charger_questions_du_service`). |
| Poids absents ou vides | `REJ-POIDS-SCORE-NON-CONFIGURES` : « poids à configurer ». Aucun score n'est calculé. |
| Valeur écrite mais invalide (liste vide, question sans `mots_cles`, poids décimal, critère inconnu, tous les poids à 0…) | `REJ-PROFIL-INVALIDE` avec la raison, **jamais lue comme absente** ; `opsys verifier` la signale. |

Des questions ou des poids invalides n'arrêtent pas la réception d'un lead (contrairement aux services, à la zone et à la
fenêtre, qui la conditionnent) : M1 reçoit, qualifie, et dit `REJ-PROFIL-INVALIDE` dans le bloc concerné de sa réponse.
`opsys verifier` signale aussi des questions écrites pour un service que l'entreprise ne déclare pas. Les questions et les
poids d'un test sont fictifs : `departments/m01-front-office/fixtures/qualification/profil-fictif.v1.yaml`
(`fictif: true`). Comment M1 les utilise : [M1-canaux](../departements/M1-canaux.md) §9.

## Garde de dérive

- `opsys verifier` : profil valide s'il existe ; aucune source de département ni du socle ne recopie
  le catalogue (`taxonomie.copies_locales_du_catalogue`).
- `tests/test_taxonomie_derive.py` : le YAML v2, M1, M2, M3 et M4 portent les mêmes clés, la même
  version et les mêmes sous-clés `utm` ; les copies de l'énuméré v1 de M1, M2, M3 et M4 sont celles du
  fichier gelé (celle de M7, l'énuméré sans `autre`) ; M4 et M7 valident `service` par
  `opsys.taxonomie` ; le catalogue de `m4.travaux_termines` et M4 déclarent `type_travaux` et `service`.
- Gate BMAD de M3 (`departments/m03-estimation/docs/bmad/verif_coherence.py`, contrôle 13 ter) :
  l'architecture de M3 décrit le contrat v2 que M2 accepte et cite le catalogue du socle.

## Reste à faire

- Demande de chiffrage M1→M3 (`m1-demande-chiffrage.v1.yaml`) : v2 à publier.
- Règle de précédence entre services (« réparation de gouttières ») : décision du propriétaire (T2.1).
- Barèmes et estimateurs par service (T2.3, M3.8).
