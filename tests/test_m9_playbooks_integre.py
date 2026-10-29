"""M9.15 — playbooks par le vrai dispatcher ; chaque port cité existe réellement dans les départements (fictif)."""

from __future__ import annotations

import json

import pytest
from m9_strategic_intelligence import playbooks

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements

FICTIF = True
M9 = "m09-strategic-intelligence"
ADMIN = IdentiteAppelante("admin.fictif", "admin", source="console")
CONNAISSANCE = "2026-10-28T13:00:00Z"


@pytest.fixture
def cap(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'playbooks.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
    yield Capacites(charger_departements(), stockage.transaction, filtre={M9}, memoire=False)
    stockage.liberer()


def appel(cap, nom, arguments, identite_appelante=ADMIN):
    if identite_appelante is None:
        return cap.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return cap.appeler(nom, arguments)


def test_chaque_port_cite_par_un_playbook_est_un_outil_reel():
    departements = charger_departements()
    outils_reels = (
        {outil.nom for departement in departements.values() for outil in departement.outils_exposes()}
        if all(hasattr(d, "outils_exposes") for d in departements.values())
        else None
    )
    if outils_reels is None:
        outils_reels = set()
        for departement in departements.values():
            outils_reels |= {outil.nom for outil in departement.charger_outils()}
    for id_, gabarit in playbooks.CATALOGUE.items():
        for etape in gabarit["etapes"]:
            if etape["port"] is not None:
                assert etape["port"] in outils_reels, f"{id_}.{etape['id']} cite un port inexistant : {etape['port']}"


def test_lister_et_evaluer_par_les_vrais_outils_sans_donnee_donne_inconnu_ou_a_declarer(cap):
    liste = appel(cap, "m9_lister_playbooks", {})
    assert liste["ok"] is True and len(liste["resultat"]["playbooks"]) == 6
    assert all(p["etapes_sensibles"] >= 1 for p in liste["resultat"]["playbooks"])
    reponse = appel(cap, "m9_evaluer_playbook", {"playbook_id": "rupture", "connaissance": CONNAISSANCE})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    plan = reponse["resultat"]["plan"]
    assert plan["declenchement"]["statut"] == "INCONNU", "aucune capture : le déclencheur est inconnu, pas absent"
    assert reponse["resultat"]["evaluation"]["verdict"] == "INCONNU"
    declare = appel(
        cap,
        "m9_evaluer_playbook",
        {
            "playbook_id": "hausse_prix",
            "connaissance": CONNAISSANCE,
            "declare_par_la_personne": True,
            "liaisons": {"marge_retablie": "50"},
        },
    )["resultat"]
    assert declare["plan"]["declenchement"]["statut"] == "DECLENCHE"
    assert declare["plan"]["succes"][0]["cible_declaree_par_la_personne"] is True
    assert all(e["effet_autorise"] is False for e in declare["plan"]["etapes"])


def test_refus_identites_et_playbook_inconnu(cap):
    vendeur = IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    for nom, arguments in (
        ("m9_lister_playbooks", {}),
        ("m9_evaluer_playbook", {"playbook_id": "cash", "connaissance": CONNAISSANCE}),
    ):
        assert appel(cap, nom, arguments, vendeur)["ok"] is False and appel(cap, nom, arguments, None)["ok"] is False
    refus = appel(cap, "m9_evaluer_playbook", {"playbook_id": "inventé", "connaissance": CONNAISSANCE})
    assert refus["ok"] is False or "REJ" in json.dumps(refus)
