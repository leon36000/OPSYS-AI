"""Aide NON COLLECTÉE des tests du radar de risques (M9.12) : pages de producteurs FICTIVES, de la forme exacte que
leurs
vrais outils rendent, et chaîne de captures. Réutilise les constructeurs des tests de raccord (M1, M4, M7) et de
``pages_athena`` (M2) : une charge qui viole le contrat de son producteur est refusée par la capture elle-même.

Tout est fictif (``FICTIF = True``).
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

FICTIF = True
ICI = Path(__file__).resolve().parent
CONNAISSANCE = "2026-10-28T13:00:00Z"
RECU = "2026-10-28T12:00:{:02d}Z"


def _charger(nom: str):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, ICI / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


pages_athena = _charger("pages_athena")
m1 = _charger("test_raccord_m1_plaintes")
m4 = _charger("test_raccord_m4_capacite")
m7 = _charger("test_raccord_m7_depenses")

# Seuils déclarés par la direction (fictifs) : de quoi faire parler chaque règle.
SEUILS = {
    "plaintes_seuil_nombre": 3,
    "capacite_utilisation_seuil_pct": "90",
    "depense_marketing_plafond_cad": "1500.00",
    "leads_plancher_par_semaine": 5,
    "estimation_ecart_relatif_max": "0.25",
    "retard_chantier_jours": 5,
    "donnees_perimees_jours": 14,
    "cash_libre_plancher_cad": "5000.00",
    "multiple_seuil_critique": "1.5",
}


def ok(corps: dict) -> dict:
    return {"ok": True, "resultat": corps}


def enveloppe(contenu: dict) -> dict:
    return ok({"accepte": True, "resultat": contenu})


# ------------------------------------------------------------------------------------------------------ les pages
def page_plaintes(n: int = 0, *, categories=("degat",), statut="ouvert") -> dict:
    if n == 0:
        return m1._page(m1.charge_aucune_declaree())
    plaintes = [m1._plainte(i + 1, categories=categories, statut=statut) for i in range(n)]
    par_categorie = dict.fromkeys(m1.CATEGORIES, 0)
    for plainte in plaintes:
        for categorie in plainte["categories"]:
            par_categorie[categorie] += 1
    comptes = {"declarees": n, "par_categorie": par_categorie, "sans_categorie": 0}
    comptes |= {
        "par_type": {"plainte": n, "urgence": 0},
        "par_statut": {"ouvert": n if statut == "ouvert" else 0, "clos": 0 if statut == "ouvert" else n},
    }
    return m1._page(m1._base("CONNUE", "TRANSFERTS_DE_PLAINTE_AU_REGISTRE", comptes=comptes, plaintes=plaintes))


def page_plaintes_non_branchee() -> dict:
    return m1._page(m1.charge_non_branchee())


def page_capacite(equipes: list[tuple[str, int, int]]) -> dict:
    charge = copy.deepcopy(m4.charge_calculable())
    charge["equipes"] = [m4._equipe(*e) for e in equipes]
    dispo, plan = sum(e[1] for e in equipes), sum(e[2] for e in equipes)
    charge.update(
        heures_disponibles=m4._heures(dispo),
        heures_planifiees=m4._heures(plan),
        minutes_disponibles=dispo,
        minutes_planifiees=plan,
    )
    return m4._page(charge)


def page_capacite_non_calculable() -> dict:
    return m4._page(m4.charge_non_calculable())


def page_depenses(google: str = "1000.00", meta: str = "300.00") -> dict:
    return ok(m7.charge_connue(google, meta))


def page_prevision(*, bas="2.00", centre="3.50", haut="4.00", horizon=2) -> dict:
    page = pages_athena.page_m2_prevision(horizon=horizon)
    for periode in page["resultat"]["resultat"]["par_periode"]:
        periode.update(centre=centre, intervalle={"niveau": 80, "bas": bas, "haut": haut})
    return page


def ligne_ecart(wct="wct-1", *, ecart="0.10", signal=False) -> dict:
    return {
        "wct_id": wct, "devis_id": "D1", "intervention_id": "I1", "horodatage_completion": "2026-10-20T16:00:00Z",
        "main_doeuvre": {"duree_reelle_minutes": "300", "duree_estimee_minutes": "240", "ecart_relatif": ecart,
                         "verdict": None},
        "materiaux": {"chantier_id": "C1", "signal_critique": signal, "seuil_pourcentage": 10, "lignes": []}
        if signal is not None else None,
    }  # fmt: skip


def page_ecarts(*lignes: dict) -> dict:
    return enveloppe(list(lignes))


def page_disponibilite(articles=(), reservations=()) -> dict:
    return enveloppe({"articles": list(articles), "tronque": False, "reservations_actives": list(reservations)})


def article(materiau="gouttiere-5po", disponible="12") -> dict:
    return {"materiau_id": materiau, "disponible": disponible, "en_main": "20", "reserve": "8"}


def page_retards(reports=(), incidents=()) -> dict:
    return enveloppe({
        "reports": {"liste": [{"intervention_id": i, "motif": m, "depuis": d} for i, m, d in reports], "reste": 0},
        "incidents": {"liste": list(incidents), "reste": 0},
    })  # fmt: skip


def page_cash_libre(montant: str | None = "20000.00", *, statut="CALCULE") -> dict:
    if montant is None and statut == "manque":
        return ok({"cash_libre": {"statut": "manque", "manque": ["cash_libre"]}})
    constat = {
        "statut": statut,
        "cash_libre_cad": montant if statut == "CALCULE" else None,
        "en_deficit": montant is not None and montant.startswith("-"),
        "sequence": 1,
    }
    return ok({"cash_libre": {"statut": "lu", "constat": constat, "age": {"jours": 1}}})


def page_sla(*, violations: dict[str, int] | None = None, non_evaluees: tuple[str, ...] = ()) -> dict:
    regles = []
    for nom in (
        "prochaine_action_obligatoire",
        "lead_chaud_non_contacte",
        "photos_non_recues",
        "soumission_non_relancee",
        "plainte_non_escaladee",
        "lead_sans_proprietaire",
        "tache_en_retard",
    ):
        if nom in non_evaluees:
            regles.append({"regle": nom, "etat": "non_evaluee", "manque": "délai à déclarer", "violations": None})
        else:
            regles.append(
                {"regle": nom, "etat": "evaluee", "manque": None, "violations": (violations or {}).get(nom, 0)}
            )
    return enveloppe(
        {
            "reference": CONNAISSANCE,
            "leads_examines": 12,
            "regles": regles,
            "violations": [],
            "total": 0,
            "suivant": None,
        }
    )


ARGUMENTS = {
    "m1.plaintes_structurees": {"date_reference": m1.JOUR, "jours": 7},
    "m4.capacite_equipe": dict(m4.ARGS),
    "m7.depenses_marketing": {"debut": m7.DEBUT, "fin": m7.FIN},
    "m2.prevision_pipeline": dict(pages_athena.ARGUMENTS["m2.prevision_pipeline"]),
    "m3.ecarts": {"depuis": "2026-10-01T00:00:00-04:00", "jusqua": "2026-11-01T00:00:00-04:00"},
    "m6.disponibilite": {},
    "m4.retards_incidents": {"horodatage_reference": "2026-10-28T12:00:00Z"},
    "m8.vue_executive": {"aujourd_hui": "2026-10-28"},
    "m2.sla_filet": {"horodatage": "2026-10-28T12:00:00Z"},
}


def capturer(chaine: list, lecture_id: str, page: dict, rang: int = 0, *, recu: str | None = None) -> dict:
    return pages_athena.capturer(
        chaine, lecture_id, page, recu or RECU.format(rang), arguments=copy.deepcopy(ARGUMENTS[lecture_id])
    )


def radar(chaine: list, **plus):
    from m9_strategic_intelligence import risques

    return risques.evaluer(chaine, connaissance=plus.pop("connaissance", CONNAISSANCE), **plus)


def par_regle(resultat: dict) -> dict:
    return {(r["regle"], r["sujet"]): r for r in resultat["risques"]}


def non_evaluee(resultat: dict, regle: str) -> list[dict]:
    return [n for n in resultat["regles_non_evaluees"] if n["regle"] == regle]
