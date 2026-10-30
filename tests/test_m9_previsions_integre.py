"""M9.9 — m9_previsions_consolidees sur la vraie prévision de trésorerie M5 (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _TESTS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


H = _charger("m9_producteurs_b")
FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    H.declarer_m5(tmp_path, monkeypatch)
    H.enregistrer_mouvements_m5()
    H.factures_clients_m5()
    H.comptes_a_payer_m5(3)
    yield H.capacites(H.M5)
    H.desinstaller_base()


def _capturer(cap, arguments, recu):
    reponse = H.capturer(cap, H.ADMIN, "m5.prevision_tresorerie", arguments, recu)
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse
    return reponse["resultat"]["capture"]


def _consolidees(cap, identite=H.ADMIN, **arguments):
    arguments = {"connaissance": CONNAISSANCE, **arguments}
    if identite is None:
        return cap.appeler("m9_previsions_consolidees", arguments)
    with H.contexte.appele_par_appareil(identite):
        return cap.appeler("m9_previsions_consolidees", arguments)


def test_prevision_reelle_de_m5_citee_et_domaines_sans_prevision_nommes(monde):
    capture = _capturer(monde, {"aujourd_hui": H.AUJOURD_HUI_M5}, "2026-10-28T12:00:01Z")
    assert capture["complete"] is True
    reponse = _consolidees(monde, perime_apres_jours=7)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    domaines = {d["domaine"]: d for d in reponse["resultat"]["domaines"]}
    t = domaines["tresorerie"]
    version = t["versions"][0]
    assert version["statut"] == "COMPLETE" and version["semaines_lues"] == 6 and version["semaines_manquantes"] == 0
    assert version["solde_initial"] == "20000.00" and version["valeurs"]["alerte.statut"] == "ALERTE"
    assert len(version["valeurs"]["prevision_id"]) == 64 and version["reference_jour"] == H.AUJOURD_HUI_M5
    assert version["faits"]["prevision_id"].startswith("m5.prevision_tresorerie#0:p0.resultat.resultat.prevision_id")
    assert t["incertitude"]["chiffree"] is False
    # La prévision date du jour de référence M5 ; la connaissance est postérieure : l'âge est dit, la péremption jugée.
    assert version["age_jours"] is not None and t["statut"] in ("DISPONIBLE", "PERIMEE")
    for nom in ("leads", "capacite", "materiaux"):
        assert domaines[nom]["statut"] == "AUCUNE_PREVISION_PRODUITE" and domaines[nom]["versions"] == []


def test_deux_versions_dont_une_page_de_26_semaines(monde):
    _capturer(monde, {"aujourd_hui": H.AUJOURD_HUI_M5, "horizon_semaines": 26}, "2026-10-28T12:00:01Z")
    H.factures_clients_m5()  # le registre bouge : une seconde lecture peut porter une autre empreinte
    _capturer(monde, {"aujourd_hui": H.AUJOURD_HUI_M5, "horizon_semaines": 26}, "2026-10-28T12:00:02Z")
    res = _consolidees(monde)["resultat"]
    t = next(d for d in res["domaines"] if d["domaine"] == "tresorerie")
    assert t["versions_total"] == 2 and all(v["semaines_lues"] == 26 for v in t["versions"])
    assert all(v["statut"] in ("COMPLETE", "CONTRADICTOIRE") for v in t["versions"])


def test_refus_non_admin_agent_et_parametres(monde):
    vendeur = H.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    assert _consolidees(monde, vendeur)["ok"] is False
    assert _consolidees(monde, None)["ok"] is False
    refus = _consolidees(monde, perime_apres_jours=-5)
    assert "perime_apres_jours" in json.dumps(refus) or refus["ok"] is False
    sans_fuseau = _consolidees(monde, connaissance="2026-10-28T13:00:00")
    assert sans_fuseau["ok"] is False or sans_fuseau["resultat"].get("accepte") is False
