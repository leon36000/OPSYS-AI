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

En ligne de commande : `opsys-metier services lister` (fichier, services déclarés, catalogue) et
`opsys-metier services declarer gouttieres revetement --par nathan` (codes du catalogue, signé au journal
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
  le code d'un type v1, aucune n'est prise pour l'autre). Depuis T4.12, aucune table n'est requise par le schéma de
  l'outil : celles par service viennent du profil des équipes (plus bas), celles par type de travaux (leads v1, gelés)
  restent des arguments, exigés seulement si le lot contient un lead v1.
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
mal formé (liste vide, ville en double) est refusé, jamais lu comme absent ; `opsys-metier verifier` le signale.

## Fenêtre de conversation (PLAN T2.1-b)

Le même profil porte `fenetre_conversation_minutes` : la durée, en minutes entières (de 1 à 10080), pendant laquelle M1
rassemble les messages d'un même client pour qualifier une demande écrite en plusieurs messages.
`opsys.taxonomie.charger_fenetre_conversation` la lit. **Aucune durée n'est inventée** : absente, elle donne le verdict
`REJ-FENETRE-NON-CONFIGUREE` (qui dit où la déclarer), et M1 qualifie message par message comme avant. Une valeur mal
formée est refusée (`REJ-PROFIL-INVALIDE`), jamais lue comme absente ; `opsys-metier verifier` la signale. Détail des règles :
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
| Valeur écrite mais invalide (liste vide, question sans `mots_cles`, poids décimal, critère inconnu, tous les poids à 0…) | `REJ-PROFIL-INVALIDE` avec la raison, **jamais lue comme absente** ; `opsys-metier verifier` la signale. |

Des questions ou des poids invalides n'arrêtent pas la réception d'un lead (contrairement aux services, à la zone et à la
fenêtre, qui la conditionnent) : M1 reçoit, qualifie, et dit `REJ-PROFIL-INVALIDE` dans le bloc concerné de sa réponse.
`opsys-metier verifier` signale aussi des questions écrites pour un service que l'entreprise ne déclare pas. Les questions et les
poids d'un test sont fictifs : `departments/m01-front-office/fixtures/qualification/profil-fictif.v1.yaml`
(`fictif: true`). Comment M1 les utilise : [M1-canaux](../departements/M1-canaux.md) §9.

## Vocabulaire des plaintes et destinataires des transferts (PLAN T4.5)

Le même profil porte ce que M1 reconnaît d'une plainte ou d'une urgence de sécurité, et à qui il transfère. **Rien de cela
n'est dans le code** : le propriétaire l'écrit (GATE NATHAN), `opsys.taxonomie` le lit et l'écrit comme le reste
(`enregistrer_*(…, par="nom")` signe au journal d'audit).

```yaml
signaux_plainte:                # par catégorie (ensemble fermé) ; une catégorie absente ne reconnaît rien
  insatisfaction: [déçu, inacceptable, plainte]        # des mots, ou des expressions de plusieurs mots
  degat: [après vos travaux, vous avez endommagé]
  garantie: [sous garantie, malfaçon]
  avocat: [avocat, mise en demeure]                    # menace juridique : pas de brouillon de réponse
  securite: [danger, fumée, fil électrique]            # urgence : escaladée tout de suite
destinataires_transfert:        # type de transfert -> rôle ; une table partielle est permise
  plainte: nathan_owner         # types : ventes, estimation, admin, finance, plainte, urgence, technique, proprietaire
  urgence: nathan_owner         # rôles : nathan_owner, admin, finance, manager, seller, employee
```

| Situation | Verdict |
|---|---|
| Aucun vocabulaire (clé absente ou vide) | `REJ-SIGNAUX-PLAINTE-NON-CONFIGURES` : « vocabulaire des plaintes à configurer ». M1 ne reconnaît aucune plainte et le dit dans chaque réponse. Aucun mot par défaut. |
| Aucun destinataire pour ce type de transfert | `REJ-DESTINATAIRE-NON-CONFIGURE` : « destinataire à configurer pour le transfert de type … ». Le transfert est ouvert quand même ; M1 ne choisit jamais une personne. |
| Valeur écrite mais invalide (catégorie ou type inconnu, terme de moins de 3 caractères, doublon, rôle inconnu, `client` ou `system_agent`, déclaration vide…) | `REJ-PROFIL-INVALIDE` avec la raison, **jamais lue comme absente** ; `opsys-metier verifier` la signale. |

Un terme suit les règles de lecture des mots-clés d'un service : mot entier, pluriel admis, accents et casse ignorés (le féminin
s'écrit à part : « déçu », « déçue »). Les types de transfert sont ceux de la définition du produit (§7 M1.12) : un test de dérive
(`tests/test_taxonomie_plaintes.py`) les compare à ce texte. Un vocabulaire ou une table invalides n'arrêtent pas la réception
d'un message. Ce que M1 en fait : [M1-canaux](../departements/M1-canaux.md) §10.

## Garde de dérive

- `opsys-metier verifier` : profil valide s'il existe ; aucune source de département ni du socle ne recopie
  le catalogue (`taxonomie.copies_locales_du_catalogue`).
- `tests/test_taxonomie_derive.py` : le YAML v2, M1, M2, M3 et M4 portent les mêmes clés, la même
  version et les mêmes sous-clés `utm` ; les copies de l'énuméré v1 de M1, M2, M3 et M4 sont celles du
  fichier gelé (celle de M7, l'énuméré sans `autre`) ; M4 et M7 valident `service` par
  `opsys.taxonomie` ; le catalogue de `m4.travaux_termines` et M4 déclarent `type_travaux` et `service`.
- Gate BMAD de M3 (`departments/m03-estimation/docs/bmad/verif_coherence.py`, contrôle 13 ter) :
  l'architecture de M3 décrit le contrat v2 que M2 accepte et cite le catalogue du socle.

## Équipes, dépôt, quarts et durées (PLAN T4.12)

Le même profil porte les équipes de l'entreprise et ce que M4 en fait : `opsys.equipes` (module frère de
`opsys.taxonomie`, même fichier, même écriture signée au journal d'audit). Avant T4.12, l'agent recopiait équipes, dépôt
et quarts à chaque cédule. **Rien de cela n'est dans le code** : le propriétaire le déclare (GATE NATHAN), une fois.

```yaml
equipes:
  liste:                        # l'id d'une équipe EST le technicien_id de son assignation
    - id: eq-repentigny
      membres: [alice, bruno]   # identifiants de PERSONNES OPSYS (opsys-metier personnes lister), rien d'autre
      competences: [gouttieres, revetement]                  # des codes que le propriétaire choisit
      depot: {id: depot-repentigny, latitude_microdegres: 45735000, longitude_microdegres: -73455000}
      quarts: [{jour: 0, debut_min: 480, fin_min: 1020}]     # jour : numéro de journée de la cédule
  services:                     # par code de service DÉCLARÉ ci-dessus, durée et compétences requises
    gouttieres: {duree_min: 90, competences: [gouttieres]}
  cedule:                       # réglages du solveur, tous obligatoires (graine facultative)
    {facteur_detour_milliemes: 1300, vitesse_moyenne_kmh: 50, marge_par_trajet_secondes: 600,
     iterations: 500, cout_non_cedule_m: 500000}
  fenetre_par_defaut:           # offerte à un chantier a_planifier dont le client n'a donné aucune fenêtre
    {jours: [0], debut_min: 480, fin_min: 1020}
```

`opsys-metier equipes lister` montre le fichier, le profil canonique et ce qu'il reste à déclarer ; `opsys-metier equipes declarer
--depuis equipes.yaml --par nathan` REMPLACE la clé entière par le contenu validé du fichier (YAML ou JSON), signée au
journal (identifiants d'équipe, nombre de membres, services, empreinte : jamais le nom d'un membre). Les membres doivent
être des personnes OPSYS existantes et actives ; une personne n'est membre que d'une équipe ; l'identifiant d'une équipe
ne peut être celui d'une personne qui n'en est pas membre. Chaque sous-clé est facultative à la déclaration : ce qui
manque, M4 le dit au moment d'en avoir besoin.

| Situation | Verdict |
|---|---|
| Aucun profil (clé absente ou vide) | `REJ-EQUIPES-NON-CONFIGUREES` : dit quoi déclarer et la commande. Aucune équipe, aucun dépôt, aucun quart ni aucune durée n'est inventé. |
| Profil écrit mais invalide (équipe sans membre, quart mal formé, clé inconnue comme `salaire`, personne dans deux équipes…) | `REJ-PROFIL-INVALIDE` avec la raison, **jamais lu comme absent** ; `opsys-metier verifier` le signale. Le schéma est FERMÉ : aucune donnée de ressources humaines, de santé ni d'évaluation. |
| Durée pour un service que l'entreprise ne déclare pas | `opsys-metier verifier` la signale. |

M4 s'en sert de trois façons : `m4_proposer_cedule` lit équipes, durées, compétences, réglages et fenêtre par défaut sans
argument (un argument donné est une SURCHARGE, tracée : la provenance de chaque valeur est rendue et gardée au maillon
du plan) ; l'admissibilité d'une équipe pour un service est CALCULÉE par le code (toutes les compétences du service, et
au moins un quart assez long pour sa durée : `admissibilite.py`) et devient le volet « équipe » de
`m4_verifier_preparation` ; les membres d'une équipe agissent sur les interventions assignées à leur équipe
([ROLES](ROLES.md), « Les équipes du profil de l'entreprise »). Les leads v1 (gelés) n'ont pas de service : leurs durées et
compétences par type de travaux restent des arguments. Détail : README de M4.

## Règles météo, fuseau et fournisseur de prévisions (PLAN T4.13)

Le même profil porte la météo : `opsys.meteo` (module frère de `opsys.equipes`, même fichier, même écriture signée au
journal d'audit). Les SEUILS ne sont pas ceux du code : un revêtement ne craint pas le vent comme une gouttière, et c'est
le propriétaire qui décide (GATE NATHAN) ; **aucune valeur par défaut**.

```yaml
meteo:
  fuseau: America/Toronto        # fuseau des créneaux ; requis dès qu'un fournisseur est ouvert
  fournisseur: msc_geomet        # msc_geomet ou open_meteo ; absent : prévision saisie à la main SEULEMENT (défaut)
  services:                      # par code de service DÉCLARÉ
    revetement:
      seuils:                    # mesure -> {validation, blocage} ; au moins l'un des deux ; nombres entiers
        vent_kmh: {validation: 30, blocage: 45}          # vent moyen horaire, >= seuil
        pluie_mm_h: {blocage: 3}                         # précipitations horaires (mm), >= seuil
        gel_c: {blocage: 0}                              # température minimale, <= seuil
        verglas: {blocage: true}                         # précipitations verglaçantes prévues
        chaleur_c: {blocage: 35}                         # température maximale, >= seuil
      sans_objet: []             # risques que l'entreprise déclare SANS OBJET pour ce service
```

Cinq risques (vent, pluie, gel, verglas, chaleur). Pour chaque service, chacun est JUGÉ (au moins une mesure dans `seuils` :
`vent_kmh`, `rafales_kmh` pour le vent ; `pluie_mm_h`, `pluie_probabilite_pct` pour la pluie ; `gel_c` ; `verglas` ;
`chaleur_c`) ou déclaré `sans_objet` ; un risque sans décision n'est jamais « sans risque » : le verdict du créneau reste
« inconnu » et dit « seuil à configurer ». `opsys-metier meteo lister` montre le profil et ce qu'il reste à décider ; `opsys-metier meteo
declarer --depuis meteo.yaml --par nathan` REMPLACE la clé entière par le contenu validé du fichier, signée au journal
(services, fournisseur, empreinte : jamais la clé d'API).

| Situation | Verdict |
|---|---|
| Aucun profil météo | `REJ-METEO-NON-CONFIGUREE` : dit quoi déclarer et la commande. Le volet « météo » de `m4_verifier_preparation` manque, et la cédule ne prend pas l'intervention. |
| Profil écrit mais invalide (seuil mal ordonné, mesure inconnue, fournisseur inconnu, forfait non commercial…) | `REJ-PROFIL-INVALIDE` avec la raison, **jamais lu comme absent** ; `opsys-metier verifier` le signale. |
| Service sans règles, ou risque sans décision | Le volet « météo » de la préparation manque (« seuil à configurer pour le service … »). |

**Le fournisseur est fermé par défaut** : sans clé `fournisseur`, aucune requête ne part jamais et l'admin saisit la
prévision (`previsions_saisies` de `m4_verifier_meteo_creneau`, sa source et son heure citées). MSC GeoMet (licence de
données ECCC v2.1.1, usage commercial permis, attribution rendue à chaque résultat) s'ouvre par `fournisseur: msc_geomet` ;
il ne donne ni rafales, ni quantité de précipitations, ni verglas fiable : les règles qui les demandent restent « inconnu ».
Open-Meteo (API gratuite réservée à un usage non commercial) ne s'ouvre qu'avec `open_meteo: {forfait: commercial, cle_env:
NOM_DE_VARIABLE}` ET la clé d'API dans cette variable d'environnement : décision du propriétaire. Conditions lues le
2026-09-29 : `docs/research/INGREDIENTS.md`. Seule la position générale d'un chantier (dixième de degré) quitte le serveur
(Loi 25). M4 s'en sert pour le volet « météo » de la préparation (les règles du service existent : la préparation n'a pas
de date, elle ne promet pas le beau temps) et pour `m4_verifier_meteo_creneau` (la prévision d'un créneau contre les
seuils). Détail : README de M4.

## Reste à faire

- Demande de chiffrage M1→M3 (`m1-demande-chiffrage.v1.yaml`) : v2 à publier.
- Règle de précédence entre services (« réparation de gouttières ») : décision du propriétaire (T2.1).
- Barèmes et estimateurs par service (T2.3, M3.8).
- Quarts par jour de la semaine et calendrier : le profil des équipes garde le `jour` numéroté du solveur (M4 ne tient
  pas encore de calendrier : `m4_verifier_meteo_creneau` reçoit `{jour: date}` de l'appelant) ; véhicules et équipements
  ne sont pas modélisés.
