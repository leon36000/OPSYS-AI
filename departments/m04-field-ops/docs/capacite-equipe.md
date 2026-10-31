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
  signalée, aucun pointage, aucune position n'est déduit. Seuls les congés d'**équipe** et les fériés déclarés au profil
  sont soustraits (portée `semaine_type`). Un quart partiel est un quart plus court dans le profil.
* `portee: "journees_datees_seulement"` (défaut, inchangée) : le `jour` d'un quart est un numéro de journée de plan, pas
  un jour de semaine. Seules les journées datées par un admin relient ce numéro à une date. Le chiffre est donc une
  **borne basse de la capacité ouverte**, pas la capacité totale de la semaine. La semaine type et les congés n'y
  changent rien.
* `portee: "semaine_type"` (argument `portee`, DECISIONS-ARCHITECTE-r1 §3) : calculable pour une **semaine future non
  datée**. Pour chaque jour civil, les plages de la semaine type de l'équipe pour ce jour de semaine (heures locales
  America/Montreal, **durée écoulée réelle** : 25 h pour 00:00-24:00 le jour du retour à l'heure normale), sauf un férié
  déclaré (toutes les équipes) ou un congé de l'équipe : zéro déclaré ce jour-là. Un jour fermé (`[]`) est un zéro
  déclaré ; un jour absent est inconnu. `heures_planifiees` suit la même règle que la portée datée (créneaux datés de la
  cédule appliquée) : une intervention active sans date reste un manque, car sa semaine est inconnue.
* Jours-personnes, **seulement** si le profil déclare `duree_jour_personne_minutes` (jamais supposé) et que la semaine
  est calculable, dans les deux portées (`Decimal`, dix-millième, demi vers le haut, au moins deux décimales ;
  `duree_jour_personne_minutes` et les minutes exactes sont écrites à côté). L'unité de la charge reste
  `heures_declarees` : l'heure d'**équipe** est l'unité de référence, les jours-personnes en sont une conversion
  déclarée (DECISIONS-ARCHITECTE-r3) :
  * équipe qui déclare `effectif_planifie` (profil, entier 1 à 50) : `jours_personnes_*` = minutes de l'équipe ×
    effectif planifié / durée. L'effectif est une **capacité prévisionnelle déclarée, jamais une présence constatée** :
    il n'est ni lu ni déduit des membres déclarés (une équipe de 2 membres peut en prévoir 3), des pointages ou des
    absences ;
  * équipe sans effectif déclaré : `effectif_planifie: null` sur sa ligne — **dit**, jamais un 1 supposé — et
    `jours_personnes_*` = minutes / durée, sans multiplication (le calcul d'avant) : des jours de quart d'équipe ;
  * `jours_personnes_base` (racine, code fermé) dit la règle de la charge : `effectif_planifie_declare` (toutes les
    équipes), `effectif_non_declare` (aucune) ou `effectif_partiellement_declare` (certaines) ; dans ce dernier cas
    chaque équipe garde sa conversion et les totaux `jours_personnes_*` de la racine valent `null` (jours de personnes
    et jours d'équipe ne s'additionnent pas ; les heures, elles, restent totalisées). Deux avertissements de plus
    expliquent la conversion et la base retenue.

  Pourquoi `null` plutôt qu'un 1 implicite : `effectif_planifie: 1` est une **déclaration** (« une personne prévue »),
  que le propriétaire peut faire ; l'absence de déclaration n'en est pas une. Écrire 1 donnerait le même chiffre mais
  ferait passer des jours d'équipe pour des jours de personnes prévues. Un lecteur qui trouve 1 avec la base
  `effectif_non_declare` refuse la charge.
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

Avec `duree_jour_personne_minutes: 480` déclaré et aucun effectif planifié, la charge calculable porte en plus
`"duree_jour_personne_minutes": 480, "jours_personnes_base": "effectif_non_declare", "jours_personnes_disponibles":
"2.25", "jours_personnes_planifiees": "0.625"` (à la racine) et `effectif_planifie: null`, `jours_personnes_disponibles` /
`jours_personnes_planifiees` sur chaque équipe. Si `eq-a` déclare `effectif_planifie: 2` et `eq-b` `effectif_planifie:
3` : `eq-a` porte `"effectif_planifie": 2, "jours_personnes_disponibles": "2.25"` (540 × 2 / 480), `eq-b`
`"3.375"`, la racine `"jours_personnes_base": "effectif_planifie_declare", "jours_personnes_disponibles": "5.625"`
((1080 + 1620) / 480) ; les heures et minutes ne changent pas. Sans la durée, aucune de ces clés n'existe, effectif
déclaré ou non (la charge est identique à celle d'avant).

Arguments : `debut_semaine` (lundi, AAAA-MM-JJ, obligatoire), `horodatage_reference` (ISO 8601 avec fuseau, facultatif :
recopié en `lu_a`, M4 n'a pas d'horloge), `portee` (`journees_datees_seulement` par défaut, ou `semaine_type` ; toute
autre valeur est refusée par le schéma de l'outil). Heures en texte décimal (minutes/60 arrondi au dix-millième, au moins deux
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
| `semaine_type_non_declaree:<équipe>` | portée `semaine_type` : l'équipe n'a pas de semaine type |
| `semaine_type_jour_non_declare:<équipe>:<jour>` | portée `semaine_type` : ce jour de semaine est absent (inconnu, pas fermé) |
| `feries_non_declares:<année>` | portée `semaine_type` : la liste des fériés de cette année n'est pas déclarée complète |
| `heure_locale_ambigue:<équipe>:<date>` | portée `semaine_type` : une plage commence ou finit sur une heure sautée ou répétée |

`aucune_journee_datee_dans_la_semaine` ne s'applique qu'à la portée datée. Les libellés de congé et de férié ne sortent
jamais : seuls les codes, les identifiants d'équipe, les noms de jour fermés et les dates ISO.

Seuls ces codes, des identifiants déjà validés et des dates ISO sortent : jamais un nom d'équipe libre ni un détail de
verdict (un identifiant d'équipe mal formé n'est pas recopié). Un plan appliqué qui ne détient plus aucune
intervention ne date plus rien. Les créneaux annulés, reportés ou à replanifier ne comptent pas et ne sont pas un manque.

## Ce que le lecteur (M9) doit faire

Refuser toute unité autre que `heures_declarees` et toute portée hors des deux admises, vérifier que la portée rendue
est celle demandée, lire `calculable` avant tout chiffre, nommer `portee` (borne basse datée, ou semaine type déclarée)
et l'âge via `lu_a`/`sources`, ne jamais convertir lui-même en jours-personnes (seuls les `jours_personnes_*` écrits par
M4 sur déclaration existent) ni déduire une présence ni un effectif. Il refait la conversion annoncée pour refuser une
charge incohérente : effectif hors de 1 à 50 ou non entier, jours qui ne valent pas minutes × effectif / durée (ou
minutes / durée si `null`), base qui contredit les effectifs, total converti écrit en base partielle ou manquant
ailleurs. `verifier_charge` (module M4) rejoue ces contrôles côté producteur.
