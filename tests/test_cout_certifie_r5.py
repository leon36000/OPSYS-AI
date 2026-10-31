"""Décisions r5 de l'architecte, sur la vraie voie (M3 → M4 V3 → bus → M5 → réconciliateur), base éphémère, fictif.

1. Une exception de la publication certifiée PENDANT la livraison du WCT n'annule plus rien : reçu WCT et facture
   brouillon présents, livraison `traite` du premier coup (ni réessai ni quarantaine), échec typé dans le reçu du
   bus, devis marqué « à recalculer » (mécanisme E1 : D3 `perime_recalcul_en_attente`), puis le réconciliateur,
   hors livraison, refuse une fois par état (pas de boucle) et republie un certifié quand la cause est corrigée.
2. Une correction purement M4 après certification (déclaration d'équipe du jour du chantier) rend le certifié
   périmé, et il est recalculé ; une écriture M4 sans rapport (autre jour) ne rend rien périmé et n'écrit rien.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import time
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from sqlalchemy import select

from opsys import identite, service_politiques, stockage
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.evenements import reconciliateur_cout_certifie as rc
from opsys.stockage import codec
from opsys.stockage.schema import COUT_CERTIFIE_RECONCILIATIONS, EVENEMENTS_RECUS


def _charger(nom_fichier, nom):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(nom_fichier))
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


cm = _charger("test_cascade_marge_m5_m8_m10.py", "r5_helpers_cascade_marge")
rg = _charger("test_regression_cascade_cout_certifie.py", "r5_helpers_regression")
BASE = rg.BASE
LEAD, DEVIS, CHANTIER = "LEAD-R5-fictif", "DEVIS-R5-fictif", "CH-R5-fictif"
OPERATEUR = "operateur-r5-fictif"
CODE_PERIME = "REJ-COUT-CERTIFIE-A-RECALCULER"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-r5.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv(rc.ENV_MODE, "actif")
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    rc.reinitialiser()
    try:
        yield url
    finally:
        rc.reinitialiser()
        m2_outils.reinitialiser_registre()
        stockage.liberer()


def _octroyer(*operations):
    session = Session(OPERATEUR, frozenset({"admin"}), "csrf-fictif", int(time.time()) + 3600)
    with stockage.transaction() as cnx:
        if identite.personne(cnx, OPERATEUR) is None:
            identite.creer_personne(cnx, OPERATEUR, "Opérateur (fictif)", "mot-de-passe-operateur-assez-long",
                                    ["admin"])
        for operation in operations:
            service_politiques.octroyer(cnx, session, operation, motif="Mise en service fictive")


def _statut():
    from m5_financecore import port_service_m4

    with stockage.transaction():
        return port_service_m4.etat_cout_certifie(DEVIS)["statut"]


def _journal():
    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(COUT_CERTIFIE_RECONCILIATIONS).order_by(
            COUT_CERTIFIE_RECONCILIATIONS.c.id)).mappings()]


def _recu_wct(wct_id):
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == "m05-financecore",
        )).mappings().one()
    return dict(ligne)


def _certifiees():
    return [t for t in rg._traces_m5(DEVIS) if t["provenance_service_v1"] and t["mo_statut"] == "complet"]


def _chantier(deps):
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), rg.TARIF_PRIX_LIVRE)
    return cm._chantier_termine(deps, BASE, LEAD, DEVIS, CHANTIER, 40.0, certifie=True)


# -------------------------------------------------------------------------------------------
# 1. Publication certifiée découplée de la livraison du WCT
# -------------------------------------------------------------------------------------------
def test_publication_qui_leve_en_livraison_ne_touche_ni_recu_ni_facture_puis_reprise_hors_livraison(
        base_durable, monkeypatch):
    _octroyer("m4.recalculer_v3")  # `m4.verifier_v3` : posée par le harnais d'équipe (voie V1 active en livraison)
    deps = charger_departements()
    wct_id, _ = _chantier(deps)
    original = m5_outils._instantane_tarifs_equipes

    def illisible():
        raise ValueError("tarifs d'équipe : chaîne invalide")

    monkeypatch.setattr(m5_outils, "_instantane_tarifs_equipes", illisible)
    total = cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total
    recu = _recu_wct(wct_id)
    assert (recu["statut"], recu["tentatives"], recu["derniere_erreur"]) == ("traite", 1, None), recu
    resultat = codec.decoder(recu["resultat"])
    assert (resultat["service_m4"], resultat["service_m4_code"]) == ("echec_publication", "TARIFS_ILLISIBLES")
    assert resultat["traite"] is True and resultat["cout_certifie"] == "marque"
    facture = rg._facture_du_devis(DEVIS)
    assert facture["statut"] == "BROUILLON"
    with stockage.transaction():
        assert list(stockage.maillons("m05-financecore", "wct_recus"))[0]["wct_id"] == wct_id
        assert list(stockage.maillons("m05-financecore", "rentabilite_service_v1")) == []
    assert _certifiees() == []
    courant = rg._evenement_courant_m5(DEVIS)
    assert courant["verdict"] == "PARTIELLE" and CODE_PERIME in courant["manque"], courant
    assert _statut() == "perime_recalcul_en_attente"
    # Le réconciliateur (actif, hors livraison) refuse avec un code typé, une fois par état : pas de boucle.
    refus = [j for j in _journal() if j["statut"] == "refus"]
    assert refus and {j["code"] for j in refus} == {"TARIFS_ILLISIBLES"}, _journal()
    assert len({j["intention_id"] for j in refus}) == len(refus)
    nombre = len(_journal())
    assert rc.reconcilier(deps)["raison"] == "etat_inchange"
    rc.reinitialiser()
    assert rc.reconcilier(deps)["refus"] == 1
    assert len(_journal()) == nombre
    # La cause est corrigée (registre des tarifs relisible, nouveau tarif déclaré) : nouvelle trace certifiée.
    monkeypatch.setattr(m5_outils, "_instantane_tarifs_equipes", original)
    rg._ajouter_tarif_equipe_un_autre_jour()
    rg._drainer(deps, 10)
    assert len(_certifiees()) == 1 and _statut() == "a_jour"
    assert rg._evenement_courant_m5(DEVIS)["verdict"] == "CALCULEE"
    assert _journal()[-1]["statut"] == "publiee" and _journal()[-1]["acteur"] == "opsys-systeme"
    assert _recu_wct(wct_id)["tentatives"] == 1  # la livraison n'a jamais été rejouée


def test_sans_politique_la_livraison_reste_l_ordinaire(base_durable, monkeypatch):
    """Contrôle : sans capacité (politique absente), aucune marque, aucune publication, statut `inconnu`."""
    monkeypatch.setattr(cm, "_poser_politique", lambda operation: None)
    deps = charger_departements()
    wct_id, _ = _chantier(deps)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    resultat = codec.decoder(_recu_wct(wct_id)["resultat"])
    assert "service_m4" not in resultat and _statut() == "inconnu"
    assert CODE_PERIME not in rg._evenement_courant_m5(DEVIS)["manque"]
