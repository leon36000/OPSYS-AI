# `m4.capacite_equipe` — capacité des équipes par semaine (contrat v1)

Producteur : M4 (Field Ops), propriétaire du calcul. Lecture pure T0 : outil `m4_lire_capacite_equipe`
(`src/m4_field_ops/capacite_equipe.py`, calcul pur ; adaptateur dans `outils.py`). Données fictives dans les tests.
Aucun grant nouveau : `roles_appareil` vide (aucun appareil), appel d'agent comme les autres lectures T0 ; un admin
d'appareil est refusé par le core, un employé ou un vendeur par le double contrôle de l'outil.

## Ce que la valeur veut dire

* `heures_disponibles` : les heures des **quarts déclarés** du profil des équipes (`opsys.equipes`, `fin_min - debut_min`),
  une fois par **journée datée** de la semaine. `heures_planifiees` : la durée des créneaux de la cédule **appliquée** dont
  la date est confirmée (`m4_confirmer_dates_cedule`).
* Unité fermée `heures_declarees` : heures d'horloge du quart d'une équipe (une équipe = une unité de cédule), **jamais**
  des heures-personnes ni des jours-personnes. Aucune conversion ; un lecteur refuse toute autre unité.
* **Déclaration d'équipe ≠ présence individuelle.** Les membres ne sont ni lus ni comptés ni écrits ; aucune absence
  signalée, aucun pointage, aucune position n'est déduit ; le profil ne porte aucun congé. Un quart partiel est un quart
  plus court dans le profil.
* `portee: "journees_datees_seulement"` : le `jour` d'un quart est un numéro de journée de plan, pas un jour de semaine
  (le profil n'a pas de calendrier hebdomadaire). Seules les journées datées par un admin relient ce numéro à une date.
  Le chiffre est donc une **borne basse de la capacité ouverte**, pas la capacité totale de la semaine.
* Absence ≠ zéro, tout ou rien : un seul manque rend la semaine non calculable pour toutes les équipes.

## Charge

```json
{
  "contrat": "m4.capacite_equipe", "version": 1,
  "semaine_debut": "2030-06-03", "fuseau": "America/Montreal",
  "unite": "heures_declarees", "portee": "journees_datees_seulement",
  "calculable": true, "manque": [],
  "equipes": [{"equipe_id": "eq-a", "heures_disponibles": "9.00", "heures_planifiees": "5.00",
               "minutes_disponibles": 540, "minutes_planifiees": 300}],
  "heures_disponibles": "18.00", "heures_planifiees": "5.00", "minutes_disponibles": 1080, "minutes_planifiees": 300,
  "jours_dates": ["2030-06-03"],
  "lu_a": "2030-06-02T09:30:00-04:00",
  "sources": {"profil_empreinte": "<sha256>", "registre_tete": "<ligne_id>", "plans_appliques": 1,
              "plans_proposes_non_appliques": 0, "cedule_revision_max": 1, "cedule_confirmee_le": "<ISO 8601>"},
  "avertissements": ["..."]
}
```

Arguments : `debut_semaine` (lundi, AAAA-MM-JJ, obligatoire), `horodatage_reference` (ISO 8601 avec fuseau, facultatif :
recopié en `lu_a`, M4 n'a pas d'horloge). Heures en texte décimal (minutes/60 arrondi au dix-millième, au moins deux
décimales) ; les `minutes_*` entières exactes sont écrites à côté. Une semaine ou un instant invalide est un refus
(`REJ-CONTRAT-INVALIDE`), jamais une capacité.

Non calculable : `calculable: false`, `equipes: []`, aucun total ni valeur, `manque` non vide (codes fermés) :

| Code | Cause |
|---|---|
| `profil_equipes_non_declare` / `profil_equipes_invalide` / `profil_sans_equipes` | profil absent, illisible, ou sans équipe |
| `cedule_non_appliquee` | aucun plan appliqué (une proposition n'est pas une cédule) |
| `aucune_journee_datee_dans_la_semaine` | aucune journée de la semaine datée par un admin |
| `interventions_planifiees_sans_date:N` | N interventions actives du carnet sans date : leur semaine est inconnue |
| `creneaux_a_reconfirmer:N` | N créneaux de la semaine dont la date n'est plus valide (équipe réassignée, etc.) |
| `quart_ambigu:<équipe>:<date>` | une même date reliée à deux numéros de journée aux quarts différents |
| `equipe_planifiee_non_declaree:<équipe>` | une équipe porte des créneaux mais n'est plus au profil |

Seuls ces codes, des identifiants déjà validés et des dates ISO sortent : jamais un nom d'équipe libre ni un détail de
verdict (un identifiant d'équipe mal formé n'est pas recopié). Un plan appliqué qui ne détient plus aucune
intervention ne date plus rien. Les créneaux annulés, reportés ou à replanifier ne comptent pas et ne sont pas un manque.

## Ce que le lecteur (M9) doit faire

Refuser toute unité autre que `heures_declarees`, lire `calculable` avant tout chiffre, nommer `portee` (borne basse) et
l'âge via `lu_a`/`sources`, ne jamais convertir en jours-personnes ni déduire une présence. `verifier_charge` (module M4)
rejoue ces contrôles côté producteur.
