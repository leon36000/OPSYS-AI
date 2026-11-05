from types import SimpleNamespace

import pytest

from opsys import outils
from opsys.memoire import outils as outils_memoire


def test_rechercher_refuse_un_element_portee_non_chaine_avant_toute_recherche(monkeypatch):
    public = next(o for o in outils_memoire.outils() if o.nom == "opsys_memoire_rechercher")
    marqueur = "NE-PAS-ECHO-FICTIF"
    arguments = {"requete": "question fictive", "portees": [{"portee": marqueur}]}

    def aucun_acces():
        pytest.fail("la recherche ou l'autorité ne doit pas être consultée pour un argument mal formé")

    monkeypatch.setattr(outils_memoire, "departement_appelant", aucun_acces)
    monkeypatch.setattr(outils_memoire, "_memoire", aucun_acces)
    reponse = outils.executer(public, arguments)
    assert reponse["ok"] is False
    assert reponse["erreur"] in {"arguments_invalides", "refus_metier"}
    assert marqueur not in repr(reponse)


def test_rechercher_accepte_une_liste_de_portees_chaine(monkeypatch):
    class AccesApresValidation(Exception):
        pass

    monkeypatch.setattr(
        outils_memoire,
        "departement_appelant",
        lambda: SimpleNamespace(id="m01-front-office", memoire_lecture=("procedures",)),
    )
    monkeypatch.setattr(outils_memoire, "_memoire", lambda: (_ for _ in ()).throw(AccesApresValidation()))

    with pytest.raises(AccesApresValidation):
        outils_memoire.rechercher("question fictive", ["procedures"])
