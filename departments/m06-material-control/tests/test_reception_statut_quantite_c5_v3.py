"""M6 C5 : le statut par ligne doit rester cohérent avec la quantité reçue.

Tests publics sur SQLite et données fictives. Une ligne manquante est représentée
par une ligne reçue de quantité zéro, conformément au contrat historique.
"""

from __future__ import annotations

import m6_material_control.outils as m6_outils
import pytest
from m6_material_control import details_reception
from sqlalchemy import select

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import META

_DEPARTEMENT = "m06-material-control"
_PHOTO = "fichier:sha256:" + "ab" * 32
_HORODATAGE = "2026-10-06T14:30:00-04:00"


@pytest.fixture
def base_durable_m6(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-c5-statuts.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _outil(nom):
    return next(outil for outil in m6_outils.outils() if outil.nom == nom)


def _appeler(statut: str, quantite: float, **detail):
    po_id = "PO-STATUT-FICTIF"
    materiau_id = "mat-statut-fictif"
    arguments = {
        "bon_demande": {
            "po_id": po_id,
            "chantier_id": "CH-STATUT-FICTIF",
            "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": 5.0}],
            "horodatage": "2026-10-06T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": po_id,
            "chantier_id": "CH-STATUT-FICTIF",
            "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}],
            "horodatage": _HORODATAGE,
        },
        "details_reception": [{
            "materiau_id": materiau_id,
            "statut_ligne": statut,
            **detail,
        }],
    }
    return executer_atomique(_outil("m6_receptionner_commande"), arguments)


def _instantane_complet():
    stockage.liberer()
    with stockage.transaction() as cnx:
        return {
            table.name: sorted(repr(tuple(row)) for row in cnx.execute(select(table)))
            for table in META.sorted_tables
        }


@pytest.mark.parametrize(
    "statut, quantite, detail",
    [
        ("manquant", 5.0, {}),
        ("conforme", 0.0, {}),
        ("substitue", 0.0, {"materiau_substitue": "mat-substitut-fictif"}),
        ("endommage", 0.0, {"photos": [_PHOTO]}),
    ],
    ids=["manquant-positif", "conforme-zero", "substitue-zero", "endommage-zero"],
)
def test_refuse_statut_contradictoire_a_la_quantite_avant_toute_ecriture(
    base_durable_m6, statut, quantite, detail
):
    avant = _instantane_complet()

    reponse = _appeler(statut, quantite, **detail)

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-STATUT-QUANTITE-INCOHERENT"
    assert _instantane_complet() == avant


def test_manquant_zero_reste_representable_par_l_api_publique(base_durable_m6):
    reponse = _appeler("manquant", 0.0)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    accuse = reponse["resultat"]["resultat"]["accuse_reception"]
    assert accuse["lignes"][0]["quantite_recue"] == 0.0
    assert reponse["resultat"]["details_lignes"] == [{
        "materiau_id": "mat-statut-fictif",
        "statut_ligne": "manquant",
    }]


def test_une_contradiction_sur_une_ligne_tardive_refuse_le_lot_entier(base_durable_m6):
    avant = _instantane_complet()
    po_id = "PO-STATUT-MIXTE-FICTIF"
    arguments = {
        "bon_demande": {
            "po_id": po_id,
            "chantier_id": "CH-STATUT-FICTIF",
            "lignes_demandees": [
                {"materiau_id": "mat-valide-fictif", "quantite_demandee": 5.0},
                {"materiau_id": "mat-incoherent-fictif", "quantite_demandee": 5.0},
            ],
            "horodatage": "2026-10-06T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": po_id,
            "chantier_id": "CH-STATUT-FICTIF",
            "lignes_recues": [
                {"materiau_id": "mat-valide-fictif", "quantite_recue": 2.0},
                {"materiau_id": "mat-incoherent-fictif", "quantite_recue": 3.0},
            ],
            "horodatage": _HORODATAGE,
        },
        "details_reception": [
            {"materiau_id": "mat-valide-fictif", "statut_ligne": "conforme"},
            {"materiau_id": "mat-incoherent-fictif", "statut_ligne": "manquant"},
        ],
    }

    reponse = executer_atomique(_outil("m6_receptionner_commande"), arguments)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-STATUT-QUANTITE-INCOHERENT"
    assert _instantane_complet() == avant


@pytest.mark.parametrize(
    "statut, quantite, detail",
    [
        ("conforme", 2.0, {}),
        ("substitue", 2.0, {"materiau_substitue": "mat-substitut-fictif"}),
        ("endommage", 2.0, {"photos": [_PHOTO]}),
    ],
    ids=["conforme-positif", "substitue-positif", "endommage-positif"],
)
def test_statuts_de_lignes_physiquement_recues_gardent_leur_quantite_positive(
    base_durable_m6, statut, quantite, detail
):
    reponse = _appeler(statut, quantite, **detail)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert reponse["resultat"]["details_lignes"][0]["statut_ligne"] == statut
    assert reponse["resultat"]["resultat"]["accuse_reception"]["lignes"][0]["quantite_recue"] == quantite


def test_appel_historique_sans_details_reste_compatible(base_durable_m6):
    materiau_id = "mat-historique-fictif"
    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": "PO-HISTORIQUE-FICTIF",
            "chantier_id": "CH-STATUT-FICTIF",
            "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": 5.0}],
            "horodatage": "2026-10-06T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": "PO-HISTORIQUE-FICTIF",
            "chantier_id": "CH-STATUT-FICTIF",
            "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": 0.0}],
            "horodatage": _HORODATAGE,
        },
    })

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert "details_lignes" not in reponse["resultat"]


@pytest.mark.parametrize(
    "statut, quantite, attendu",
    [
        ("conforme", 2.0, None),
        ("manquant", 0.0, None),
        ("conforme", 0.0, "REJ-RECEPTION-STATUT-QUANTITE-INCOHERENT"),
        ("manquant", 2.0, "REJ-RECEPTION-STATUT-QUANTITE-INCOHERENT"),
        ("conforme", -1.0, "REJ-RECEPTION-QUANTITE-INVALIDE"),
    ],
    ids=["recu-positif", "manquant-zero", "recu-zero", "manquant-positif", "recu-negatif"],
)
def test_garde_pure_statut_quantite_refuse_zero_ou_negatif_incoherent(statut, quantite, attendu):
    details, code = details_reception.valider_details([{
        "materiau_id": "mat-helper-fictif",
        "statut_ligne": statut,
    }])
    assert code is None and details is not None
    code = details_reception.valider_coherence_statuts_quantites(details, [{
        "materiau_id": "mat-helper-fictif",
        "quantite_recue": quantite,
    }])
    assert code == attendu
