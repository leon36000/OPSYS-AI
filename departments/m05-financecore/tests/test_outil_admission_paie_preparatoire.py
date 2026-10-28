"""Diagnostic propriétaire, SQLite et identités FICTIFS ; aucun calcul de paie."""

import pytest

FICTIF = True
NOM = "m5_verifier_admission_paie_preparatoire"
CONTEXTE = {"annee": 2026, "date_paie": "2026-10-23", "juridiction": "QC",
            "frequence": "bihebdomadaire", "periode_annuelle": 22, "pm": 12}


def _outil():
    from m5_financecore import outils

    return next((o for o in outils.outils() if o.nom == NOM), None)


def test_contrat_lecture_console_ferme_sans_droit_appareil():
    from m5_financecore import analyse

    from opsys.console import metier
    from opsys.outils import Autonomie, valider_arguments

    outil = _outil()
    assert outil is not None
    assert outil.autonomie is Autonomie.T0
    assert outil.roles_appareil == frozenset()
    assert set(outil.parametres["properties"]) == set(CONTEXTE)
    assert not valider_arguments(outil.parametres, CONTEXTE)
    assert valider_arguments(outil.parametres, {**CONTEXTE, "chemin_configuration": "/tmp/fictif.json"})
    assert metier.LECTURES[NOM] == "m05-financecore"
    assert NOM in analyse.SORTIES_HORS_ANALYSE


@pytest.fixture
def base_sqlite(monkeypatch, tmp_path):
    from m5_financecore import outils

    from opsys import identite, stockage

    url = f"sqlite:///{tmp_path / 'admission-fictive.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "owner.fictif", "Owner fictif", "QA-fictive-only-identity", ["nathan_owner", "admin"],
        )
        identite.creer_personne(cnx, "employee.fictif", "Employee fictif", "QA-fictive-only-employee", ["employee"])
    yield
    stockage.liberer()


def _appeler(personne, role, source):
    from opsys import contexte
    from opsys.outils import executer_atomique

    appelante = None if personne is None else contexte.IdentiteAppelante(personne, role, source=source)
    with contexte.appele_par_appareil(appelante):
        return executer_atomique(_outil(), CONTEXTE)


def test_vrai_owner_console_obtient_refus_documentaire_sans_mouvement(base_sqlite):
    from opsys import stockage

    avant = list(stockage.maillons("m05-financecore", "principal"))
    reponse = _appeler("owner.fictif", "nathan_owner", "console")
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["admissible"] is False  # les captures officielles ne sont pas livrées
    assert resultat["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert resultat["actions_financieres_bloquees"] is True
    assert resultat["autorisation_outil_ou_acteur"] is False
    assert all("CAPTURE_INDISPONIBLE_OU_LIEE" in m for m in resultat["motifs"])
    assert list(stockage.maillons("m05-financecore", "principal")) == avant


@pytest.mark.parametrize("personne,role,source", [
    (None, None, "console"),
    ("owner.fictif", "admin", "appareil"),
    ("owner.fictif", "nathan_owner", "appareil"),
    ("employee.fictif", "nathan_owner", "console"),
])
def test_autorite_refusee_avant_lecture_configuration(base_sqlite, monkeypatch, personne, role, source):
    from m5_financecore import outils

    def interdit(**_arguments):
        pytest.fail("Configuration consultée avant autorité propriétaire console SQL")

    monkeypatch.setattr(outils, "_admission_paie_serveur", interdit)
    resultat = _appeler(personne, role, source)
    assert resultat["ok"] is True
    assert resultat["resultat"]["accepte"] is False


def test_role_revoque_refuse_avec_meme_identite(base_sqlite, monkeypatch):
    from m5_financecore import outils

    from opsys import identite, stockage

    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "owner.fictif", "nathan_owner")

    def interdit(**_arguments):
        pytest.fail("Configuration consultée après révocation SQL")

    monkeypatch.setattr(outils, "_admission_paie_serveur", interdit)
    resultat = _appeler("owner.fictif", "nathan_owner", "console")
    assert resultat["ok"] is True
    assert resultat["resultat"]["accepte"] is False


def test_route_backend_console_reutilise_manifeste_et_identite_sql(base_sqlite):
    from pathlib import Path

    from m5_financecore import outils

    from opsys import stockage
    from opsys.console import metier
    from opsys.console.securite import Session
    from opsys.departements import lire_manifeste

    departement = lire_manifeste(Path(outils.__file__).resolve().parents[2])
    session = Session("owner.fictif", frozenset({"nathan_owner", "admin"}), "CSRF-fictif-QA", 4102444800)
    with stockage.transaction() as cnx:
        reponse = metier.executer(cnx, {departement.id: departement}, session, NOM, CONTEXTE)
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["admissible"] is False
    assert reponse["resultat"]["resultat"]["actions_financieres_bloquees"] is True
