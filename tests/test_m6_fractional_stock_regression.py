"""Régression CDX-01 : les quantités déclarées sont décimales, sans tolérance de stock.

Fixtures entièrement fictives. L'intégration publie un WCT synthétique conforme dans le
vrai bus ; elle qualifie le consommateur transactionnel M6, pas la production de ce WCT par M4.
"""

from __future__ import annotations

import pytest
from m6_material_control import materiel, registre, stock

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
CHANTIER = "chantier-fractions-fictif"
MATERIAU = "gouttiere-fractions-fictif"


def _wct():
    return {
        "wct_id": "wct-fractions-fictif", "intervention_id": "intervention-fractions-fictif",
        "lead_id": "lead-fractions-fictif", "technicien_id": "technicien-fractions-fictif",
        "horodatage_completion": "2026-10-22T00:00:00Z", "fix_gps_completion": {},
        "duree_reelle_minutes": 30, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 64, "consommateurs_cibles": ["M6"], "devis_id": None,
    }


def _formulaire(quantites):
    return {
        "wct_id": _wct()["wct_id"], "intervention_id": _wct()["intervention_id"],
        "chantier_id": CHANTIER,
        "lignes_consommees": [{"materiau_id": MATERIAU, "quantite": q} for q in quantites],
    }


def _mouvement(quantite):
    return {
        "type_mouvement": "RECEPTION" if quantite > 0 else "CONSOMMATION",
        "chantier_id": CHANTIER, "materiau_id": MATERIAU,
        "quantite": quantite, "cout_unitaire": 1.0,
    }


@pytest.mark.parametrize(("historique", "quantites", "restant"), [
    ([0.3], [0.1, 0.2], 0.0),
    ([0.3, -0.1], [0.2], 0.0),
    ([0.1, 0.2], [0.3], 0.0),
    ([0.3], [0.1], 0.2),
    ([3.0], [1.0, 2.0], 0.0),
    ([0.3], [0.30000000000000004], None),
    ([0.3], [0.4], None),
])
def test_consommation_compare_les_quantites_decimales_sans_epsilon(historique, quantites, restant):
    cible = registre.Registre()
    _, erreur = cible.ajouter_lot([_mouvement(q) for q in historique])
    assert erreur is None
    avant = cible.lire()
    confirmation, erreur = materiel.consommer_materiaux(
        _wct(), _formulaire(quantites), cible, wct_id=_wct()["wct_id"],
    )
    if restant is None:
        assert confirmation is None
        assert erreur == "REJ-STOCK-INSUFFISANT"
        assert cible.lire() == avant
    else:
        assert erreur is None
        assert confirmation["stock_restant"] == [
            {"materiau_id": MATERIAU, "quantite": restant} for _ in quantites
        ]
        assert stock.deriver_stock_theorique(CHANTIER, MATERIAU, cible) == restant
        assert isinstance(confirmation["stock_restant"][0]["quantite"], float)
        apres = cible.lire()
        assert len(apres) == len(avant) + len(quantites)
        assert all(m["wct_id"] == _wct()["wct_id"] for m in apres[len(avant):])
        assert materiel.consommer_materiaux(
            _wct(), _formulaire(quantites), cible, wct_id=_wct()["wct_id"],
        ) == (None, "REJ-DECLARATION-DEJA-SOUMISE")
        assert cible.lire() == apres
    assert cible.valider_chaine() == (True, "")


@pytest.fixture
def sqlite_fictive(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-fractions-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield
    finally:
        stockage.liberer()


@pytest.mark.parametrize(("quantites", "accepte"), [([0.1, 0.2], True), ([0.30000000000000004], False)])
def test_consommation_transactionnelle_garde_wct_stock_et_rejeu(sqlite_fictive, quantites, accepte):
    outil = next(o for o in charger_departements()["m06-material-control"].charger_outils()
                 if o.nom == "m6_consommer_materiaux")
    arguments = {"wct": _wct(), "formulaire": _formulaire(quantites)}
    with stockage.transaction():
        cible = registre.Registre(stockage.maillons("m06-material-control", "principal"))
        _, erreur = cible.ajouter(_mouvement(0.3))
        assert erreur is None
        avant = cible.lire()

    inconnu = executer_atomique(outil, arguments)
    assert inconnu["ok"]
    assert inconnu["resultat"] == {"accepte": False, "verdict": {"code": "REJ-WCT-INCONNU"}}
    with stockage.transaction():
        assert list(stockage.maillons("m06-material-control", "principal")) == avant
        charge = {**_wct(), "statut": "completed_verified"}
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=charge["wct_id"])

    # Le contenu transporté ne fait pas autorité : seul le WCT canonique publié est utilisé.
    arguments["wct"] = {**_wct(), "consommateurs_cibles": []}
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"], reponse
    assert reponse["resultat"]["accepte"] is accepte, reponse
    with stockage.transaction():
        cible = registre.Registre(stockage.maillons("m06-material-control", "principal"))
        apres = cible.lire()
        assert cible.valider_chaine() == (True, "")
        if accepte:
            assert len(apres) == 3
            assert [m["quantite"] for m in apres] == [0.3, -0.1, -0.2]
            assert stock.deriver_stock_theorique(CHANTIER, MATERIAU, cible) == 0.0
            assert reponse["resultat"]["registre"]["hash_tete"] == cible.hash_tete()
        else:
            assert apres == avant
            assert reponse["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    if accepte:
        rejeu = executer_atomique(outil, arguments)
        assert rejeu["ok"]
        assert rejeu["resultat"] == {
            "accepte": False, "verdict": {"code": "REJ-DECLARATION-DEJA-SOUMISE"},
        }
        with stockage.transaction():
            assert list(stockage.maillons("m06-material-control", "principal")) == apres
