"""M9.12–13 — radars de risques et d'occasions par les vrais outils, producteurs M4/M5/M6/M8 réels (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import m2_revenue_crm.outils as m2_outils

_TESTS = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _TESTS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


G = _charger("test_m9_graphe_reel")
B, A = G.B, G.A
FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"


def _appel(cap, nom, arguments, identite=B.ADMIN):
    if identite is None:
        return cap.appeler(nom, arguments)
    with B.contexte.appele_par_appareil(identite):
        return cap.appeler(nom, arguments)


def _cles(objet) -> set[str]:
    if isinstance(objet, dict):
        return set(objet) | {c for v in objet.values() for c in _cles(v)}
    if isinstance(objet, list):
        return {c for v in objet for c in _cles(v)}
    return set()


def _capturer(cap, lecture, arguments, rang):
    reponse = B.capturer(cap, B.ADMIN, lecture, arguments, f"2026-10-28T12:01:{rang:02d}Z")
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse
    return reponse["resultat"]["capture"]


def test_radars_sur_le_monde_reel_materiau_en_rupture(tmp_path, monkeypatch):
    try:
        monde = G._monter_scenario(tmp_path, monkeypatch)
        assert monde["chaine"]
        cap = B.capacites(G.M2, G.M3, G.M4, G.M5, G.M6, G.M8)
        _capturer(cap, "m5.prevision_tresorerie", {"aujourd_hui": B.AUJOURD_HUI_M5}, 1)
        _capturer(cap, "m4.retards_incidents", {"horodatage_reference": "2026-10-28T12:00:00Z"}, 2)
        _capturer(cap, "m8.vue_executive", {"aujourd_hui": "2026-10-28"}, 3)
        radar = _appel(cap, "m9_radar_risques", {"connaissance": CONNAISSANCE})
        assert radar["ok"] is True and radar["resultat"]["accepte"] is True, radar
        res = radar["resultat"]
        par_regle = {(r["regle"], r["sujet"]): r for r in res["risques"]}
        # LA RUPTURE réelle : 120 des 150 pi au rebut, la réservation du devis est partielle côté M6.
        materiaux = par_regle[("materiaux_reservation_incomplete", f"devis:{G.DEVIS}")]
        assert materiaux["statut"] == "ACTIF" and materiaux["gravite"] in ("MOYEN", "ELEVE")
        assert materiaux["origine_etablie"] is False and materiaux["preuves"][0].startswith("m6.disponibilite#")
        # M5 sans seuil d'alerte déclaré : la trésorerie n'est PAS dite saine, elle est inconnue
        cash = [r for r in res["risques"] if r["domaine"] == "cash"]
        assert [r["regle"] for r in cash] == ["cash_non_evaluable"] and cash[0]["gravite"] == "INCONNU"
        absentes = {n["regle"] for n in res["regles_non_evaluees"]}
        assert "capacite_incident_ouvert" not in absentes and "capacite_report_en_cours" not in absentes
        # l'écart de marge M8 est négatif ou non : la règle est évaluée sur les vraies mesures, jamais supposée
        assert "qualite_ecart_marge_negatif" not in absentes
        assert all("cause" not in r and r["origine_etablie"] is False for r in res["risques"])
        # source périmée : connaissance bien plus tard, péremption courte
        tard = _appel(cap, "m9_radar_risques", {"connaissance": "2026-11-20T12:00:00Z", "perime_apres_jours": 3})[
            "resultat"
        ]
        assert {r["statut"] for r in tard["risques"] if r["domaine"] == "materiaux"} == {"A_RECONFIRMER"}
        # radar d'occasions : devis sans réponse (M8) = hypothèse sans coût ni capacité ; aucun revenu
        occasions = _appel(
            cap,
            "m9_radar_occasions",
            {
                "reference": CONNAISSANCE,
                "occasions_declarees": [
                    {
                        "id": "service_gouttieres",
                        "libelle": "Offrir l'entretien de gouttières",
                        "origine": "DECLAREE_PAR_LA_PERSONNE",
                    }
                ],
            },
        )["resultat"]
        assert occasions["accepte"] is True
        assert occasions["occasions"][0]["statut"] == "HYPOTHESE" and not (
            _cles(occasions) & {"revenu", "gain", "marge", "probabilite"}
        )
        refus = _appel(
            cap,
            "m9_radar_occasions",
            {
                "reference": CONNAISSANCE,
                "occasions_declarees": [{"id": "x", "libelle": "y", "origine": "SIGNAL_MESURE", "revenu": "9"}],
            },
        )
        assert "REJ-OCCASION-REVENU" in json.dumps(refus)
        # non admin, voie d'agent : refusés
        vendeur = B.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
        for nom, arguments in (
            ("m9_radar_risques", {"connaissance": CONNAISSANCE}),
            ("m9_radar_occasions", {"reference": CONNAISSANCE}),
        ):
            assert _appel(cap, nom, arguments, vendeur)["ok"] is False
            assert _appel(cap, nom, arguments, None)["ok"] is False
    finally:
        m2_outils.reinitialiser_registre()
