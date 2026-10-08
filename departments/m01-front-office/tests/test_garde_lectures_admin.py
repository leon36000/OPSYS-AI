"""T4.26 : identité confirmée et date valide avant toute lecture M1 (personnes fictives)."""

from __future__ import annotations

import pytest
from m1_front_office import outils
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.outils import executer, executer_atomique
from opsys.stockage.schema import META

FICTIF = True
ADMIN = contexte.IdentiteAppelante("admin.fictif", "admin")
OWNER = contexte.IdentiteAppelante("owner.fictif", "nathan_owner", source="console")
LECTURES = ("m1_lire_transfert", "m1_produire_digest")


@pytest.fixture
def lectures(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'lectures-m1-fictives.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        for personne, role in ((ADMIN.personne, ADMIN.role), (OWNER.personne, OWNER.role),
                               ("employee.fictif", "employee"), ("seller.fictif", "seller"),
                               ("client.fictif", "client")):
            identite.creer_personne(cnx, personne, "Personne fictive", "mot-de-passe-fictif-1234", [role])
    yield {o.nom: o for o in outils.outils() if o.nom in LECTURES}
    outils.utiliser_stockage_durable()
    stockage.liberer()


def _args(nom):
    return {"date_reference": "2026-10-07"} if nom == "m1_produire_digest" else {"transfert_id": "tr-inconnu-fictif"}


def _etat():
    with stockage.transaction() as cnx:
        return tuple((t.name, tuple(tuple(r) for r in cnx.execute(select(t)))) for t in META.sorted_tables)


def _observer(monkeypatch):
    appels = []
    obtenir = outils._obtenir_registre

    def observer():
        appels.append("registre")
        return obtenir()

    monkeypatch.setattr(outils, "_obtenir_registre", observer)
    return appels


@pytest.mark.parametrize("nom", LECTURES)
@pytest.mark.parametrize("acteur", [
    contexte.IdentiteAppelante("employee.fictif", "employee"),
    contexte.IdentiteAppelante("seller.fictif", "seller"),
    contexte.IdentiteAppelante("client.fictif", "client"),
    contexte.IdentiteAppelante("inconnu.fictif", "admin"),
    contexte.IdentiteAppelante("employee.fictif", "admin"),
    contexte.IdentiteAppelante(OWNER.personne, OWNER.role),
])
def test_role_et_identite_refuses_avant_registre(lectures, monkeypatch, nom, acteur):
    avant = _etat()
    appels = _observer(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(lectures[nom], _args(nom))
    assert reponse["ok"] is True
    assert isinstance(reponse["resultat"], dict)
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert appels == [] and _etat() == avant


@pytest.mark.parametrize("nom", LECTURES)
@pytest.mark.parametrize("acteur", [ADMIN, OWNER])
@pytest.mark.parametrize("perte", ["role_retire", "inactive"])
def test_retrait_ou_inactivation_meme_identite_refuse_avant_registre(lectures, monkeypatch, nom, acteur, perte):
    with stockage.transaction() as cnx:
        if perte == "inactive":
            identite.activer(cnx, acteur.personne, False)
        else:
            identite.retirer_role(cnx, acteur.personne, acteur.role)
    avant = _etat()
    appels = _observer(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(lectures[nom], _args(nom))
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert appels == [] and _etat() == avant


@pytest.mark.parametrize("nom", LECTURES)
@pytest.mark.parametrize("acteur", [ADMIN, OWNER])
def test_admin_et_owner_console_confirme_conservent_enveloppe_interne(lectures, nom, acteur):
    avant = _etat()
    interne = executer_atomique(lectures[nom], _args(nom))
    with contexte.appele_par_appareil(acteur):
        assert executer_atomique(lectures[nom], _args(nom)) == interne
    assert _etat() == avant


@pytest.mark.parametrize("nom", LECTURES)
def test_hors_transaction_et_provenance_forgee_ne_donnent_pas_acces(lectures, monkeypatch, nom):
    appels = _observer(monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        assert executer(lectures[nom], _args(nom))["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    acteur = contexte.depuis_meta_mcp_identite({
        contexte.PERSONNE_META: OWNER.personne, contexte.ROLE_META: OWNER.role,
        "source": "console", "opsys/source": "console",
    })
    assert acteur is not None and acteur.source == "appareil"
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(lectures[nom], _args(nom))
        assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
        forge = executer_atomique(lectures[nom], {**_args(nom), "source": "console"})
    assert forge["ok"] is False and forge["erreur"] == "arguments_invalides"
    assert appels == []


@pytest.mark.parametrize("date_reference", ["", "2023-02-29", "2026-04-31", "0000-01-01", "2026-1-01",
                                             "２０２６-１０-０７", "2026-10-07\n", "2026-10-07T00:00:00Z"])
def test_date_invalide_refuse_nominalement_avant_registre(lectures, monkeypatch, date_reference):
    avant = _etat()
    appels = _observer(monkeypatch)
    reponse = executer_atomique(lectures["m1_produire_digest"], {"date_reference": date_reference})
    assert reponse["ok"] is True
    assert isinstance(reponse["resultat"], dict)
    assert reponse["resultat"]["verdict"]["code"] == "REJ-DIGEST-DATE-INVALIDE"
    assert appels == [] and _etat() == avant


def test_date_bissextile_et_interne_sans_identite_restent_valides(lectures):
    avant = _etat()
    reponse = executer_atomique(lectures["m1_produire_digest"], {"date_reference": "2024-02-29"})
    assert reponse == {
        "ok": True, "resultat": "Absence d'activité enregistrée pour la période de référence 2024-02-29.",
    }
    assert _etat() == avant
