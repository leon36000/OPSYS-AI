"""C3 — les seuils de M6 sont des RÉGLAGES DE DIRECTION : décidés depuis la console (geste N3 du propriétaire), avec
retour arrière, au lieu de n'être éditables que dans `department.yaml`.

Les valeurs en vigueur aujourd'hui (écart de matériaux 0.30, écart de prix 0.15) viennent d'un AGENT, pas de Nathan : la
proposition est étiquetée « recommandation, non validée ». Vrais outils de M6, vrai sas N3, vraie console ; base SQLite
migrée ; données fictives.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import m6_material_control.outils as m6
import pytest
from fastapi.testclient import TestClient

from opsys import stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.reglages import lecture

RACINE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reglages_aide_m6", Path(__file__).with_name("reglages_aide.py"))
aide = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aide)

FICTIF = True
SECRET = "secret-reglages-m6-" + "x" * 40
VARIANCE = "m6.seuil_variance_chantier_pourcentage"
PRIX = "m6.seuil_ecart_prix_reception_pourcentage"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    deps = aide.installer(tmp_path, monkeypatch)
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"), deps, stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        r = client.post("/connexion", data={"identifiant": aide.PROPRIETAIRE, "mot_de_passe": aide.MOT_DE_PASSE},
                        follow_redirects=False)
        assert r.status_code == 303
        client.csrf = client.get("/api/session").json()["csrf"]
        client.deps = deps
        yield client
    stockage.liberer()


def _seuils():
    with stockage.transaction():
        return m6._seuil_variance_chantier(), m6._seuil_ecart_prix_reception()


def _adopter(client, cle, saisie):
    return client.post("/reglages/geste", data={"csrf": client.csrf, "action": "adopter", "cle": cle, "saisie": saisie,
                                                 "raison": "Décision de la direction"}, follow_redirects=False)


def _revenir(client, cle):
    return client.post("/reglages/geste", data={"csrf": client.csrf, "action": "revenir", "cle": cle,
                                                 "raison": "Retour au départ"}, follow_redirects=False)


def test_la_console_liste_les_deux_seuils_avec_la_proposition_non_validee_et_sa_source(monde):
    vue = {r["cle"]: r for r in monde.get("/api/reglages").json()["reglages"]}

    for cle, valeur in ((VARIANCE, "0.3"), (PRIX, "0.15")):
        r = vue[cle]
        assert r["departement"] == "m06-material-control" and r["niveau"] == "N3"
        assert r["manque"] is False and r["statut"] == "fichier", "la valeur d'agent de department.yaml est en vigueur"
        assert r["proposition"]["valeur"] == valeur
        assert r["proposition"]["etiquette"] == "recommandation, non validée"
        assert "department.yaml" in r["proposition"]["source"]


def test_sans_adoption_rien_ne_change_les_valeurs_du_fichier_restent_en_vigueur(monde):
    assert _seuils() == (0.30, 0.15)


def test_l_adoption_change_le_seuil_a_l_appel_suivant_et_le_retour_arriere_le_rend(monde):
    assert _adopter(monde, VARIANCE, "0.25").status_code == 303
    assert _adopter(monde, PRIX, "0.1").status_code == 303
    assert _seuils() == (0.25, 0.1)

    assert _revenir(monde, VARIANCE).status_code == 303
    assert _seuils() == (0.30, 0.1), "retour arrière : on retombe sur la valeur du fichier, pas sur « rien »"


@pytest.mark.parametrize("saisie", ["0", "0.001", "6", "beaucoup", "-0.2", "1e2", ""])
def test_une_valeur_hors_bornes_ou_illisible_n_est_jamais_adoptee(monde, saisie):
    reponse = _adopter(monde, VARIANCE, saisie)

    assert reponse.status_code in (303, 400, 422)
    assert _seuils()[0] == 0.30
    with stockage.transaction():
        assert lecture.adoptees().valeurs == {}


def test_un_employe_ou_un_administrateur_seul_ne_decide_pas_un_seuil(tmp_path, monkeypatch):
    deps = aide.installer(tmp_path, monkeypatch)
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe="/opsys"), deps, stockage.transaction)
    with TestClient(app, base_url="https://testserver/opsys") as client:
        client.post("/connexion", data={"identifiant": aide.ADMIN, "mot_de_passe": aide.MOT_DE_PASSE},
                    follow_redirects=False)
        client.csrf = client.get("/api/session").json()["csrf"]
        _adopter(client, VARIANCE, "0.25")
    assert _seuils()[0] == 0.30
    stockage.liberer()


def test_un_seuil_adopte_decide_ce_qui_est_critique_pour_un_chantier(monde):
    """28 % d'écart : sous 0.30, pas critique ; après adoption de 0.25, critique ; retour arrière, plus critique."""
    from m6_material_control import variance_chantier

    besoin = [{"materiau_id": "REV-FICTIF", "quantite_estimee": 100.0, "unite": "feuille"}]
    declare = [{"type_ligne": "prevu", "materiau_id": "REV-FICTIF", "quantite": 128.0, "unite": "feuille",
                "quantite_estimee": 100.0}]

    def critique():
        seuil = _seuils()[0]
        resultat, code = variance_chantier.evaluer("CH-1", besoin, declare, seuil)
        assert code is None
        return resultat["signal_variance_critique"] is not None

    assert critique() is False
    assert _adopter(monde, VARIANCE, "0.25").status_code == 303
    assert critique() is True
    assert _revenir(monde, VARIANCE).status_code == 303
    assert critique() is False
