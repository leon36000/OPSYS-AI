"""Charge modeste sur le VRAI bus : 1 000 événements de cinq types, six consommateurs réels, sans perte ni doublon.

Compte exact des registres des départements destinataires (ni plus ni moins que les constats distincts), reçus tous
`traite`, aucune quarantaine, rejeu complet (mêmes constats sous d'autres identifiants) sans aucun maillon de plus, et
reprise après une panne de M8 au milieu du lot. Données fictives.
"""

from __future__ import annotations

import time

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest

from opsys import evenements

FICTIF = True
M2, M5, M6, M7, M8, M9, M10 = (
    "m02-revenue-crm",
    "m05-financecore",
    "m06-material-control",
    "m07-marketing",
    "m08-analytics",
    "m09-strategic-intelligence",
    "m10-memoire",
)
N_DEPENSES, N_ANOMALIES, N_CONVERSIONS, N_DOSSIERS, N_RAPPROCHEMENTS = 300, 300, 200, 100, 100
TOTAL = N_DEPENSES + N_ANOMALIES + N_CONVERSIONS + N_DOSSIERS + N_RAPPROCHEMENTS
ATTENDU = {
    (M8, "faits_operations"): N_DEPENSES + N_ANOMALIES + N_CONVERSIONS,
    (M5, "charges_marketing_recues"): N_DEPENSES,
    (M5, "grand_livre"): N_DEPENSES,
    (M9, "signaux_gestion_recus"): N_ANOMALIES,
    (M2, "conversions_hors_ligne_recues"): N_CONVERSIONS,
    (M10, "dossiers_cpa_scelles"): N_DOSSIERS,
    (M6, "rapprochements_facture_recus"): N_RAPPROCHEMENTS,
}
LIVRAISONS_ATTENDUES = 2 * N_DEPENSES + 2 * N_ANOMALIES + 2 * N_CONVERSIONS + N_DOSSIERS + N_RAPPROCHEMENTS


@pytest.fixture
def monde(tmp_path, monkeypatch):
    m = im.monter(tmp_path, monkeypatch, (M2, M5, M6, M7, M8, M9, M10))
    m.surveiller(monkeypatch)
    yield m
    im.demonter()


def _publier_lot(suffixe=""):
    for i in range(N_DEPENSES):
        evenements.publier(
            "m7.depenses_marketing_constatees",
            M7,
            ch.depense_marketing(releve_id=f"charge-rel-{i}"),
            evenement_id=f"dep{suffixe}-{i}",
        )
    for i in range(N_ANOMALIES):
        evenements.publier(
            "m7.anomalie_depense_detectee",
            M7,
            ch.anomalie_depense(anomalie_id=f"{i:032x}"),
            evenement_id=f"ano{suffixe}-{i}",
        )
    for i in range(N_CONVERSIONS):
        evenements.publier(
            "m7.conversion_hors_ligne_importee",
            M7,
            ch.conversion_hors_ligne(conversion_id=f"conv-{i}", lead_id=f"lead-charge-{i}"),
            evenement_id=f"conv{suffixe}-{i}",
        )
    for i in range(N_DOSSIERS):
        evenements.publier(
            "m5.dossier_cpa_scelle", M5, ch.dossier_cpa(dossier_id=f"dossier-{i}"), evenement_id=f"cpa{suffixe}-{i}"
        )
    for i in range(N_RAPPROCHEMENTS):
        evenements.publier(
            "m5.rapprochement_po_constate",
            M5,
            ch.rapprochement_po(facture=f"ff-charge-{i}"),
            evenement_id=f"rap{suffixe}-{i}",
        )


def _tailles(monde):
    return {cle: monde.taille(*cle) for cle in ATTENDU}


def test_mille_evenements_sans_perte_ni_doublon_puis_rejeu_complet_sans_effet(monde):
    _publier_lot()
    assert len(monde.sortants()) == TOTAL == 1000
    debut = time.monotonic()
    total = monde.repartir(passes=12, limite=500)
    duree = time.monotonic() - debut
    assert total["quarantaines"] == 0 and total["echecs"] == 0, total
    assert total["traites"] == LIVRAISONS_ATTENDUES, total
    assert _tailles(monde) == ATTENDU
    recus = monde.recus()
    assert len(recus) == LIVRAISONS_ATTENDUES and {r["statut"] for r in recus} == {"traite"}
    assert len({(r["evenement_id"], r["consommateur"]) for r in recus}) == LIVRAISONS_ATTENDUES  # aucun reçu en double
    assert monde.quarantaines() == [] and monde.ecritures_hors_propriete() == []
    assert duree < 600, f"charge modeste trop lente : {duree:.0f} s"
    # Les mêmes 1 000 constats sous d'AUTRES identifiants : livrés, mais aucun maillon de plus nulle part.
    _publier_lot("-bis")
    total = monde.repartir(passes=12, limite=500)
    assert total["quarantaines"] == 0 and total["echecs"] == 0 and total["traites"] == LIVRAISONS_ATTENDUES
    assert _tailles(monde) == ATTENDU
    assert monde.quarantaines() == []


def test_panne_de_m8_au_milieu_du_lot_reprise_sans_perte_ni_doublon(monde):
    _publier_lot()
    monde.pannes.add(M8)
    premier = monde.repartir(passes=1, limite=400)
    assert premier["quarantaines"] == 0 and premier["echecs"] > 0
    assert monde.taille(M8, "faits_operations") == 0
    monde.pannes.clear()
    total = monde.repartir(passes=14, limite=500)
    assert total["quarantaines"] == 0
    assert _tailles(monde) == ATTENDU
    assert {r["statut"] for r in monde.recus()} == {"traite"}
    assert monde.quarantaines() == []
