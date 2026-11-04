"""D3/D5 M9 : bucket d'attribution absent et bornes du contrat M7, données fictives."""
from __future__ import annotations

import hashlib
import importlib
import json

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import graphe_impacts as gi
from m9_strategic_intelligence import relations_catalogue as rc

from opsys import contexte

FICTIF = True
UTC = "2026-10-28T12:00:00Z"


def _charger_test(nom: str, racine_tests, monkeypatch):
    monkeypatch.syspath_prepend(str(racine_tests))
    return importlib.import_module(nom)


def _capture(resultat: dict) -> dict:
    return cs.construire(
        cat.obtenir("m7.performance_campagnes"),
        {"debut": "2026-10-01", "fin": "2026-10-31"},
        [{"ok": True, "resultat": resultat}],
        recu_a=UTC,
        reference=None,
        index=0,
        hash_precedent="",
    )


def _campagne_id(source: str, campagne: str) -> str:
    canonique = json.dumps((source, campagne), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256-" + hashlib.sha256(canonique).hexdigest()


def test_bucket_absent_reste_inconnu_sans_fausse_ligne_invalide_meme_si_racine_complete():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({
        "couverture": "COMPLETE",
        "campagnes": [
            {"source": "source-fictive", "campagne": "campagne-fictive",
             "source_refs": [{"type": "m2.client_associe", "reference": "lead-attribue-fictif"}]},
            {"source": None, "campagne": None, "couverture": "INCONNUE",
             "manque": ["ATTRIBUTION_ABSENTE"],
             "source_refs": [{"type": "m2.client_associe", "reference": "lead-sans-attribution-fictif"}]},
        ],
    })
    graphe = gi.construire([capture], [regle], connaissance=UTC)
    active = next(x for x in graphe["regles_actives"] if x["regle"] == regle.id)
    inconnues = {x["raison"] for x in graphe["regles_inconnues"] if x["regle"] == regle.id}
    assert active["aretes"] == 1 and active["lignes_ecartees"] == 0
    assert "COUVERTURE_INCONNUE" in inconnues
    assert "IDENTIFIANT_LIEN_INVALIDE" not in inconnues
    assert gi.propager(graphe, "campagne", _campagne_id("source-fictive", "campagne-fictive"))["complet"] is False


@pytest.mark.parametrize("identifiant", [
    "L" * 129,
    " lead-fictif ",
    "é" * 1024,  # exactement 2048 octets UTF-8
])
def test_m7_lead_jusqua_2048_octets_est_relier(identifiant):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({"couverture": "PARTIELLE", "campagnes": [{
        "source": "source-fictive", "campagne": "campagne-fictive",
        "source_refs": [{"type": "m2.client_associe", "reference": identifiant}],
    }]})
    graphe = gi.construire([capture], [regle], connaissance=UTC)
    assert any(a["vers"] == f"lead:{identifiant}" for a in graphe["aretes"])


@pytest.mark.parametrize("identifiant", ["é" * 1024 + "a", " " * 8])
def test_m7_lead_hors_domaine_2048_octets_est_refuse_et_signale(identifiant):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({"couverture": "COMPLETE", "campagnes": [{
        "source": "source-fictive", "campagne": "campagne-fictive",
        "source_refs": [{"type": "m2.client_associe", "reference": identifiant}],
    }]})
    graphe = gi.construire([capture], [regle], connaissance=UTC)
    assert not graphe["aretes"]
    assert any(x["raison"] == "IDENTIFIANT_LIEN_INVALIDE" and x["regle"] == regle.id
               for x in graphe["regles_inconnues"])


def test_borne_128_des_autres_identifiants_reste_inchangee():
    assert gi._texte_id("I" * 128) == "I" * 128
    assert gi._texte_id("I" * 129) is None


def test_identifiant_historique_d_une_arete_courte_reste_inchange():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({"couverture": "PARTIELLE", "campagnes": [{
        "source": "source-fictive", "campagne": "campagne-fictive",
        "source_refs": [{"type": "m2.client_associe", "reference": "lead-court-fictif"}],
    }]})
    graphe = gi.construire([capture], [regle], connaissance=UTC)
    assert [arete["id"] for arete in graphe["aretes"]] == ["3abde9f159f35c9fd00b"]
    assert graphe["graphe_id"] == "89f0c067490e51c26e46a92694a38607c5a090330798bf2a703168e17674354f"


def test_parcours_public_m2_bus_m7_capture_m9_et_propagation_accepte_lead_long(
    tmp_path, pytestconfig, monkeypatch
):
    racine_tests = pytestconfig.rootpath / "tests"
    monkeypatch.syspath_prepend(str(racine_tests / "fixtures"))
    a = _charger_test("m9_producteurs_a", racine_tests, monkeypatch)
    b = _charger_test("m9_producteurs_b", racine_tests, monkeypatch)
    import m2_revenue_crm.outils as m2_outils


    nettoyage = pytest.MonkeyPatch()
    try:
        b.installer_base(tmp_path, nettoyage)
        m2_outils.utiliser_stockage_durable()
        outils_m2 = a.outils_departement("m02-revenue-crm")
        leads = [
            ("lead-sans-utm-fictif", None),
            ("L" * 129, {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"}),
            (" lead-avec-espaces-fictif ", {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"}),
            ("é" * 1024, {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"}),
            ("lead-court-fictif", {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"}),
            ("foo:bar", {"utm_source": "source-fictive", "utm_campaign": "campagne-fictive"}),
        ]
        for index, (lead_id, utm) in enumerate(leads):
            contrat = {
                "lead_id": lead_id, "conversation_id": f"conversation-fictive-{index}",
                "type_travaux": "renovation_totale", "ville": "Repentigny", "canal": "telephone",
                "contact": {"nom": f"Client fictif {index}"}, "urgence_declaree": False,
            }
            if utm is not None:
                contrat["utm"] = utm
            reponse = a.geste(outils_m2, "m2_ingerer_lead", {
                "contrat": contrat, "horodatage": "2026-09-10T12:00:00Z",
            })
            assert reponse["accepte"] is True

        livraison = b.livrer((b.M7,))
        assert livraison["traites"] == 6 and livraison["echecs"] == 0
        capacites = b.capacites(b.M9, b.M7)
        capture = b.capturer(
            capacites, b.ADMIN, "m7.performance_campagnes",
            {"debut": "2026-09-01", "fin": "2026-09-30"}, UTC,
        )
        assert capture["resultat"]["capture"]["verdict"] == "ACCEPTEE"
        page = b.captures_stockees()[-1]["pages"][0]["resultat"]
        bucket_inconnu = next(x for x in page["campagnes"] if x["source"] is None)
        assert bucket_inconnu["manque"] == ["ATTRIBUTION_ABSENTE"]

        with contexte.appele_par_appareil(b.ADMIN):
            apercu = capacites.appeler("m9_apercu_graphe_impacts", {"connaissance": "2026-10-28T12:01:00Z"})
        assert apercu["ok"] is True
        graphe = apercu["resultat"]
        active = next(x for x in graphe["regles_actives"] if x["regle"] == "m7_campagne_lead_utm")
        assert active["aretes"] == 5 and active["lignes_ecartees"] == 0
        raisons = {x["raison"] for x in graphe["regles_inconnues"] if x["regle"] == "m7_campagne_lead_utm"}
        assert "COUVERTURE_INCONNUE" in raisons and "IDENTIFIANT_LIEN_INVALIDE" not in raisons

        with contexte.appele_par_appareil(b.ADMIN):
            propagation = capacites.appeler("m9_propager_impacts", {
                "connaissance": "2026-10-28T12:01:00Z", "kind": "lead",
                "identifiant": "é" * 1024,
                "relations": ["attribue_selon_utm"], "profondeur_max": 2,
            })
        assert propagation["ok"] is True, propagation
        assert propagation["resultat"]["depart"]["id"] == "é" * 1024
        assert propagation["resultat"]["impacts"] == []
        with contexte.appele_par_appareil(b.ADMIN):
            split_d8 = capacites.appeler("m9_propager_impacts", {
                "connaissance": "2026-10-28T12:01:00Z", "kind": "lead:foo",
                "identifiant": "bar", "relations": ["attribue_selon_utm"], "profondeur_max": 2,
            })
            exact_d8 = capacites.appeler("m9_propager_impacts", {
                "connaissance": "2026-10-28T12:01:00Z", "kind": "lead",
                "identifiant": "foo:bar", "relations": ["attribue_selon_utm"], "profondeur_max": 2,
            })
        assert split_d8["ok"] is False and "REJ-GRAPHE-NOEUD-INCONNU" in split_d8["details"]
        assert exact_d8["ok"] is True and exact_d8["resultat"]["depart"] == {"kind": "lead", "id": "foo:bar"}
        with contexte.appele_par_appareil(b.ADMIN):
            hors_borne = capacites.appeler("m9_propager_impacts", {
                "connaissance": "2026-10-28T12:01:00Z", "kind": "lead",
                "identifiant": "é" * 1025,
                "relations": ["attribue_selon_utm"], "profondeur_max": 2,
            })
        assert hors_borne["ok"] is False and "REJ-GRAPHE-ID" in hors_borne["details"]
    finally:
        try:
            m2_outils.reinitialiser_registre()
            b.desinstaller_base()
        finally:
            nettoyage.undo()
