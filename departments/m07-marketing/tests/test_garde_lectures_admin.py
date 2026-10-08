"""Les trois listes M7 confirment l'admin avant toute lecture (personnes fictives).

Une identité admin inconnue ne devient jamais une voie interne sans contexte.
La lecture n'exige pas nathan_owner et conserve les enveloppes directes existantes.
"""

from __future__ import annotations

import json

import pytest
from m7_marketing import outils as m7
from sqlalchemy import text

from opsys import contexte, identite, stockage
from opsys.outils import executer, executer_atomique

FICTIF = True
ADMIN = contexte.IdentiteAppelante("gestionnaire.fictif", "admin")
EMPLOYE = contexte.IdentiteAppelante("employe.fictif", "employee")
VENDEUR = contexte.IdentiteAppelante("vendeur.fictif", "seller")
LISTES = ("m7_lister_file_approbation", "m7_lister_demandes_avis", "m7_lister_contenus_chantier")


@pytest.fixture
def listes(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'lectures-m7-fictives.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m7.content_approval.reset()
    with stockage.transaction() as cnx:
        for acteur in (ADMIN, EMPLOYE, VENDEUR):
            identite.creer_personne(cnx, acteur.personne, "Personne fictive", "mot-de-passe-fictif-1234", [acteur.role])
    yield {o.nom: o for o in m7.outils() if o.nom in LISTES}
    m7.content_approval.reset()
    stockage.liberer()


def _etat():
    with stockage.transaction() as cnx:
        noms = cnx.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).scalars().all()
        return {nom: sorted(
            [dict(ligne) for ligne in cnx.execute(text(f'SELECT * FROM "{nom}"')).mappings()],
            key=lambda ligne: json.dumps(ligne, sort_keys=True, default=str),
        ) for nom in noms}


def _observer_lectures(monkeypatch):
    appels = {"file": 0, "registres": 0}
    file = m7.content_approval.list_items
    maillons = stockage.maillons

    def lire_file(*args, **kwargs):
        appels["file"] += 1
        return file(*args, **kwargs)

    def lire_registre(*args, **kwargs):
        appels["registres"] += 1
        return maillons(*args, **kwargs)

    monkeypatch.setattr(m7.content_approval, "list_items", lire_file)
    monkeypatch.setattr(stockage, "maillons", lire_registre)
    return appels


@pytest.mark.parametrize("nom", LISTES)
@pytest.mark.parametrize(("acteur", "perturbation"), [
    pytest.param(EMPLOYE, None, id="employe_actif"),
    pytest.param(VENDEUR, None, id="vendeur_actif"),
    pytest.param(contexte.IdentiteAppelante("fantome.fictif", "admin"), None, id="admin_inconnu"),
    pytest.param(ADMIN, "inactive", id="admin_inactif"),
    pytest.param(ADMIN, "role_retire", id="admin_role_retire"),
    pytest.param(contexte.IdentiteAppelante(EMPLOYE.personne, "admin"), None, id="role_admin_non_porte"),
])
def test_identite_refusee_avant_la_file_ou_le_registre(listes, monkeypatch, nom, acteur, perturbation):
    if perturbation is not None:
        with stockage.transaction() as cnx:
            if perturbation == "inactive":
                identite.activer(cnx, ADMIN.personne, False)
            else:
                identite.retirer_role(cnx, ADMIN.personne, "admin")
    avant = _etat()
    appels = _observer_lectures(monkeypatch)
    with contexte.appele_par_appareil(acteur):
        reponse = executer_atomique(listes[nom], {})
    assert reponse["ok"] is True
    assert isinstance(reponse["resultat"], dict) and reponse["resultat"].get("accepte") is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert appels == {"file": 0, "registres": 0}
    assert _etat() == avant


@pytest.mark.parametrize("nom", LISTES)
def test_admin_actif_non_proprietaire_lit_le_meme_resultat_direct_que_la_voie_interne(listes, nom):
    avant = _etat()
    interne = executer_atomique(listes[nom], {})
    with contexte.appele_par_appareil(ADMIN):
        admin = executer_atomique(listes[nom], {})
    assert admin == interne and admin["ok"] is True
    if nom == LISTES[0]:
        assert admin["resultat"] == []
    else:
        assert "accepte" not in admin["resultat"] and admin["resultat"]["total"] == 0
    assert _etat() == avant


@pytest.mark.parametrize("nom", LISTES)
def test_contexte_admin_hors_transaction_est_refuse_avant_lecture(listes, monkeypatch, nom):
    avant = _etat()
    appels = _observer_lectures(monkeypatch)
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer(listes[nom], {})
    assert reponse["ok"] is True
    assert isinstance(reponse["resultat"], dict) and reponse["resultat"].get("accepte") is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert appels == {"file": 0, "registres": 0}
    assert _etat() == avant


@pytest.mark.parametrize("nom", LISTES)
def test_apres_contexte_refuse_l_appel_interne_reste_autorise(listes, nom):
    avant = _etat()
    with contexte.appele_par_appareil(EMPLOYE):
        refuse = executer_atomique(listes[nom], {})
    assert isinstance(refuse["resultat"], dict) and refuse["resultat"].get("accepte") is False, refuse
    assert contexte.identite_appelante() is None
    assert executer_atomique(listes[nom], {})["ok"] is True
    if nom == LISTES[0]:
        assert executer(listes[nom], {}) == {"ok": True, "resultat": []}
    assert _etat() == avant
