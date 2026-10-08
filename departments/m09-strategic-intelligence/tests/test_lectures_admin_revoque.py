"""Identités et registres fictifs : refus de lectures M9 avant tout accès métier."""
from unittest.mock import Mock

import pytest
from m9_strategic_intelligence import outils as module

from opsys import contexte, identite, stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import executer_atomique

FICTIF = True
MAINTENANT = "2026-10-08T07:00:00-04:00"
LECTURES = [
    ("m9_lire_etat_consolide", {}),
    ("m9_lire_alertes_m8", {}),
    ("m9_produire_briefing_matin", {"maintenant": MAINTENANT}),
    ("m9_lire_suite_briefing", {"maintenant": MAINTENANT, "section": "alertes_m8"}),
    ("m9_produire_lecture_strategique", {"maintenant": MAINTENANT}),
]


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'identites-fictives.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    # Aucune authentification de mot de passe testée ici ; identité/roles réels en SQLite.
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "hachage-fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        for personne, role, actif in [
            ("admin.fictif", "admin", True), ("employe.fictif", "employee", True),
            ("vendeur.fictif", "seller", True), ("ancien.fictif", "admin", False),
        ]:
            identite.creer_personne(cnx, personne, personne, "fictif-mot-de-passe", [role], actif=actif)
    yield
    stockage.liberer()


@pytest.fixture
def lectures_bloquees(base, monkeypatch):
    lire_registre = Mock(side_effect=AssertionError("registre M9 lu avant refus"))
    class RegistreFerme:
        lire = lire_registre
    class AlertesFermees:
        def __iter__(self):
            lire_registre()
            return iter(())
    outils = {o.nom: o for o in module.outils(registre_cible=RegistreFerme(), alertes_cible=AlertesFermees())}
    lire_file = Mock(side_effect=AssertionError("file propriétaire lue avant refus"))
    monkeypatch.setattr(module.approbations, "compter", lire_file)
    return outils, lire_registre, lire_file


@pytest.mark.parametrize("nom,args", LECTURES)
@pytest.mark.parametrize("appelante", [
    IdentiteAppelante("employe.fictif", "employee"), IdentiteAppelante("vendeur.fictif", "seller"),
    IdentiteAppelante("employe.fictif", "admin"), IdentiteAppelante("ancien.fictif", "admin"),
    IdentiteAppelante("inconnu.fictif", "admin"), IdentiteAppelante("admin.fictif", "employee"),
])
def test_refus_avant_registres_et_file(lectures_bloquees, nom, args, appelante):
    outils, registre, file = lectures_bloquees
    with contexte.appele_par_appareil(appelante):
        reponse = executer_atomique(outils[nom], args)
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier", reponse
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")
    registre.assert_not_called()
    file.assert_not_called()


@pytest.mark.parametrize("nom,args", LECTURES)
def test_role_retire_depuis_emission_du_jeton(lectures_bloquees, nom, args):
    outils, registre, file = lectures_bloquees
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        reponse = executer_atomique(outils[nom], args)
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier", reponse
    assert reponse["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE")
    registre.assert_not_called()
    file.assert_not_called()


@pytest.mark.parametrize("nom,args", LECTURES)
def test_admin_hors_transaction_refuse(lectures_bloquees, nom, args):
    outils, registre, file = lectures_bloquees
    with (
        contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")),
        pytest.raises(ValueError, match="REJ-IDENTITE-APPAREIL-INVALIDE"),
    ):
        outils[nom].fonction(**args)
    registre.assert_not_called()
    file.assert_not_called()


@pytest.mark.parametrize("nom,args", LECTURES)
@pytest.mark.parametrize("appareil", [True, False])
def test_admin_valide_et_voie_agents_conservent_la_lecture(base, nom, args, appareil):
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin") if appareil else None):
        outils = {o.nom: o for o in module.outils()}
        reponse = executer_atomique(outils[nom], args)
    assert reponse["ok"] is True, reponse
    assert "resultat" in reponse
