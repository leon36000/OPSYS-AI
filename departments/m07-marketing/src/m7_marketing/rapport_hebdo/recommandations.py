"""Recommandations du rapport hebdomadaire : des RÈGLES lisibles, chacune liée à une donnée ou marquée hypothèse.

Chaque recommandation naît d'une règle nommée (`regle`) appliquée à une section du rapport. Elle porte :

  - `sources` : les données qui la fondent (`{type, ref, valeur}` : mesure de M8, contenu mesuré, observation de
  croissance,
    section de M7). Une recommandation SANS source doit être marquée `hypothese: true` : sinon elle est refusée à la
    construction (`ValueError`) — aucune recommandation flottante. Chaque source doit exister dans
    `rapport["references"]`
    (`verifier_liaison`) ;
  - `priorite` = `impact` × `facilite` (entiers de 1 à 5, 1 à 25) : l'ordre est déterministe (priorité décroissante,
  puis
    règle, puis identifiant) ; aucun modèle ne classe ;
  - `tache` : vrai si la recommandation devient une tâche interne de niveau bas (`TACHES_MAX` au plus par semaine).

Jamais d'achat d'abonnés, de faux engagement ni de spam : les actions de croissance passent la garde
`croissance.verifier_legitimite`. Une recommandation ne déclenche rien : ni publication, ni dépense, ni envoi.

Module pur.
"""

from __future__ import annotations

from typing import Any

from . import croissance

TACHES_MAX = 5
RECOMMANDATIONS_MAX = 12
TYPES_SOURCE = ("mesure_m8", "contenu_m8", "observation_growth", "section_m7")
_INSUFFISANT = ("donnees_insuffisantes", "source_absente")
BAISSE_PCT = -10  # une série qui baisse d'au moins 10 % entre deux observations est signalée


def _source(type_: str, ref: str, valeur: Any = None) -> dict[str, Any]:
    if type_ not in TYPES_SOURCE:
        raise ValueError(f"type de source inconnu : {type_}")
    return {"type": type_, "ref": ref, "valeur": None if valeur is None else str(valeur)}


def _rec(
    regle: str,
    cle: str,
    action: str,
    impact: int,
    facilite: int,
    sources: list[dict[str, Any]],
    *,
    hypothese: bool = False,
    tache: bool = True,
) -> dict[str, Any]:
    if not 1 <= impact <= 5 or not 1 <= facilite <= 5:
        raise ValueError("impact et facilité : entiers de 1 à 5")
    if not sources and not hypothese:
        raise ValueError(f"recommandation {regle} sans source : elle doit être marquée hypothèse")
    if not croissance.verifier_legitimite(action):
        raise ValueError(f"recommandation {regle} : tactique non légitime refusée")
    return {
        "id": f"{regle}:{cle}" if cle else regle,
        "regle": regle,
        "action": action,
        "impact": impact,
        "facilite": facilite,
        "priorite": impact * facilite,
        "hypothese": hypothese,
        "sources": sources,
        "tache": tache,
    }


def deriver(rapport: dict[str, Any]) -> list[dict[str, Any]]:
    """Les recommandations du rapport (sans la clé `recommandations` elle-même), priorisées, au plus
    `RECOMMANDATIONS_MAX`."""
    recs: list[dict[str, Any]] = []
    mesures = rapport["mesures_m8"]
    if mesures["statut"] == "source_absente":
        recs.append(
            _rec(
                "entrepot_m8_absent",
                "",
                "Vérifier que l'entrepôt de M8 est construit et à jour : sans lui, le coût par lead et les "
                "mesures marketing manquent au rapport.",
                3,
                4,
                [],
                hypothese=True,
            )
        )
    cout = rapport["cout_par_lead"]
    if cout["statut"] == "donnees_insuffisantes":
        source = cout["cout_par_lead_pub_cad"]
        recs.append(
            _rec(
                "cout_par_lead_non_calculable",
                "",
                "Déclarer la correspondance des canaux publicitaires et importer les relevés de "
                "dépense pour que M8 puisse calculer un coût par lead.",
                3,
                3,
                [_source("mesure_m8", "m8_cout_par_lead_pub_cad", source["statut"] if source else "absente")]
                if source
                else [],
                hypothese=source is None,
            )
        )
    perimees = sorted(
        i for i, m in mesures.get("mesures", {}).items() if m["fraicheur"] in ("perime", "inconnu", "manquant")
    )
    if perimees:
        recs.append(
            _rec(
                "mesures_m8_perimees",
                "",
                f"Rafraîchir les sources des mesures périmées ou manquantes de M8 ({len(perimees)}).",
                2,
                4,
                [_source("mesure_m8", i, mesures["mesures"][i]["fraicheur"]) for i in perimees[:5]],
                tache=False,
            )
        )
    contenus = rapport["contenus"]
    if contenus.get("sans_lien_de_suivi", 0) + contenus.get("cle_ambigue", 0) > 0 and contenus.get("sans_lien_ids"):
        n = contenus["sans_lien_de_suivi"] + contenus["cle_ambigue"]
        recs.append(
            _rec(
                "contenus_sans_lien_de_suivi",
                "",
                f"Renseigner l'adresse du site dans le profil de marque : {n} contenu(s) exporté(s) "
                "n'ont aucun lien de suivi, donc aucun lead ne peut leur être attribué.",
                4,
                5,
                [_source("contenu_m8", i, "sans_lien") for i in contenus["sans_lien_ids"]],
            )
        )
    for c in contenus.get("meilleurs", [])[:2]:
        recs.append(
            _rec(
                "contenu_gagnant",
                str(c["utm_content"]),
                f"Reproduire l'angle du contenu {c['canal']} (clé {c['utm_content']}) pour le prochain chantier : "
                f"{c['leads']} lead(s) attribué(s).",
                4,
                4,
                [_source("contenu_m8", str(c["utm_content"]), c["leads"])],
            )
        )
    for c in contenus.get("faibles", [])[:2]:
        recs.append(
            _rec(
                "contenu_faible",
                str(c["utm_content"]),
                f"Revoir le contenu {c['canal']} (clé {c['utm_content']}) : {rapport['contenus']['regle_faible']} ; "
                "vérifier le lien de suivi et l'appel à l'action avant de conclure.",
                3,
                4,
                [_source("contenu_m8", str(c["utm_content"]), c["leads"])],
                hypothese=True,
            )
        )
    canaux = rapport["leads_par_canal"].get("canaux", [])
    inconnus = [c for c in canaux if c["canal"] == "inconnu" and c["leads"] > 0]
    if inconnus:
        recs.append(
            _rec(
                "leads_sans_canal",
                "",
                f"Ajouter des liens de suivi (utm_source et utm_campaign) : {inconnus[0]['leads']} lead(s) "
                "n'ont pas de canal connu.",
                4,
                4,
                [_source("section_m7", "performance", inconnus[0]["leads"])],
            )
        )
    reputation = rapport["reputation"]
    if reputation["statut"] == "calcule":
        if reputation["negatifs_sans_reponse"] > 0:
            recs.append(
                _rec(
                    "avis_negatifs_sans_reponse",
                    "",
                    f"Préparer la réponse aux {reputation['negatifs_sans_reponse']} avis négatif(s) "
                    "sans réponse (publication soumise à la validation d'une personne).",
                    5,
                    4,
                    [_source("section_m7", "reputation", reputation["negatifs_sans_reponse"])],
                )
            )
        elif reputation["sans_reponse"] > 0:
            recs.append(
                _rec(
                    "avis_sans_reponse",
                    "",
                    f"Répondre aux {reputation['sans_reponse']} avis sans réponse (validation humaine).",
                    2,
                    5,
                    [_source("section_m7", "reputation", reputation["sans_reponse"])],
                )
            )
    calendrier = rapport["calendrier"]
    if calendrier["statut"] == "calcule":
        if calendrier["creneaux_semaine"] == 0 and calendrier["exportes_semaine"] == 0:
            recs.append(
                _rec(
                    "calendrier_vide",
                    "",
                    "Aucun contenu planifié ni exporté durant la semaine : planifier au moins un contenu "
                    "cette semaine.",
                    3,
                    5,
                    [_source("section_m7", "calendrier", 0)],
                )
            )
        if calendrier["en_attente_de_decision"] > 0:
            recs.append(
                _rec(
                    "contenus_en_attente",
                    "",
                    f"Décider les {calendrier['en_attente_de_decision']} contenu(s) en attente d'approbation.",
                    3,
                    5,
                    [_source("section_m7", "calendrier", calendrier["en_attente_de_decision"])],
                )
            )
    baisses = 0
    for s in rapport["croissance_engagement"].get("series", []):
        v = s["variation"]
        if v and v["pct"] is not None and int(v["pct"]) <= BAISSE_PCT and baisses < 2:
            baisses += 1
            recs.append(
                _rec(
                    "croissance_en_baisse",
                    f"{s['plateforme']}:{s['metrique']}",
                    f"Examiner les contenus récents de {s['plateforme']} : {s['metrique']} en baisse de "
                    f"{abs(int(v['pct']))} % entre les deux dernières observations (cause inconnue).",
                    3,
                    3,
                    [_source("observation_growth", i) for i in s["observation_ids"]],
                    hypothese=True,
                )
            )
    plan = rapport["plan_croissance"]
    for a in plan["actions"][:2]:
        recs.append(
            _rec(
                "action_organique",
                f"{a['plateforme']}:{a['dimension']}:{a['gagnant']}",
                a["action"],
                4,
                3,
                [_source("observation_growth", i) for i in a["observations_source"][:6]],
            )
        )
    if plan["manques"]:
        recs.append(
            _rec(
                "donnees_croissance_manquantes",
                "",
                "Saisir les observations de performance par format, créneau ou série pour dégager "
                "des actions organiques : " + plan["manques"][0],
                2,
                4,
                [],
                hypothese=True,
            )
        )
    recs.sort(key=lambda r: (-r["priorite"], r["regle"], r["id"]))
    recs = recs[:RECOMMANDATIONS_MAX]
    restantes = TACHES_MAX
    for r in recs:  # les tâches sont les mieux classées, au plus TACHES_MAX
        if r["tache"] and restantes > 0:
            restantes -= 1
        else:
            r["tache"] = False
    return recs


def verifier_liaison(rapport: dict[str, Any]) -> list[str]:
    """Les écarts de liaison recommandation ↔ donnée : une recommandation sans source ni hypothèse, une source d'un type
    inconnu ou qui ne figure pas dans `rapport['references']`. Vide si tout est lié."""
    problemes = []
    references = rapport["references"]
    for r in rapport["recommandations"]:
        if not r["sources"] and not r["hypothese"]:
            problemes.append(f"{r['id']} : ni source ni hypothèse")
        for s in r["sources"]:
            if s["type"] not in TYPES_SOURCE:
                problemes.append(f"{r['id']} : type de source inconnu {s['type']}")
            elif s["ref"] not in references.get(s["type"], []):
                problemes.append(f"{r['id']} : source {s['type']}:{s['ref']} absente des références du rapport")
    return problemes
