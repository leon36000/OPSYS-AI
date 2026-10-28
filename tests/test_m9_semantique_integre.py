"""M9.3 — m9_rapprocher_metriques sur le vrai M8 (registre de définitions durable, mesures d'un chantier) (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m8_analytics import registre_metriques

from opsys import stockage

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
M8 = "m08-analytics"


def _recu(n: int) -> str:
    return f"2026-10-28T12:00:{n:02d}Z"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    H.declarer_m5(tmp_path, monkeypatch)
    H.alimenter_m8()
    yield H.capacites(H.M8)
    H.desinstaller_base()


def _definir(metric_id, unite):
    with stockage.transaction():
        verdict = registre_metriques.enregistrer_definition(
            {
                "metric_id": metric_id,
                "departement_proprietaire": M8,
                "unite": unite,
                "source": "m8_lire_mesures_chantier",
                "fraicheur_attendue_jours": 30,
                "regles_qualite": {"plage_min": None, "plage_max": None},
            },
            stockage.maillons(M8, "definitions_metriques"),
        )
    assert verdict["enregistree"] is True, verdict


def _appel(cap, nom, arguments, identite=H.ADMIN):
    if identite is None:
        return cap.appeler(nom, arguments)
    with H.contexte.appele_par_appareil(identite):
        return cap.appeler(nom, arguments)


def _rapprocher(cap, connaissance=CONNAISSANCE, identite=H.ADMIN):
    return _appel(cap, "m9_rapprocher_metriques", {"connaissance": connaissance}, identite)


def _capturer_mesures(cap, n):
    reponse = H.capturer(cap, H.ADMIN, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, _recu(n))
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse
    return reponse["resultat"]["capture"]


def _capturer_registre(cap, n):
    reponse = H.capturer(cap, H.ADMIN, "m8.definitions_metriques", {}, _recu(n))
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse
    assert reponse["resultat"]["capture"]["complete"] is True
    return reponse["resultat"]["capture"]


def test_sans_capture_du_registre_le_rapprochement_est_refuse(monde):
    _capturer_mesures(monde, 1)
    reponse = _rapprocher(monde)
    assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    assert "REJ-SEMANTIQUE-REGISTRE-ABSENT" in json.dumps(reponse)


def test_mesures_reelles_face_au_registre_reel(monde):
    mesures = _capturer_mesures(monde, 1)
    page = H.page(mesures["index"])
    par_metrique = {m["metric_id"]: m for m in H.valeurs(page, "resultat.mesures[*]")}
    assert par_metrique["m8_marge_reelle_cad"]["valeur"] == "114.00"
    unite_marge = par_metrique["m8_marge_reelle_cad"]["unite"]
    _definir("m8_marge_reelle_cad", unite_marge)
    _definir("m8_marge_prevue_cad", "minutes")  # unité volontairement divergente de la mesure réelle
    registre = _capturer_registre(monde, 2)
    reponse = _rapprocher(monde)
    assert reponse["ok"] is True, reponse
    res = reponse["resultat"]
    assert res["accepte"] is True and res["definitions_connues"] == 2 and res["registre_capture"] == [registre["index"]]
    assert res["prochain_depart"] is None and sum(res["statuts"].values()) == res["total_observations"]
    statuts = {o["metric_id"]: o["statut"] for o in res["observations"]}
    # L'empreinte de définition portée par la mesure (64 hexadécimaux) et la version entière du registre ne sont pas
    # reliées : M9 ne dit ni « périmée » ni « compatible ». Les métriques absentes du registre n'ont pas de définition.
    assert statuts["m8_marge_reelle_cad"] == "VERSION_NON_COMPARABLE"
    assert statuts["m8_marge_prevue_cad"] == "UNITE_DIVERGENTE"
    assert statuts["m8_ecart_duree_minutes"] == "SANS_DEFINITION"
    assert res["comparables_ensemble"] == 0 and res["agregable"] is False
    assert next(o for o in res["observations"] if o["metric_id"] == "m8_marge_reelle_cad")["valeur"] == "114.00"
    assert all(o["source"].startswith("m8.mesures_chantier#") for o in res["observations"])


def test_connaissance_anterieure_au_registre_le_refuse_et_non_admin_refuse(monde):
    _capturer_mesures(monde, 1)
    _definir("m8_marge_reelle_cad", "CAD")
    _capturer_registre(monde, 2)
    avant = _rapprocher(monde, "2026-10-28T12:00:01Z")  # le registre n'était pas encore connu
    assert "REJ-SEMANTIQUE-REGISTRE-ABSENT" in json.dumps(avant)
    comptable = H.IdentiteAppelante("comptable", "admin")
    assert (
        _rapprocher(monde, identite=H.IdentiteAppelante("vendeur.fictif", "employee", source="appareil"))["ok"] is False
    )
    assert _rapprocher(monde, identite=None)["ok"] is False
    assert comptable.role == "admin"
