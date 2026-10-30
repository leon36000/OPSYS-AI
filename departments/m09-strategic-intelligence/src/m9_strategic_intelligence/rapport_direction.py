"""Les vingt sections de direction des revues hebdomadaire, mensuelle et trimestrielle M9.6–7.

Module pur et déterministe. Une revue de direction répond, section par section, à ce que le cahier de direction exige
(résumé, revenus et cash, pipeline, estimations, production, inventaire, marketing, clients, risques, occasions, ce qui
a fonctionné ou échoué, leçons, décisions à prendre, plan de la semaine suivante, objectifs mesurables, actions par
département, prévisions à 4 et 13 semaines, recommandations) — avec les règles de M9 :

* chaque section est calculée à ``fin`` de période, sur ce que M9 savait alors : une revue publiée reste vraie pour
  toujours ; ce qui arrive ensuite fait une version suivante ;
* un contenu est un FAIT CITÉ (adresse + valeur textuelle exacte d'une capture complète), un DÉNOMBREMENT de ce que M9
  tient, ou l'état d'un registre de M9 (plans, actions, expériences, conseils) ; aucune quantité n'est calculée ici,
  aucun chiffre d'entreprise n'est produit ;
* une section sans matière dit ``NON_DISPONIBLE`` avec ce qui manque et qui le possède ; ``PARTIELLE`` quand une partie
  seulement est renseignée ; jamais une valeur par défaut ni un zéro ;
* « ce qui a fonctionné » et « ce qui a échoué » ne reprennent que des résultats MESURÉS chez leurs propriétaires ;
  « leçons apprises » ne reprend que ce qu'une personne a déclaré (contre-exemples, motifs) : M9 n'en déduit aucune.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import experiences as ex
from . import metriques_executives as me
from . import occasions as oc
from . import orchestrateur as orch
from . import plans as pl
from . import previsions as pv
from . import risques as rk

VERSION = "2026-10-29.1"
STATUTS = frozenset({"RENSEIGNEE", "PARTIELLE", "NON_DISPONIBLE"})
MAX_LIGNES = 12
SECTIONS = (
    ("resume", "Résumé de la période"),
    ("revenus_cash_marge", "Revenus, cash et marge"),
    ("pipeline_ventes", "Pipeline et ventes"),
    ("estimations_soumissions", "Estimations et soumissions"),
    ("production_cedule", "Production et cédule"),
    ("inventaire_fournisseurs", "Inventaire et fournisseurs"),
    ("marketing_visibilite", "Marketing et visibilité"),
    ("clients_satisfaction", "Clients et satisfaction"),
    ("risques", "Risques"),
    ("opportunites", "Opportunités"),
    ("ce_qui_a_fonctionne", "Ce qui a fonctionné (mesuré)"),
    ("ce_qui_a_echoue", "Ce qui a échoué (mesuré)"),
    ("lecons_apprises", "Leçons apprises (déclarées)"),
    ("decisions_a_prendre", "Décisions à prendre"),
    ("plan_semaine_suivante", "Plan de la période suivante"),
    ("objectifs_mesurables", "Objectifs mesurables"),
    ("actions_par_departement", "Actions par département"),
    ("previsions_4_semaines", "Prévisions des propriétaires à 4 semaines"),
    ("previsions_13_semaines", "Prévisions des propriétaires à 13 semaines"),
    ("recommandations", "Recommandations stratégiques"),
)
IDS = tuple(i for i, _ in SECTIONS)
_PAR_THEME = {
    "revenus_cash_marge": {
        "indicateurs": ("revenue", "gross_margin", "net_margin", "cash_free_real", "job_profitability"),
        "lectures": (
            "m5.prevision_tresorerie",
            "m5.rentabilite_chantier",
            "m5.comptes_a_recevoir",
            "m5.comptes_a_payer",
        ),
        "domaines": ("cash", "qualite"),
    },
    "pipeline_ventes": {
        "indicateurs": ("pipeline_value", "qualified_lead", "conversion_rate"),
        "lectures": ("m2.leads", "m2.relances"),
        "domaines": (),
    },
    "estimations_soumissions": {
        "indicateurs": ("estimate_to_quote_rate", "quote_to_win_rate"),
        "lectures": ("m3.ecarts", "m8.vue_executive"),
        "domaines": (),
    },
    "production_cedule": {
        "indicateurs": ("team_capacity",),
        "lectures": ("m4.interventions", "m4.cedule_semaine", "m4.retards_incidents", "m4.meteo_intervention"),
        "domaines": ("capacite", "meteo"),
    },
    "inventaire_fournisseurs": {
        "indicateurs": ("inventory_readiness",),
        "lectures": ("m6.disponibilite",),
        "domaines": ("materiaux",),
    },
    "marketing_visibilite": {
        "indicateurs": ("marketing_roi", "cost_per_lead", "cost_per_sale"),
        "lectures": ("m7.performance_campagnes",),
        "domaines": (),
    },
    "clients_satisfaction": {
        "indicateurs": ("customer_satisfaction",),
        "lectures": ("m1.digest",),
        "domaines": (),
    },
}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _section(identifiant: str, statut: str, contenu: Mapping | None = None, *, manque: Sequence[str] = ()) -> dict:
    titre = dict(SECTIONS)[identifiant]
    return {
        "id": identifiant,
        "titre": titre,
        "statut": statut,
        "contenu": dict(contenu or {}),
        "manques": list(manque),
    }


def _avant(chaine: Sequence[Mapping], fin: dt.datetime) -> list[Mapping]:
    """Événements d'un registre reçus avant ``fin`` (un instant illisible est rejeté : jamais compté à tort)."""
    gardes = []
    for evenement in chaine:
        instant = cs.instant(evenement.get("recu_a", ""))
        if instant is not None and instant <= fin:
            gardes.append(evenement)
    return gardes


def _dans(valeur: str, periode: Mapping) -> bool:
    instant = cs.instant(valeur)
    return instant is not None and cs.instant(periode["debut"]) <= instant < cs.instant(periode["fin"])  # type: ignore[operator]


def _decimal(texte: object) -> Decimal | None:
    try:
        return Decimal(texte) if isinstance(texte, str) else None
    except InvalidOperation:
        return None


def _theme(identifiant, theme, indicateurs, couverture, radar) -> dict:
    voulus = [i for i in indicateurs if i["id"] in theme["indicateurs"]]
    lectures = [
        {"lecture_id": e["lecture_id"], "statut": e["statut"]}
        for e in couverture["lectures"]
        if e["lecture_id"] in theme["lectures"]
    ]
    risques = [
        {k: r[k] for k in ("regle", "sujet", "gravite", "statut")}
        for r in radar["risques"]
        if r["domaine"] in theme["domaines"] and r["statut"] != "LEVE"
    ]
    cites = [i for i in voulus if i.get("lignage") == "FAITS_CITES"]
    manques = [
        f"{i['id']} : aucune définition officielle chez le propriétaire ({i['proprietaire']})"
        for i in voulus
        if i["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE"
    ] + [f"{e['lecture_id']} : {e['statut']}" for e in lectures if e["statut"] != "PRESENTE"]
    contenu = {
        "indicateurs": [
            {
                "id": i["id"],
                "statut_definition": i["statut_definition"],
                "faits": i.get("faits", [])[:3],
                "lignage": i.get("lignage"),
            }
            for i in voulus
        ],
        "lectures": lectures,
        "risques_signales": risques[:MAX_LIGNES],
    }
    if cites or risques:
        statut = "RENSEIGNEE" if cites and not manques else "PARTIELLE"
    elif any(e["statut"] == "PRESENTE" for e in lectures):
        statut = "PARTIELLE"
    else:
        statut = "NON_DISPONIBLE"
    return _section(identifiant, statut, contenu, manque=manques)


def _vue_plans(plans, visibles, fin, jour_fin):
    return pl.vue(_avant(plans, fin), visibles, connaissance=_iso(fin), jour=jour_fin)["plans"]


def _iso(instant: dt.datetime) -> str:
    return instant.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sections(
    *,
    captures: Sequence[Mapping],
    sessions: Sequence[Mapping],
    plans: Sequence[Mapping] = (),
    actions: Sequence[Mapping] = (),
    experiences: Sequence[Mapping] = (),
    periode: Mapping,
) -> dict:
    """Les vingt sections de la période, à sa fin : ``{"ids": [...], "sections": {id: section}}``."""
    fin = cs.instant(periode["fin"])
    if fin is None:
        raise _refus("REJ-DIRECTION-PERIODE", "période sans fin lisible")
    fin_iso = _iso(fin)
    jour_fin = (dt.date.fromisoformat(periode["fin_local"]) - dt.timedelta(days=1)).isoformat()
    jour_suivant_fin = dt.date.fromisoformat(periode["fin_local"])
    visibles = cs.connues_a(captures, fin_iso)
    sessions_vues = [e for e in sessions if (cs.instant(e["recu_a"]) or fin) <= fin]
    radar = rk.evaluer(visibles, connaissance=fin_iso)
    couverture = cs.evaluer_couverture(
        visibles,
        reference=fin_iso,
        connaissance=fin_iso,
        attendues=[lecture for t in _PAR_THEME.values() for lecture in t["lectures"]],
    )
    indicateurs = me.lignage(visibles, connaissance=fin_iso)["indicateurs"]
    vue_plans = _vue_plans(plans, visibles, fin, jour_fin)
    chaine_actions = _avant(actions, fin)
    etat_actions = sorted(orch.etat(chaine_actions).values(), key=lambda a: a["action_id"])
    vue_exp = ex.vue(_avant(experiences, fin), visibles, connaissance=fin_iso)["experiences"]
    resultats: dict[str, dict] = {}

    # 2–8 : un thème par propriétaire, uniquement des faits cités et des manques nommés
    for identifiant, theme in _PAR_THEME.items():
        resultats[identifiant] = _theme(identifiant, theme, indicateurs, couverture, radar)

    # 9 risques
    refusees = [
        e for e in sessions_vues if e["type"] == "TOUR" and e.get("issue") == "REFUSE" and _dans(e["recu_a"], periode)
    ]
    presents = [r for r in radar["risques"] if r["statut"] != "LEVE"]
    par_gravite: dict[str, int] = {}
    for r in presents:
        par_gravite[r["gravite"]] = par_gravite.get(r["gravite"], 0) + 1
    resultats["risques"] = _section(
        "risques",
        "RENSEIGNEE" if presents else "PARTIELLE" if radar["regles_non_evaluees"] else "NON_DISPONIBLE",
        {
            "presents": len(presents),
            "par_gravite": par_gravite,
            "leves": sum(1 for r in radar["risques"] if r["statut"] == "LEVE"),
            "premiers": [
                {**{k: r[k] for k in ("regle", "sujet", "gravite", "statut")}, "preuve": r["preuves"][0]}
                for r in presents[:MAX_LIGNES]
            ],
            "grille": radar["grille"]["statut"],
            "origine_etablie": False,
            "signaux_de_m9": {
                "sorties_de_modele_refusees": len(refusees),
                "par_code": {
                    c: sum(1 for e in refusees if e.get("code") == c)
                    for c in sorted({e.get("code") for e in refusees if e.get("code")})
                },
                "lectures_attendues_non_presentes": len(couverture["lectures_non_presentes"]),
                "contradictions": len(couverture["contradictions"]),
            },
        },
        manque=[
            f"{n['regle']} : règle non évaluée ({n['raison']}), risque inconnu et non nul"
            for n in radar["regles_non_evaluees"]
        ],
    )

    # 10 opportunités : signaux mesurés par les propriétaires seulement
    signaux = oc.signaux_mesures(visibles, connaissance=fin_iso)
    resultats["opportunites"] = _section(
        "opportunites",
        "RENSEIGNEE" if signaux else "NON_DISPONIBLE",
        {
            "signaux_mesures": signaux[:MAX_LIGNES],
            "occasions_declarees": "voir m9_radar_occasions (déclarées par une personne)",
        },
        manque=[]
        if signaux
        else ["aucun signal mesuré par un propriétaire ; les occasions se déclarent avec leurs sources"],
    )

    # 11–12 fonctionné / échoué : résultats mesurés seulement
    atteints = [
        {"plan_id": p["plan_id"], "objectif": p["objectif"], "porteur": p["porteur"]}
        for p in vue_plans
        if p["statut"] == "ATTEINT_MESURE"
    ]
    exp_positives = [
        {
            "experience_id": e["experience_id"],
            "gain_mesure": e["evaluation"]["gain_mesure"],
            "inference": e["evaluation"]["inference"],
        }
        for e in vue_exp
        if (g := _decimal(e["evaluation"]["gain_mesure"])) is not None and g > 0
    ]
    resultats["ce_qui_a_fonctionne"] = _section(
        "ce_qui_a_fonctionne",
        "RENSEIGNEE" if atteints or exp_positives else "NON_DISPONIBLE",
        {"plans_atteints_mesures": atteints[:MAX_LIGNES], "experiences_a_gain_positif": exp_positives[:MAX_LIGNES]},
        manque=[]
        if atteints or exp_positives
        else ["aucun résultat mesuré favorable : un suivi déclaré n'est pas un résultat"],
    )
    en_retard = [
        {"plan_id": p["plan_id"], "objectif": p["objectif"], "echeance": p["echeance"]}
        for p in vue_plans
        if p["statut"] == "EN_RETARD"
    ]
    non_satisfaits = [
        {"plan_id": p["plan_id"], "resultat_id": r["id"]}
        for p in vue_plans
        for r in p["resultats_cles"]
        if r["mesure"].get("statut") == "NON_SATISFAIT"
    ]
    exp_negatives = [
        {"experience_id": e["experience_id"], "gain_mesure": e["evaluation"]["gain_mesure"]}
        for e in vue_exp
        if (g := _decimal(e["evaluation"]["gain_mesure"])) is not None and g < 0
    ]
    actions_echouees = [
        {"action_id": a["action_id"], "etat": a["etat"], "departement": a.get("departement")}
        for a in etat_actions
        if a["etat"] in ("ECHEC", "REFUSEE")
    ]
    vide12 = not (en_retard or non_satisfaits or exp_negatives or actions_echouees)
    resultats["ce_qui_a_echoue"] = _section(
        "ce_qui_a_echoue",
        "NON_DISPONIBLE" if vide12 else "RENSEIGNEE",
        {
            "plans_en_retard": en_retard[:MAX_LIGNES],
            "resultats_cles_non_satisfaits": non_satisfaits[:MAX_LIGNES],
            "experiences_a_gain_negatif": exp_negatives[:MAX_LIGNES],
            "actions_en_echec_ou_refusees": actions_echouees[:MAX_LIGNES],
        },
        manque=["aucun échec mesuré dans les registres de M9 ; l'absence d'échec connu n'est pas un succès"]
        if vide12
        else [],
    )

    # 13 leçons : seulement ce qu'une personne a déclaré
    lecons = [
        {"experience_id": e["experience_id"], "contre_exemple": c}
        for e in vue_exp
        for c in e["evaluation"]["contre_exemples"]["declares"]
    ] + [{"plan_id": p["plan_id"], "annulation": p["annulation"]} for p in vue_plans if p["annulation"] is not None]
    resultats["lecons_apprises"] = _section(
        "lecons_apprises",
        "RENSEIGNEE" if lecons else "NON_DISPONIBLE",
        {"declarees": lecons[:MAX_LIGNES]},
        manque=[] if lecons else ["aucune leçon déclarée par une personne : M9 n'en déduit aucune"],
    )

    # 14 décisions à prendre
    cloturees = [e for e in sessions_vues if e["type"] == "CLOTURE"]
    a_valider = [
        {
            "session_id": e["session_id"],
            "rapport_id": e["rapport_id"],
            "actions": [
                a["action"]
                for a in (e["gouvernance"] or {}).get("actions", [])
                if a["verdict"] == "VALIDATION_HUMAINE_REQUISE"
            ],
        }
        for e in cloturees
        if e["issue"] == "RECOMMANDATION"
    ]
    a_valider = [e for e in a_valider if e["actions"]]
    en_attente = [
        {
            "action_id": a["action_id"],
            "departement": a.get("departement"),
            "outil": a.get("outil"),
            "demande_id": a.get("demande_id"),
        }
        for a in etat_actions
        if a["etat"] == "EN_ATTENTE_APPROBATION"
    ]
    resultats["decisions_a_prendre"] = _section(
        "decisions_a_prendre",
        "RENSEIGNEE" if a_valider or en_attente else "NON_DISPONIBLE",
        {
            "recommandations_a_valider_par_un_humain": a_valider[:MAX_LIGNES],
            "approbations_natives_en_attente": en_attente[:MAX_LIGNES],
        },
        manque=[] if a_valider or en_attente else ["aucune décision en attente connue de M9"],
    )

    # 15 plan de la période suivante, 16 objectifs mesurables
    suivante = []
    for p in vue_plans:
        if p["statut"] in ("ANNULE", "ATTEINT_MESURE"):
            continue
        echeance = dt.date.fromisoformat(p["echeance"])
        if echeance <= jour_suivant_fin + dt.timedelta(days=7):
            suivante.append(
                {"plan_id": p["plan_id"], "objectif": p["objectif"], "echeance": p["echeance"], "statut": p["statut"]}
            )
    resultats["plan_semaine_suivante"] = _section(
        "plan_semaine_suivante",
        "RENSEIGNEE" if suivante or en_attente else "NON_DISPONIBLE",
        {"plans_a_echeance": suivante[:MAX_LIGNES], "approbations_en_attente": len(en_attente)},
        manque=[] if suivante or en_attente else ["aucun plan à échéance ni action en attente"],
    )
    objectifs = [
        {
            "plan_id": p["plan_id"],
            "resultat_id": r["id"],
            "libelle": r["libelle"],
            "operateur": r["operateur"],
            "cible": r.get("cible"),
            "statut_mesure": r["mesure"].get("statut"),
        }
        for p in vue_plans
        if p["statut"] != "ANNULE"
        for r in p["resultats_cles"]
    ]
    resultats["objectifs_mesurables"] = _section(
        "objectifs_mesurables",
        "RENSEIGNEE" if objectifs else "NON_DISPONIBLE",
        {"resultats_cles": objectifs[: MAX_LIGNES * 2], "total": len(objectifs)},
        manque=[] if objectifs else ["aucun plan déposé : aucun objectif mesurable n'est suivi par M9"],
    )

    # 17 actions par département
    par_dep: dict[str, dict[str, int]] = {}
    for a in etat_actions:
        dep = a.get("departement") or "inconnu"
        par_dep.setdefault(dep, {})
        par_dep[dep][a["etat"]] = par_dep[dep].get(a["etat"], 0) + 1
    resultats["actions_par_departement"] = _section(
        "actions_par_departement",
        "RENSEIGNEE" if par_dep else "NON_DISPONIBLE",
        {"par_departement": {k: par_dep[k] for k in sorted(par_dep)}, "total": len(etat_actions)},
        manque=[] if par_dep else ["aucune action proposée par M9"],
    )

    # 18–19 prévisions des propriétaires (jamais produites par M9)
    consolide = pv.consolider(visibles, connaissance=fin_iso)
    tresorerie = next(d for d in consolide["domaines"] if d["domaine"] == "tresorerie")
    autres = [
        {"domaine": d["domaine"], "statut": d["statut"], "proprietaire": d["proprietaire"]}
        for d in consolide["domaines"]
        if d["domaine"] != "tresorerie"
    ]
    courante = next((v for v in tresorerie.get("versions", []) if v["capture"] == tresorerie.get("courante")), None)
    horizon = _decimal(courante["valeurs"]["horizon_semaines"]) if courante and "valeurs" in courante else None
    for identifiant, semaines in (("previsions_4_semaines", 4), ("previsions_13_semaines", 13)):
        if tresorerie["statut"] in ("DISPONIBLE", "PERIMEE") and horizon is not None and horizon >= semaines:
            resultats[identifiant] = _section(
                identifiant,
                "RENSEIGNEE" if tresorerie["statut"] == "DISPONIBLE" else "PARTIELLE",
                {
                    "tresorerie_m5": {
                        "statut": tresorerie["statut"],
                        "faits": courante["faits"],
                        "age_jours": courante["age_jours"],
                        "reserves": courante["reserves"],
                        "incertitude": tresorerie["incertitude"],
                    },
                    "autres_domaines": autres,
                    "tendances": "m9_projeter_tendance (extrapolation, pas une prévision de propriétaire)",
                },
                manque=[]
                if tresorerie["statut"] == "DISPONIBLE"
                else ["prévision M5 plus ancienne que la péremption demandée"],
            )
        else:
            resultats[identifiant] = _section(
                identifiant,
                "NON_DISPONIBLE",
                {"tresorerie_m5": {"statut": tresorerie["statut"]}, "autres_domaines": autres},
                manque=[f"prévision M5 : {tresorerie['statut']} ou horizon inférieur à {semaines} semaines"]
                + [f"{d['domaine']} : {d['statut']} chez {d['proprietaire']}" for d in autres],
            )

    # 20 recommandations
    recommandations = [
        {
            "session_id": e["session_id"],
            "rapport_id": e["rapport_id"],
            "decision": (e["gouvernance"] or {}).get("decision"),
            "actions": [
                {"action": a["action"], "type": a["type"], "verdict": a["verdict"]}
                for a in (e["gouvernance"] or {}).get("actions", [])
            ],
        }
        for e in cloturees
        if e["issue"] == "RECOMMANDATION" and _dans(e["recu_a"], periode)
    ]
    abstentions = [
        {"session_id": e["session_id"], "raison": e.get("raison_abstention")}
        for e in cloturees
        if e["issue"] != "RECOMMANDATION" and _dans(e["recu_a"], periode)
    ]
    resultats["recommandations"] = _section(
        "recommandations",
        "RENSEIGNEE" if recommandations else "NON_DISPONIBLE",
        {"recommandations": recommandations[:MAX_LIGNES], "abstentions": abstentions[:MAX_LIGNES]},
        manque=[] if recommandations else ["aucune recommandation du conseil clôturée dans la période"],
    )

    # 1 résumé : dénombrements seulement, en dernier pour compter les sections réellement renseignées
    renseignees = sum(1 for s in resultats.values() if s["statut"] == "RENSEIGNEE")
    resultats["resume"] = _section(
        "resume",
        "RENSEIGNEE",
        {
            "sections_renseignees": renseignees,
            "sections_partielles": sum(1 for s in resultats.values() if s["statut"] == "PARTIELLE"),
            "sections_non_disponibles": sum(1 for s in resultats.values() if s["statut"] == "NON_DISPONIBLE"),
            "risques_presents": len(presents),
            "plans": len(vue_plans),
            "plans_en_retard": len(en_retard),
            "actions": len(etat_actions),
            "experiences": len(vue_exp),
            "recommandations_du_conseil": len(recommandations),
            "decisions_a_prendre": len(a_valider) + len(en_attente),
            "lectures_attendues_non_presentes": [
                e["lecture_id"] for e in couverture["lectures"] if e["statut"] != "PRESENTE"
            ],
        },
    )
    ordonnees = {identifiant: resultats[identifiant] for identifiant in IDS}
    return {"version": VERSION, "ids": list(IDS), "sections": ordonnees}
