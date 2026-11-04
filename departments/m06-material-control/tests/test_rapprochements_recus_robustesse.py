"""Robustesse des lectures C4 (`rapprochements_recus.py`) : un maillon incomplet en base est IGNORÉ et compté,
jamais une exception qui rend toute la file d'attentes M6 inutilisable. Le registre est append-only, mais la base
reste éditable hors outil (administrateur de base, migration) : la lecture ne doit pas en dépendre.

Données fictives ; module pur.
"""

from __future__ import annotations

from m6_material_control import rapprochements_recus

FICTIF = True


def _charge(**plus):
    base = {
        "facture_fournisseur_id": "F-1",
        "po_id": "PO-1",
        "verdict": "ECART",
        "sens": None,
        "facture_avant_taxes": "50.00",
        "recu_avant_taxes": "40.00",
        "ecart_avant_taxes": "10.00",
        "reserves": [],
        "date_reference": "2026-11-06",
    }
    base.update(plus)
    return base


def test_un_maillon_sans_date_reference_est_ignore_et_compte():
    maillons = [rapprochements_recus.fait(_charge()), {"type_entree": rapprochements_recus.TYPE_ENTREE}]

    assert [a["id"] for a in rapprochements_recus.attentes(maillons)] == ["F-1"]
    assert len(rapprochements_recus.derniers_etats(maillons)) == 1
    assert rapprochements_recus.compter_ignores(maillons) == 1


def test_une_proposition_ne_leve_pas_sur_maillon_incomplet():
    maillons = [{"type_entree": rapprochements_recus.TYPE_ENTREE,
                 "facture_fournisseur_id": "F-1", "po_id": "PO-1", "verdict": "CONCORDANT"}]

    assert rapprochements_recus.propositions_facturation(maillons, [{"po_id": "PO-1", "statut": "received"}]) == []
    assert rapprochements_recus.attentes(maillons) == []
    assert rapprochements_recus.compter_ignores(maillons) == 1


def test_un_maillon_avec_date_reference_non_textuelle_est_ignore_sans_lever():
    maillons = [
        {"type_entree": rapprochements_recus.TYPE_ENTREE, "facture_fournisseur_id": "F-1",
         "po_id": "PO-1", "verdict": "ECART", "sens": None, "facture_avant_taxes": "50.00",
         "recu_avant_taxes": "40.00", "ecart_avant_taxes": "10.00", "reserves": [],
         "date_reference": ["2026-11-06"]},
        rapprochements_recus.fait(_charge(facture_fournisseur_id="F-2")),
    ]

    assert [a["id"] for a in rapprochements_recus.attentes(maillons)] == ["F-2"]
    assert rapprochements_recus.compter_ignores(maillons) == 1


def test_un_maillon_etranger_n_est_pas_compte_comme_malforme():
    maillons = [42, {"type_entree": "autre"}, rapprochements_recus.fait(_charge())]

    assert rapprochements_recus.compter_ignores(maillons) == 0
    assert list(rapprochements_recus.derniers_etats(maillons)) == ["F-1"]


def test_derniers_etats_prefere_la_publication_la_plus_recente_puis_l_ordre_d_arrivee():
    plus_recente = rapprochements_recus.fait(
        _charge(verdict="ECART"), publie_le="2026-11-06T11:00:00+00:00")
    plus_ancienne = rapprochements_recus.fait(
        _charge(verdict="CONCORDANT"), publie_le="2026-11-06T10:00:00+00:00")

    assert rapprochements_recus.derniers_etats([plus_recente, plus_ancienne])["F-1"]["verdict"] == "ECART"

    meme_instant = [
        rapprochements_recus.fait(_charge(verdict="ECART"), publie_le="2026-11-06T10:00:00+00:00"),
        rapprochements_recus.fait(_charge(verdict="CONCORDANT"), publie_le="2026-11-06T10:00:00+00:00"),
    ]
    assert rapprochements_recus.derniers_etats(meme_instant)["F-1"]["verdict"] == "CONCORDANT"


def test_une_date_de_reference_plus_ancienne_arrivee_apres_ne_remplace_pas_la_plus_recente():
    recente = rapprochements_recus.fait(_charge(date_reference="2026-11-06", verdict="CONCORDANT"))
    ancienne = rapprochements_recus.fait(_charge(date_reference="2026-11-05", verdict="ECART"))

    assert rapprochements_recus.derniers_etats([recente, ancienne])["F-1"]["verdict"] == "CONCORDANT"
