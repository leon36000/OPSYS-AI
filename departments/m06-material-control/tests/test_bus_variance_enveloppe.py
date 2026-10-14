"""Frontière du producteur M6 : premier fait par statut, charges fictives et SQL réel.

Les registres de cette fixture isolent la publication ; les parcours appareils et
réservations complets restent dans leurs suites existantes.
"""
from __future__ import annotations

import pytest
from m6_material_control import outils
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.outils import Outil, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_WCT = {
    "wct_id": "wct-variance-fictif", "intervention_id": "intervention-fictive",
    "devis_id": "devis-fictif", "horodatage_completion": "2026-10-07T12:00:00+00:00",
}


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    monkeypatch.setattr(outils, "_seuil_variance_chantier", lambda: None)
    stockage.migrer()
    yield
    stockage.liberer()


def _charge(statut):
    return {
        "evenement_id": f"m6-variance-{_WCT['wct_id']}-{statut}",
        **{cle: valeur for cle, valeur in _WCT.items() if cle != "devis_id"},
        "chantier_id": None, "statut_variance": statut,
        "signal_critique": False if statut == "evaluee" else None,
        "seuil_pourcentage": 0.3 if statut == "evaluee" else None,
        "lignes": [] if statut == "evaluee" else None,
    }


@pytest.mark.parametrize("statut", ["seuil_absent", "prevu_absent"])
def test_meme_statut_conserve_premier_fait_et_enrichissement_durable(base, monkeypatch, statut):
    if statut == "prevu_absent":
        monkeypatch.setattr(outils, "_seuil_variance_chantier", lambda: 0.3)
    with stockage.transaction():
        assert outils._evaluer_et_publier_variance(_WCT)["statut_variance"] == statut
    ident = _charge(statut)["evenement_id"]
    premiere = evenements.charge_publiee("m6.variance_chantier", ident)
    assert premiere["chantier_id"] is None
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).one()
        # Fixture de publication : la déclaration apporte maintenant le chantier.
        stockage.maillons("m06-material-control", "principal").append({
            "wct_id": _WCT["wct_id"], "chantier_id": "chantier-fictif", "fictif": True,
        })
        assert outils._evaluer_et_publier_variance(_WCT)["statut_variance"] == statut
    stockage.liberer()
    assert list(stockage.maillons("m06-material-control", "principal"))[0]["chantier_id"] == "chantier-fictif"
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).one() == avant


@pytest.mark.parametrize("statut,collision", [
    ("seuil_absent", "producteur"), ("seuil_absent", "type"), ("evaluee", "producteur"),
])
def test_collision_refuse_publication_m6_et_annule_ecriture(base, statut, collision):
    charge = _charge(statut)
    ident = charge["evenement_id"]
    if collision == "type":
        evenements.publier("opsys.demo_complete", "m06-material-control", {"message": "fictif"}, evenement_id=ident)
    else:
        evenements.publier("m6.variance_chantier", "autre-producteur-fictif", charge, evenement_id=ident)
    with stockage.transaction() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS)).one()

    def publier():
        stockage.maillons("m06-material-control", "fictif-effet").append({"fictif": True})
        return outils._evaluer_et_publier_variance(_WCT)

    reponse = executer_atomique(Outil("m6_test_publication", "Fixture", {"type": "object"}, publier), {})
    stockage.liberer()
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert len(stockage.maillons("m06-material-control", "fictif-effet")) == 0
    with stockage.transaction() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).one() == avant


def test_identifiant_terminal_autre_type_ne_simule_pas_variance_evaluee(base):
    ident = _charge("evaluee")["evenement_id"]
    evenements.publier("opsys.demo_complete", "m06-material-control", {"message": "fictif"}, evenement_id=ident)
    with stockage.transaction():
        assert outils._evaluer_et_publier_variance(_WCT)["statut_variance"] == "seuil_absent"
    assert evenements.charge_publiee("m6.variance_chantier", ident) is None
    assert evenements.charge_publiee("opsys.demo_complete", ident) == {"message": "fictif"}
