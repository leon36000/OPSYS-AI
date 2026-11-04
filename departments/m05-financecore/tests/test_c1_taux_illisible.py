"""C1 : les défauts de lecture du fichier de taux doivent rendre le verdict M5 nommé."""
from __future__ import annotations

import m5_financecore.outils as outils_m5
import m5_financecore.taux_fiscaux as taux_fiscaux
import pytest

from opsys.outils import executer


@pytest.mark.parametrize(
    ("etat", "contenu"),
    [
        ("absent", None),
        ("yaml_invalide", b"schema_version: [\n"),
        ("utf8_invalide", b"\xff"),
    ],
)
def test_outil_public_calcul_taxes_rend_refus_taux_nomme_pour_fichier_illisible(
    etat, contenu, tmp_path, monkeypatch
):
    chemin = tmp_path / "taux-fictifs.yaml"
    if etat != "absent":
        chemin.write_bytes(contenu)
    monkeypatch.setattr(outils_m5, "_CHEMIN_TAUX_FISCAUX", chemin)
    outil = next(o for o in outils_m5.outils() if o.nom == "m5_calculer_taxes_tps_tvq")

    reponse = executer(outil, {"montant_avant_taxes": "100.00"})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-TAUX-FICHIER-INVALIDE"


@pytest.mark.parametrize(
    ("etat", "contenu"),
    [
        ("absent", None),
        ("yaml_invalide", b"schema_version: [\n"),
        ("utf8_invalide", b"\xff"),
    ],
)
def test_outil_public_rapprochement_rend_refus_taux_nomme_pour_fichier_illisible(
    etat, contenu, tmp_path, monkeypatch
):
    chemin = tmp_path / "taux-fictifs.yaml"
    if etat != "absent":
        chemin.write_bytes(contenu)
    monkeypatch.setattr(outils_m5, "_CHEMIN_TAUX_FISCAUX", chemin)
    monkeypatch.setattr(outils_m5, "_stockage_durable_actif", True)
    monkeypatch.setattr(
        outils_m5.stockage,
        "lire_instantane_maillons",
        lambda _departement, noms: {nom: [] for nom in noms},
    )
    outil = next(o for o in outils_m5.outils() if o.nom == "m5_rapprocher_grand_livre")

    reponse = executer(outil, {"debut": "2026-10-01", "fin": "2026-10-31"})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-TAUX-FICHIER-INVALIDE"


def test_lecture_taux_ne_masque_pas_exception_de_programmation(monkeypatch):
    def erreur_inattendue(*_args, **_kwargs):
        raise RuntimeError("erreur de programmation fictive")

    monkeypatch.setattr(taux_fiscaux.Path, "read_text", erreur_inattendue)
    outil = next(o for o in outils_m5.outils() if o.nom == "m5_calculer_taxes_tps_tvq")

    with pytest.raises(RuntimeError, match="erreur de programmation fictive"):
        executer(outil, {"montant_avant_taxes": "100.00"})
