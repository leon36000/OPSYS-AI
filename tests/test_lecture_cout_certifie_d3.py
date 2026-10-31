"""D3 : la lecture admin de rentabilité montre la dernière trace certifiée et son statut explicite.

`m5_lire_rentabilite_chantier` (outil T0 admin) et la console « Coûts des travaux » disent `a_jour`,
`perime_recalcul_en_attente` ou `inconnu` ; jamais un certifié périmé présenté comme à jour. La console offre aussi
le recalcul à la demande (Option 4a, porte qualifiée E6, CSRF). Vraie voie, base éphémère, fictif.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path

import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from fastapi.testclient import TestClient

from opsys import contexte, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.evenements import reconciliateur_cout_certifie as rc


def _charger(nom_fichier, nom):
    if nom in sys.modules:
        return sys.modules[nom]
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(nom_fichier))
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


cm = _charger("test_cascade_marge_m5_m8_m10.py", "d3_helpers_cascade_marge")
rg = _charger("test_regression_cascade_cout_certifie.py", "d3_helpers_regression")
BASE = rg.BASE
LEAD, DEVIS, CHANTIER = "LEAD-D3-fictif", "DEVIS-D3-fictif", "CH-D3-fictif"
SECRET = "secret-d3-console-test-" + "x" * 32
PREFIXE = "/opsys"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-d3.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv(rc.ENV_MODE, "inactif")  # les transitions sont pilotées par le test
    stockage.migrer(url)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    rc.reinitialiser()
    try:
        yield url
    finally:
        m2_outils.reinitialiser_registre()
        stockage.liberer()


def _lire(*, autorise_couts=True, devis_id=DEVIS):
    admin = contexte.IdentiteAppelante(cm.ADMIN_CERTIFIE, "admin", source="console")
    with stockage.transaction(), contexte.appele_par_appareil(admin):
        arguments = {"autorise_couts": autorise_couts}
        if devis_id is not None:
            arguments["devis_id"] = devis_id
        reponse = m5_outils.lire_rentabilite_chantier(**arguments)
    assert reponse["accepte"] is True, reponse
    return reponse["resultat"]["chantiers"]


def _chantier():
    deps = charger_departements()
    cm._m6_prix_au_livre(cm._outils(deps, "m06-material-control"), rg.TARIF_PRIX_LIVRE)
    wct_id, _ = cm._chantier_termine(deps, BASE, LEAD, DEVIS, CHANTIER, 40.0, certifie=True)
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=4))
    return deps, wct_id


def test_l_outil_admin_dit_inconnu_a_jour_puis_perime_avec_la_derniere_trace_certifiee(base_durable):
    deps, wct_id = _chantier()
    (chantier,) = _lire()
    assert chantier["cout_certifie"] == {"statut": "inconnu"}
    cm._recalculer_cout_certifie(wct_id, DEVIS, "d3-premier")
    cm._drainer_sans_echec(deps, BASE + dt.timedelta(hours=5))
    (chantier,) = _lire()
    certifie = chantier["cout_certifie"]
    assert certifie["statut"] == "a_jour", certifie
    derniere = certifie["derniere_trace_certifiee"]
    assert derniere["verdict"] == "CALCULEE" and derniere["rentabilite"]["cout_reel_complet"] is True
    assert derniere["provenance"]["wct_id"] == wct_id and derniere["provenance"]["empreinte_projection"]
    assert derniere["sequence"] == len(rg._traces_m5(DEVIS))
    # le calcul ordinaire d'aujourd'hui reste partiel : les deux sont distincts et nommés
    assert chantier["rentabilite"]["verdict"] == "PARTIELLE"
    # Sans droit de voir les coûts : statut et verdict, aucun montant.
    (masque,) = _lire(autorise_couts=False)
    assert masque["cout_certifie"]["statut"] == "a_jour"
    assert masque["cout_certifie"]["derniere_trace_certifiee"]["rentabilite"]["montants_masques"] is True
    assert "provenance" in masque["cout_certifie"]["derniere_trace_certifiee"]  # détail : un devis précis
    # En liste : une ligne, sans provenance ni empreinte.
    (ligne,) = _lire(devis_id=None)
    assert ligne["cout_certifie"]["statut"] == "a_jour"
    assert "provenance" not in ligne["cout_certifie"]["derniere_trace_certifiee"]
    # Un changement réel (prix du livre) : jamais un certifié périmé présenté comme à jour.
    rg._evenement(deps, "prix_livre_change_puis_variance_relue", DEVIS, wct_id, 30)
    (chantier,) = _lire()
    assert chantier["cout_certifie"]["statut"] == "perime_recalcul_en_attente"
    assert chantier["cout_certifie"]["derniere_trace_certifiee"]["sequence"] == derniere["sequence"]
    # Même sans nouvelle trace (tarifs d'équipe changés, aucune cascade encore) : périmé, jamais à jour.
    cm._recalculer_cout_certifie(wct_id, DEVIS, "d3-second")
    assert _lire()[0]["cout_certifie"]["statut"] == "a_jour"
    rg._ajouter_tarif_equipe_un_autre_jour()
    assert _lire()[0]["cout_certifie"]["statut"] == "perime_recalcul_en_attente"


@pytest.fixture
def console(base_durable):
    app = application.creer_application(Configuration(SECRET), charger_departements(), stockage.transaction)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client):
    r = client.post("/connexion", data={"identifiant": cm.ADMIN_CERTIFIE,
                                        "mot_de_passe": "un-mot-de-passe-certifie-suffisamment-long"},
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    return client


def test_la_console_affiche_le_statut_et_recalcule_a_la_demande(console):
    deps, wct_id = _chantier()
    client = _connecter(console)
    chemin = f"/crm/lead/{LEAD}/soumissions/{DEVIS}/couts-travaux"
    page = client.get(chemin)
    assert page.status_code == 200, page.text
    assert 'data-statut-certifie="inconnu"' in page.text and "Recalculer le coût certifié maintenant" in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    # sans CSRF : refusé ; sans politique `m4.recalculer_v3` : refus typé, rien d'écrit
    assert client.post(chemin + "/recalcul-certifie", data={"csrf": "faux"},
                       follow_redirects=False).status_code == 403
    avant = rg._traces_m5(DEVIS)
    r = client.post(chemin + "/recalcul-certifie", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 409 and "POLITIQUE_ABSENTE" in r.text, r.text
    assert client.post(chemin + "/recalcul-certifie", data={"csrf": csrf, "montant": "1"},
                       follow_redirects=False).status_code == 400  # aucun montant n'entre
    assert rg._traces_m5(DEVIS) == avant
    cm._poser_politique("m4.recalculer_v3")
    r = client.post(chemin + "/recalcul-certifie", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303, r.text
    page = client.get(chemin)
    assert 'data-statut-certifie="a_jour"' in page.text and "Recalculer le coût certifié maintenant" not in page.text
    assert "Dernière trace certifiée" in page.text
    assert len(rg._traces_m5(DEVIS)) == len(avant) + 1
    # rejeu (double clic) : rien de plus
    r = client.post(chemin + "/recalcul-certifie", data={"csrf": csrf}, follow_redirects=False)
    assert r.status_code == 303 and len(rg._traces_m5(DEVIS)) == len(avant) + 1
    # le prix change : la console le dit périmé et propose le recalcul
    rg._evenement(deps, "prix_livre_change_puis_variance_relue", DEVIS, wct_id, 30)
    page = client.get(chemin)
    assert 'data-statut-certifie="perime_recalcul_en_attente"' in page.text
    assert "Périmé — recalcul en attente" in page.text
