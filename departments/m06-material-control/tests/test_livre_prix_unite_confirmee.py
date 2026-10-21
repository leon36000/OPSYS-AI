"""Unité explicite du tarif M6, sans inférence ni migration des anciennes entrées ; données fictives."""

from pathlib import Path

import pytest
from m6_material_control import contrats, livre_prix, outils

from opsys import stockage
from opsys.outils import executer, executer_atomique

FICTIF = True


def _arguments(**surcharges):
    return {
        "materiau_id": "alu-fictif", "fournisseur_id": "gentek-fictif", "prix_unitaire": 8,
        "devise": "CAD", "date_effet": "2026-09-01", **surcharges,
    }


def _outil():
    assert Path(outils.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1] / "src")
    return next(o for o in outils.outils() if o.nom == "m6_enregistrer_prix")


def test_schema_public_accepte_et_restitue_unite_explicite():
    reponse = executer(_outil(), _arguments(unite="pi"))

    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["unite"] == "pi"
    assert reponse["resultat"]["livre_prix_historique"][0]["unite"] == "pi"
    assert "unite" in contrats.CHAMPS_ENTREE_PRIX_OPTIONNELS


def test_unite_traverse_outil_transaction_et_relecture_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'unite-tarif-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        reponse = executer_atomique(_outil(), _arguments(unite="pi"))
        assert reponse["ok"] is True, reponse
        assert reponse["resultat"]["accepte"] is True
        stockage.liberer()
        with stockage.transaction():
            (entree,) = list(stockage.maillons("m06-material-control", "livre_prix"))
        assert entree["unite"] == "pi"
        assert entree["prix_unitaire"] == 8
    finally:
        stockage.liberer()


@pytest.mark.parametrize("unite", ["", "  ", 123, True])
def test_unite_fournie_invalide_refuse_sans_ajouter_de_tarif(unite):
    registre = []
    entree, verdict = livre_prix.enregistrer_prix(
        "alu-fictif", "gentek-fictif", 8, "CAD", "2026-09-01", registre, unite=unite,
    )

    assert entree is None
    assert verdict["code"] == "REJ-PRIX-STRUCTURE-INVALIDE"
    assert registre == []


def test_anciens_arguments_positionnels_ne_fabriquent_pas_unite():
    registre = []
    entree, verdict = livre_prix.enregistrer_prix(
        "alu-fictif", "gentek-fictif", 8, "CAD", "2026-09-01", registre, "FACT-fictif",
    )
    assert verdict is None and "unite" not in entree
    assert entree["source_document"] == "FACT-fictif"
    reponse = outils.enregistrer_prix(
        "alu-fictif", "gentek-fictif", 9, "CAD", "2026-09-02", "FACT2-fictif", registre,
    )
    assert reponse["accepte"] is True and "unite" not in reponse["resultat"]
    assert len(reponse["livre_prix_historique"]) == 2
    assert registre[0] == entree


def test_unite_confirmee_reste_compatible_avec_resolution_po():
    reponse = executer(_outil(), _arguments(unite="pi"))
    assert reponse["ok"] is True, reponse
    livre = reponse["resultat"]["livre_prix_historique"]
    resolution = livre_prix.resoudre_prix_po("alu-fictif", "gentek-fictif", livre)
    assert resolution["verdict_prix"] == "PRIX_LIVRE"
    assert resolution["prix_unitaire"] == 8
